"""Deploy a verified static release on leonet.site, keeping recovery data in Share.

Run on the server through SSH. This does not pull Git, build files, or reload Nginx.
"""
import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import zipfile

PROJECT = Path('/mnt/Hosting/kostya/bronepehota')
LIVE = PROJECT / 'dist'
STORAGE = Path('/mnt/Share/kostya/bronepehota')
OPERATIONAL_FILES = {'deployment-status.json', 'deployment-status.json.tmp',
                     'deployment-prepared.json', 'deployment-prepared.json.tmp'}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def safe_path(root, name):
    path = root / name
    require(isinstance(name, str) and name and not Path(name).is_absolute()
            and '..' not in Path(name).parts and '\\' not in name
            and path.resolve().is_relative_to(root.resolve()), 'Unsafe path: ' + str(name))
    return path


def inventory(root):
    files = {}
    for path in sorted(root.rglob('*')):
        require(not path.is_symlink(), 'Unexpected symlink: ' + str(path))
        if path.is_file():
            name = path.relative_to(root).as_posix()
            if name not in OPERATIONAL_FILES:
                files[name] = sha(path)
    return files


def verify(root, build, source=None):
    metadata = read_json(root / 'build.json')
    manifest = read_json(root / 'precache.json')
    require(metadata['build'] == manifest['build'] == build, 'Build differs')
    require(source is None or metadata.get('source_commit') == source, 'Source commit differs')
    require(metadata['version'] == manifest['version'], 'Version differs')
    require(metadata['files'] == len(manifest['files']), 'File count differs')
    hashes = {name: manifest['hashes'][name] for name in manifest['files']}
    for name, expected in hashes.items():
        require(sha(safe_path(root, name)) == expected, 'Asset differs: ' + name)
    optional = read_json(root / 'assets/catalog-large.json')
    for name, entry in optional.items():
        require(entry['fallback'] in hashes, 'Fallback missing: ' + name)
        require(sha(safe_path(root, name)) == entry['sha256'], 'Large image differs: ' + name)
    require(build in (root / 'sw.js').read_text(encoding='utf-8'), 'Worker differs')
    print(f'PASS {root}: build {build}, {len(hashes)} required, {len(optional)} optional', flush=True)


def exchange(left, right):
    require(left.parent == right.parent == PROJECT, 'Exchange outside project')
    require(left.is_dir() and right.is_dir() and not left.is_symlink()
            and not right.is_symlink(), 'Exchange requires ordinary directories')
    libc = ctypes.CDLL(None, use_errno=True)
    rename = libc.renameat2
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    if rename(-100, os.fsencode(left), -100, os.fsencode(right), 2):
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))


def save_state(folder, state):
    temp = folder / 'state.json.tmp'
    temp.write_text(json.dumps(state, indent=2) + '\n', encoding='utf-8')
    temp.replace(folder / 'state.json')


def git(*args):
    return subprocess.check_output(['git', *args], cwd=PROJECT, text=True).strip()


def check_source(expected):
    require(git('branch', '--show-current') == 'main', 'Server checkout must use main')
    require(not git('status', '--porcelain'), 'Server checkout has local changes')
    require(git('rev-parse', 'HEAD') == expected, 'Server source changed')


def switch_release(stage, previous_source=None, source=None, rollback=False):
    if source:
        check_source(previous_source)
    exchange(LIVE, stage)
    try:
        if source:
            if rollback:
                git('reset', '--keep', source)
            else:
                git('merge', '--ff-only', source)
            check_source(source)
    except Exception:
        exchange(LIVE, stage)
        if source and git('rev-parse', 'HEAD') == source:
            git('reset', '--keep', previous_source)
        raise


