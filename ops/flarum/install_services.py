#!/usr/bin/env python3
"""Install only the three named forum units; requires interactive sudo."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import uuid

SOURCE = Path(__file__).resolve().parent
TARGET = Path('/etc/systemd/system')
STATE = SOURCE.parent / 'service-installation.json'
UNITS = ('bronepehota-forum.service', 'bronepehota-forum-backup.service',
         'bronepehota-forum-backup.timer')


def run(*args, **kwargs):
    subprocess.run(args, check=True, **kwargs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['install', 'disable'])
    action = parser.parse_args().action
    if os.geteuid() != 0:
        raise RuntimeError('Run with sudo in your SSH terminal.')
    os.umask(0o077)
    if STATE.is_symlink():
        raise RuntimeError('Unsafe installation state path.')
    if action == 'disable':
        run('systemctl', 'disable', '--now', UNITS[2])
        run('systemctl', 'disable', UNITS[0])
        print('Boot and scheduled backups disabled; running forum preserved.')
        return
    run('runuser', '-u', 'kostya', '--', '/usr/bin/python3', str(SOURCE/'forumctl.py'), 'check')
    run('systemd-analyze', 'verify', *[str(SOURCE/name) for name in UNITS],
        env=os.environ | {'SYSTEMD_UNIT_PATH': '/run/systemd/generator:'})
    previous = json.loads(STATE.read_text()) if STATE.exists() else None
    for name in UNITS:
        destination = TARGET/name
        if destination.is_symlink():
            raise RuntimeError('Refusing symlink unit: '+name)
        if destination.exists():
            digest = hashlib.sha256(destination.read_bytes()).hexdigest()
            if not previous or previous.get('sha256', {}).get(name) != digest:
                raise RuntimeError('Existing unit is not managed by this installer: '+name)
    hashes = {}
    for name in UNITS:
        raw = (SOURCE/name).read_bytes()
        temporary = TARGET/('.'+name+'.'+uuid.uuid4().hex)
        fd = os.open(temporary, os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o644)
        with os.fdopen(fd,'wb') as out:
            out.write(raw)
        os.chmod(temporary,0o644)
        os.replace(temporary,TARGET/name)
        hashes[name] = hashlib.sha256(raw).hexdigest()
    STATE.write_text(json.dumps({'sha256':hashes,'weekly':'Sunday 03:15 Asia/Yekaterinburg'},indent=2)+'\n')
    os.chmod(STATE,0o600)
    run('systemctl','daemon-reload')
    run('systemctl','enable','--now',UNITS[0],UNITS[2])
    run('systemctl','is-enabled',UNITS[0],UNITS[2])
    run('systemctl','is-active',UNITS[0],UNITS[2])
    run('systemctl','list-timers',UNITS[2],'--no-pager')
    print('Forum autostart and weekly backups enabled. No reboot performed.')


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError,OSError,ValueError,subprocess.CalledProcessError) as exc:
        raise SystemExit(str(exc)) from None
