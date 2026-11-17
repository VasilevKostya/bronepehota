#!/usr/bin/env python3
"""Private Flarum storage, consistent backups and isolated restore checks."""

import argparse
from contextlib import contextmanager
import datetime as dt
import gzip
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import tarfile
import tempfile
import time
import uuid

SHARE = Path('/mnt/Share')
ROOT = SHARE / 'kostya/bronepehota-forum'
DEPLOYMENT = ROOT / 'deployment'
DB_IMAGE = 'mariadb:11.8.9@sha256:d36f18d65a0459510b8b0f643b226a6d299e3206486e2b64ff20754a6d291707'
APP_IMAGE = 'bronepehota-flarum:2.0.2-php8.4.27'
FILES = ('Dockerfile', 'apache.conf', 'php.ini', 'bootstrap.sh', '.dockerignore', '.gitignore', 'compose.yaml',
         'forumctl.py', 'install_private.py', 'configure_sections.py', 'sections.json',
         'check_sections.php', 'apply_theme.py', 'field-manual.less', 'field-manual-footer.html',
         'theme-assets.json', 'publish_forum.py', 'nginx-forum.inc', 'README.md',
         'runtime.py', 'install_services.py', 'bronepehota-forum.service',
         'bronepehota-forum-backup.service', 'bronepehota-forum-backup.timer')
ARCHIVES = ('database.sql.gz', 'app.tar.gz', 'deployment.tar.gz')