def prepare(archive, old, new, folder, stage, source=None, full=False):
    require(not folder.exists() and not stage.exists(), 'Deployment already exists')
    require(archive.resolve().is_relative_to(STORAGE.resolve()), 'Archive must be in Share')
    verify(LIVE, old)
    previous_source = None
    if source:
        require(re.fullmatch('[a-f0-9]{40}', source), 'Invalid source SHA')
        previous_source = git('rev-parse', 'HEAD')
        check_source(previous_source)
        git('merge-base', '--is-ancestor', previous_source, source)
    before = inventory(LIVE)
    folder.mkdir(parents=True, mode=0o750)
    backup = folder / ('previous-' + old + '.tar')
    with tarfile.open(backup, 'w') as bundle:
        bundle.add(LIVE, arcname='dist')
    backup.chmod(0o640)
    restored = folder / 'restore-check'
    restored.mkdir(mode=0o750)
    with tarfile.open(backup) as bundle:
        bundle.extractall(restored, filter='data')
    restored = restored / 'dist'
    require(inventory(restored) == before, 'Backup restoration differs')
    verify(restored, old)
    # Rehearse the exact atomic exchange on disposable marker directories.
    first, second = PROJECT / ('.exchange-a-' + new), PROJECT / ('.exchange-b-' + new)
    require(not first.exists() and not second.exists(), 'Rehearsal paths already exist')
    first.mkdir(); second.mkdir()
    (first / 'marker').write_text('old'); (second / 'marker').write_text('new')
    exchange(first, second)
    require((first / 'marker').read_text() == 'new', 'Exchange failed')
    exchange(first, second)
    require((first / 'marker').read_text() == 'old', 'Reverse exchange failed')
    for path in (first, second):
        (path / 'marker').unlink(); path.rmdir()
    if full:
        stage.mkdir(mode=0o755)
    else:
        shutil.copytree(LIVE, stage)
    with zipfile.ZipFile(archive) as bundle:
        for entry in bundle.infolist():
            require(not entry.is_dir(), 'Patch must contain files only')
            target = safe_path(stage, entry.filename)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(bundle.read(entry))
            target.chmod(0o644)
    stage.chmod(0o755)
    for directory in stage.rglob('*'):
        if directory.is_dir():
            directory.chmod(0o755)
    verify(stage, new, source)
    require(inventory(LIVE) == before, 'Live files changed during preparation')
    state = {'old': old, 'new': new, 'backup': str(backup), 'backup_sha256': sha(backup),
             'restored': str(restored), 'archive': str(archive), 'archive_sha256': sha(archive),
             'previous_files': before, 'phase': 'prepared',
             'source_commit': source, 'previous_source': previous_source}
    save_state(folder, state)
    print('PASS backup restored and forward/reverse directory exchange rehearsed', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['prepare', 'publish', 'rollback', 'finalize'])
    parser.add_argument('build')
    parser.add_argument('--previous')
    parser.add_argument('--archive', type=Path)
    parser.add_argument('--source-commit')
    parser.add_argument('--full', action='store_true')
    args = parser.parse_args()
    require(re.fullmatch('[a-f0-9]{16}', args.build), 'Invalid build')
    require(PROJECT.resolve() == PROJECT and LIVE.resolve() == LIVE, 'Unexpected project layout')
    require(STORAGE.parent.resolve() == Path('/mnt/Share/kostya'), 'Unexpected Share layout')
    os.umask(0o027)
    folder = STORAGE / 'deployments' / args.build
    stage = PROJECT / ('.deploy-' + args.build)
    if args.operation == 'prepare':
        require(args.previous and re.fullmatch('[a-f0-9]{16}', args.previous), 'Previous build required')
        require(args.archive is not None, 'Archive required')
        prepare(args.archive, args.previous, args.build, folder, stage, args.source_commit, args.full)
        return
    state = read_json(folder / 'state.json')
    require(state['new'] == args.build, 'Deployment state differs')
    if args.operation == 'publish':
        require(state['phase'] == 'prepared', 'Deployment is not prepared')
        require(sha(Path(state['backup'])) == state['backup_sha256'], 'Backup changed')
        require(inventory(LIVE) == state['previous_files'], 'Live site changed since preparation')
        verify(stage, state['new'], state.get('source_commit'))
        switch_release(stage, state.get('previous_source'), state.get('source_commit'))
        try:
            verify(LIVE, state['new'], state.get('source_commit'))
        except Exception:
            switch_release(stage, state.get('source_commit'), state.get('previous_source'), rollback=True)
            raise
        state['phase'] = 'published'
    elif args.operation == 'rollback':
        require(state['phase'] in ['published', 'verified'], 'Deployment is not published')
        require(read_json(LIVE / 'build.json')['build'] == state['new'], 'A different release is live')
        if not stage.exists():
            restored = Path(state['restored'])
            require(inventory(restored) == state['previous_files'], 'Restored backup changed')
            shutil.copytree(restored, stage)
            stage.chmod(0o755)
        require(inventory(stage) == state['previous_files'], 'Previous release changed')
        switch_release(stage, state.get('source_commit'), state.get('previous_source'), rollback=True)
        verify(LIVE, state['old'])
        state['phase'] = 'rolled_back'
    else:
        require(state['phase'] == 'published', 'Deployment is not awaiting verification')
        verify(LIVE, state['new'], state.get('source_commit'))
        if state.get('source_commit'):
            check_source(state['source_commit'])
        require(inventory(stage) == state['previous_files'], 'Previous release changed')
        # Keep recovery files on Share, never as a backup inside the web hosting tree.
        require(stage.parent == PROJECT and stage.name == '.deploy-' + args.build
                and not stage.is_symlink(), 'Unsafe cleanup target')
        destination = folder / 'previous-dist'
        require(not destination.exists(), 'Previous directory already saved')
        shutil.move(str(stage), str(destination))
        require(inventory(destination) == state['previous_files'], 'Moved backup differs')
        state['restored'] = str(destination)
        state['phase'] = 'verified'
    save_state(folder, state)
    print(json.dumps({'phase': state['phase'], 'build': read_json(LIVE / 'build.json')['build']}), flush=True)


if __name__ == '__main__':
    main()