def run(args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def compose_args(*args):
    return ['docker', 'compose', '--project-name', 'bronepehota-forum-prep',
            '--project-directory', str(DEPLOYMENT), '--env-file', str(DEPLOYMENT / '.env'),
            '-f', str(DEPLOYMENT / 'compose.yaml'), *args]


def compose(*args, **kwargs):
    return run(compose_args(*args), **kwargs)


def guard_storage():
    if not SHARE.is_mount() or SHARE.resolve() != SHARE:
        raise RuntimeError('Share must be a mounted filesystem, not a fallback directory or symlink.')
    if ROOT.resolve() != ROOT:
        raise RuntimeError('Forum storage must not contain symlinked path components.')
    for name in ('app', 'db', 'deployment', 'backups', 'secrets', 'restore-tests', 'composer-cache'):
        path = ROOT / name
        if path.is_symlink() or (path.exists() and not path.is_dir()):
            raise RuntimeError(f'Unsafe storage directory: {path}')


def write_new(path, text):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as output:
        output.write(text)


def prepare():
    guard_storage()
    if ROOT.exists() and not (ROOT / '.prepared.json').exists():
        if set(p.name for p in ROOT.iterdir()) - {'deployment'}:
            raise RuntimeError('Unrecognized existing data: refusing first-time initialization.')
    ROOT.mkdir(mode=0o700, exist_ok=True)
    if ROOT.stat().st_uid != os.getuid() or ROOT.stat().st_mode & 0o077:
        raise RuntimeError('Forum root must belong to the operator and have mode 0700.')
    for name in ('deployment', 'secrets', 'backups', 'restore-tests', 'composer-cache', 'db', 'app'):
        (ROOT / name).mkdir(mode=0o700 if name != 'app' else 0o755, exist_ok=True)
    source = Path(__file__).resolve().parent
    if source != DEPLOYMENT:
        for name in FILES:
            target = DEPLOYMENT / name
            if target.exists():
                raise RuntimeError(f'Refusing to overwrite deployment file: {target}')
            shutil.copyfile(source / name, target)
    for filename in ('db_password', 'db_root_password'):
        path = ROOT / 'secrets' / filename
        if not path.exists():
            write_new(path, secrets.token_hex(32) + '\n')
        if path.is_symlink() or path.stat().st_mode & 0o077:
            raise RuntimeError('Database secrets must be private regular files.')
    password = (ROOT / 'secrets/db_root_password').read_text().strip()
    client = ROOT / 'secrets/db_root_client.cnf'
    client_text = f'[client]\nuser=root\npassword={password}\nprotocol=socket\n'
    if not client.exists():
        write_new(client, client_text)
    if client.is_symlink() or client.read_text() != client_text or client.stat().st_mode & 0o077:
        raise RuntimeError('Root client configuration does not match the protected password.')
    env = DEPLOYMENT / '.env'
    env_text = f'FORUM_DATA_ROOT={ROOT}\n'
    if not env.exists():
        write_new(env, env_text)
    if env.is_symlink() or env.read_text() != env_text:
        raise RuntimeError('Unexpected storage path in deployment .env.')
    marker = ROOT / '.prepared.json'
    if not marker.exists():
        write_new(marker, json.dumps({'schema': 1, 'root': str(ROOT)}, indent=2) + '\n')
    check()


def check():
    guard_storage()
    marker = ROOT / '.prepared.json'
    if marker.is_symlink() or json.loads(marker.read_text()) != {'schema': 1, 'root': str(ROOT)}:
        raise RuntimeError('Invalid storage marker.')
    for path in (DEPLOYMENT / '.env', ROOT / 'secrets/db_password',
                 ROOT / 'secrets/db_root_password', ROOT / 'secrets/db_root_client.cnf'):
        if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077:
            raise RuntimeError(f'Unsafe private file: {path.name}')
    config = json.loads(compose('--profile', '*', 'config', '--format', 'json',
                                capture_output=True, text=True).stdout)
    services = config['services']
    if services['db'].get('ports') or services['db']['image'] != DB_IMAGE:
        raise RuntimeError('Database must have no published ports and use the pinned image.')
    ports = services['app'].get('ports', [])
    if len(ports) != 1 or ports[0].get('host_ip') != '127.0.0.1' or str(ports[0]['published']) != '8086':
        raise RuntimeError('Preview must bind only to 127.0.0.1:8086.')
    for service in services.values():
        if service.get('restart') != 'no':
            raise RuntimeError('Compose restart must remain no; systemd controls startup after Share is mounted.')
        for volume in service.get('volumes', []):
            source = Path(volume.get('source', ''))
            if volume.get('type') != 'bind' or source.resolve() != source or source.parent != ROOT:
                raise RuntimeError('Every persistent mount must point directly inside Share storage.')
            if volume.get('bind', {}).get('create_host_path') is not False:
                raise RuntimeError('Automatic bind mount directory creation must be disabled.')
    print('Storage and Compose configuration validated; nothing started.')


@contextmanager
def operation_lock():
    import fcntl
    guard_storage()
    fd = os.open(ROOT / '.operation.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError('Another forum backup or restore check is already running.') from exc
        yield
    finally:
        os.close(fd)


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def stream_command(args, output, compressed=False):
    with tempfile.TemporaryFile() as error:
        with subprocess.Popen(args, stdout=subprocess.PIPE, stderr=error) as process:
            try:
                if compressed:
                    with gzip.GzipFile(fileobj=output, mode='wb') as zipped:
                        shutil.copyfileobj(process.stdout, zipped)
                else:
                    shutil.copyfileobj(process.stdout, output)
            except BaseException:
                process.kill()
                process.wait()
                raise
            finally:
                process.stdout.close()
            if process.wait():
                error.seek(0)
                raise RuntimeError('Backup command failed: ' + error.read(2000).decode(errors='replace'))


def sql_command(prefix, query):
    return [*prefix, 'mariadb', '--defaults-extra-file=/run/secrets/db_root_client',
            '--batch', '--skip-column-names', '--execute', query]


def table_checksums(prefix):
    names = run(sql_command(prefix, "SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA='forum' AND TABLE_TYPE='BASE TABLE' ORDER BY TABLE_NAME"),
                capture_output=True, text=True).stdout.splitlines()
    result = {}
    for name in names:
        escaped = name.replace('`', '``')
        output = run(sql_command(prefix, f'CHECKSUM TABLE `forum`.`{escaped}` EXTENDED'),
                     capture_output=True, text=True).stdout.strip().split('\t')
        if len(output) != 2 or output[1] == 'NULL':
            raise RuntimeError('Could not compute database table checksum.')
        result[name] = output[1]
    return result


def verify_backup(path):
    manifest_path = path / 'manifest.json'
    if path.is_symlink() or manifest_path.is_symlink():
        raise RuntimeError('Backup metadata must not be a symlink.')
    manifest = json.loads(manifest_path.read_text())
    if manifest.get('schema') != 1 or set(manifest.get('sha256', {})) != set(ARCHIVES):
        raise RuntimeError('Unsupported or incomplete backup manifest.')
    if manifest.get('database_image') != DB_IMAGE:
        raise RuntimeError('Restore requires the pinned and tested database image.')
    for name in ARCHIVES:
        archive = path / name
        if archive.is_symlink() or not archive.is_file() or sha256(archive) != manifest['sha256'][name]:
            raise RuntimeError(f'Backup checksum mismatch: {name}')
    with gzip.open(path / 'database.sql.gz', 'rb') as source:
        while source.read(1024 * 1024):
            pass
    for name in ('app.tar.gz', 'deployment.tar.gz'):
        with tarfile.open(path / name) as archive:
            for member in archive:
                tarfile.data_filter(member, str(path / 'validation-only'))
    return manifest


def backup():
    check()
    running = compose('ps', '--status', 'running', '--services', capture_output=True, text=True).stdout.splitlines()
    if 'db' not in running:
        raise RuntimeError('Database is not running; refusing to create an incomplete backup.')
    name = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:8]
    pending = ROOT / 'backups' / ('.pending-' + name)
    pending.mkdir(mode=0o700)
    try:
        if 'app' in running:
            compose('stop', 'app')
        prefix = compose_args('exec', '-T', 'db')
        checksums = table_checksums(prefix)
        dump = [*prefix, 'mariadb-dump', '--defaults-extra-file=/run/secrets/db_root_client',
                '--single-transaction', '--quick', '--hex-blob', '--routines', '--events', '--triggers', '--databases', 'forum']
        with (pending / 'database.sql.gz').open('xb') as output:
            stream_command(dump, output, compressed=True)
        with (pending / 'app.tar.gz').open('xb') as output:
            stream_command(['docker', 'run', '--rm', '--network', 'none', '--read-only',
                            '--mount', f'type=bind,src={ROOT / "app"},dst=/data,readonly',
                            '--entrypoint', 'tar', DB_IMAGE, '-czf', '-', '-C', '/data', '.'], output)
        with tarfile.open(pending / 'deployment.tar.gz', 'w:gz') as archive:
            archive.add(DEPLOYMENT, arcname='deployment')
            archive.add(ROOT / 'secrets', arcname='secrets')
        manifest = {'schema': 1, 'created_utc': name, 'database_image': DB_IMAGE,
                    'app_image': APP_IMAGE, 'table_checksums': checksums,
                    'sha256': {filename: sha256(pending / filename) for filename in ARCHIVES}}
        write_new(pending / 'manifest.json', json.dumps(manifest, indent=2, ensure_ascii=False) + '\n')
        verify_backup(pending)
        final = pending.with_name(name)
        pending.rename(final)
        print('Verified backup:', final)
        return final
    finally:
        if 'app' in running:
            compose('start', 'app')


def backup_path(value):
    path = Path(value)
    if not path.is_absolute():
        path = ROOT / 'backups' / path
    if path.is_symlink() or path.resolve().parent != ROOT / 'backups':
        raise RuntimeError('Use a direct child of the private backups directory.')
    return path


def extract_safe(archive_path, destination):
    with tarfile.open(archive_path) as archive:
        for member in archive:
            tarfile.data_filter(member, str(destination))
        archive.extractall(destination, filter='data')


def restore_test(path):
    check()
    manifest = verify_backup(path)
    token = uuid.uuid4().hex[:12]
    destination = ROOT / 'restore-tests' / token
    destination.mkdir(mode=0o700)
    (destination / 'app').mkdir(mode=0o700)
    (destination / 'db').mkdir(mode=0o700)
    extract_safe(path / 'app.tar.gz', destination / 'app')
    extract_safe(path / 'deployment.tar.gz', destination)
    name = 'bronepehota-forum-restore-' + token
    # Never use the restored .env/Compose: they refer to the original database.
    command = ['docker', 'run', '-d', '--name', name, '--network', 'none', '--log-driver', 'none',
               '--mount', f'type=bind,src={destination / "db"},dst=/var/lib/mysql',
               '--mount', f'type=bind,src={destination / "secrets/db_root_password"},dst=/run/secrets/db_root_password,readonly',
               '--mount', f'type=bind,src={destination / "secrets/db_root_client.cnf"},dst=/run/secrets/db_root_client,readonly',
               '-e', 'MARIADB_DATABASE=forum', '-e', 'MARIADB_ROOT_PASSWORD_FILE=/run/secrets/db_root_password', DB_IMAGE]
    created = False
    try:
        run(command, stdout=subprocess.DEVNULL)
        created = True
        deadline = time.monotonic() + 150
        prefix = ['docker', 'exec', name]
        while True:
            result = subprocess.run([*prefix, 'healthcheck.sh', '--connect', '--innodb_initialized'],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if result.returncode == 0:
                break
            if time.monotonic() > deadline:
                raise RuntimeError('Isolated restore database did not become ready.')
            time.sleep(2)
        with gzip.open(path / 'database.sql.gz', 'rb') as source, tempfile.TemporaryFile() as error:
            with subprocess.Popen(['docker', 'exec', '-i', name, 'mariadb',
                                   '--defaults-extra-file=/run/secrets/db_root_client'],
                                  stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=error) as process:
                try:
                    shutil.copyfileobj(source, process.stdin)
                finally:
                    process.stdin.close()
                if process.wait():
                    raise RuntimeError('Database import failed in the isolated restore test.')
        if table_checksums(prefix) != manifest['table_checksums']:
            raise RuntimeError('Restored database checksums differ from the backup.')
        print('Restore test passed; original database was not modified.')
        print('Restored files retained in:', destination)
    finally:
        if created:
            run(['docker', 'rm', '--force', name], stdout=subprocess.DEVNULL)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ('prepare', 'check', 'backup'):
        commands.add_parser(name)
    for name in ('verify', 'restore-test'):
        command = commands.add_parser(name)
        command.add_argument('backup')
    args = parser.parse_args()
    os.umask(0o077)
    if args.command == 'prepare':
        prepare()
    elif args.command == 'check':
        check()
    elif args.command == 'backup':
        with operation_lock():
            backup()
    elif args.command == 'verify':
        guard_storage()
        verify_backup(backup_path(args.backup))
        print('Backup checksums and archive structure verified.')
    else:
        with operation_lock():
            restore_test(backup_path(args.backup))


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, OSError, ValueError, tarfile.TarError, subprocess.CalledProcessError) as exc:
        raise SystemExit(str(exc)) from exc
