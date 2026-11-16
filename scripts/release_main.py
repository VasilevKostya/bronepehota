"""One-shot application of an explicitly approved common GitHub release.

No timer, daemon, inbound webhook or GitHub-held SSH key is needed.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import deploy_main
from release_bundle import check, require, validate_metadata
from verify_deployed import verify, read

REPOSITORY = 'VasilevKostya/bronepehota'
API = 'https://api.github.com/repos/' + REPOSITORY
PAGES = 'https://vasilevkostya.github.io/bronepehota/'
MAIN = 'https://bronepehota.leonet.site/'


def get_json(url):
    with urlopen(Request(url, headers={'User-Agent': 'bronepehota-release',
                                      'Accept': 'application/vnd.github+json'}), timeout=30) as response:
        return json.load(response)


def release_tag(source, build):
    require(re.fullmatch('[a-f0-9]{40}', source) and re.fullmatch('[a-f0-9]{16}', build),
            'Expected full source SHA and build ID')
    return 'site-' + source + '-' + build


def approved_release(source, build, sha256):
    tag = release_tag(source, build)
    release = get_json(API + '/releases/tags/' + tag)
    require(not release['draft'] and not release['prerelease']
            and release['target_commitish'] == source, 'Release is not approved for this source')
    assets = {asset['name']: asset for asset in release['assets']}
    require({'site.zip', 'release.json', 'approval.json'} <= assets.keys(), 'Incomplete release')
    prefix = 'https://github.com/' + REPOSITORY + '/releases/download/' + tag + '/'
    for name in ['site.zip', 'release.json', 'approval.json']:
        require(assets[name]['browser_download_url'] == prefix + name, 'Unexpected release asset URL')
    metadata = get_json(assets['release.json']['browser_download_url'])
    validate_metadata(metadata, source, sha256, build)
    approval = get_json(assets['approval.json']['browser_download_url'])
    require(approval.get('source_commit') == source and approval.get('sha256') == sha256
            and approval.get('build') == build and approval.get('actor', '').lower() == 'vasilevkostya',
            'Approval does not match the candidate or owner')
    return release, assets, metadata


def download(assets, metadata, folder):
    folder.mkdir(parents=True, exist_ok=True, mode=0o750)
    archive = folder / 'site.zip'
    if not archive.exists():
        temporary = folder / 'site.zip.download'
        with urlopen(assets['site.zip']['browser_download_url'], timeout=60) as incoming, temporary.open('wb') as outgoing:
            received = 0
            while chunk := incoming.read(1024 * 1024):
                received += len(chunk)
                require(received <= metadata['bytes'], 'Archive is larger than approved')
                outgoing.write(chunk)
        temporary.replace(archive)
    (folder / 'release.json').write_text(json.dumps(metadata, indent=2) + '\n', encoding='utf-8')
    return check(folder, source=metadata['source_commit'], sha256=metadata['sha256'], build=metadata['build'])


def announce_ready(source, build, sha256, deadline, state='waiting'):
    metadata = {'state': state, 'source_commit': source, 'build': build, 'sha256': sha256,
                'heartbeat_at': time.time(), 'expires_at': time.time() + max(0, deadline - time.monotonic())}
    path = deploy_main.LIVE / 'deployment-prepared.json.tmp'
    path.write_text(json.dumps(metadata) + '\n', encoding='utf-8')
    path.chmod(0o644)
    path.replace(deploy_main.LIVE / 'deployment-prepared.json')


def run_deployer(operation, metadata, folder):
    command = [sys.executable, str(Path(__file__).with_name('deploy_main.py')), operation, metadata['build']]
    if operation == 'prepare':
        previous = json.loads((deploy_main.LIVE / 'build.json').read_text())['build']
        command += ['--previous', previous, '--archive', str(folder / 'site.zip'),
                    '--source-commit', metadata['source_commit'], '--full']
    subprocess.run(command, check=True)


def wait_for_pages(metadata, seconds=900):
    deadline = time.monotonic() + seconds
    while True:
        announce_ready(metadata['source_commit'], metadata['build'], metadata['sha256'], deadline, 'prepared')
        try:
            current = json.loads(read(PAGES + 'build.json'))
            if current.get('build') == metadata['build'] and current.get('source_commit') == metadata['source_commit']:
                return
        except (OSError, ValueError):
            pass
        require(time.monotonic() < deadline, 'Pages did not publish the prepared candidate; main site was not changed')
        time.sleep(10)


def apply(metadata, folder, rollback=False):
    source, build = metadata['source_commit'], metadata['build']
    subprocess.run(['git', 'fetch', 'origin', 'main'], cwd=deploy_main.PROJECT, check=True)
    deploy_main.git('merge-base', '--is-ancestor', source, 'origin/main')
    restore_from = None
    if rollback:
        current_build = json.loads((deploy_main.LIVE / 'build.json').read_text())['build']
        if current_build != build:
            current_state = json.loads((deploy_main.STORAGE / 'deployments' / current_build / 'state.json').read_text())
            require(current_state.get('old') == build and current_state.get('previous_source') == source,
                    'Rollback must match the immediately preceding common release')
            deploy_main.check_source(current_state['source_commit'])
            require(deploy_main.inventory(Path(current_state['restored'])) == current_state['previous_files'],
                    'Rollback backup changed')
            restore_from = current_build
    state_path = deploy_main.STORAGE / 'deployments' / build / 'state.json'
    if not state_path.exists():
        run_deployer('prepare', metadata, folder)
    state = json.loads(state_path.read_text())
    require(state.get('source_commit') == source and state.get('archive_sha256') == metadata['sha256'],
            'Existing operation belongs to a different candidate')
    require(state['phase'] in ['prepared', 'published', 'verified'], 'Previous operation was rolled back')
    # Advertise full preparation, including the tested backup, before Pages changes.
    wait_for_pages(metadata)
    verify(PAGES, build, source)
    if restore_from is not None:
        run_deployer('rollback', {'build': restore_from}, folder)
    elif state['phase'] == 'prepared':
        # Check again immediately before the atomic switch; removed approval is a stop signal.
        approved_release(source, build, metadata['sha256'])
        run_deployer('publish', metadata, folder)
    else:
        require(state['phase'] in ['published', 'verified'], 'Previous operation was rolled back')
    try:
        verify(MAIN, build, source)
        verify(PAGES, build, source)
        if json.loads(state_path.read_text())['phase'] == 'published':
            run_deployer('finalize', metadata, folder)
    except Exception:
        if json.loads(state_path.read_text())['phase'] == 'published':
            run_deployer('rollback', metadata, folder)
        raise
    # This acknowledgement is written only after source sync, verification and
    # finalization. It is operational metadata, never a bundled/offline asset.
    status = {'state': 'verified', 'source_commit': source, 'build': build, 'sha256': metadata['sha256']}
    temporary = deploy_main.LIVE / 'deployment-status.json.tmp'
    temporary.write_text(json.dumps(status) + '\n', encoding='utf-8')
    temporary.chmod(0o644)
    temporary.replace(deploy_main.LIVE / 'deployment-status.json')
    print(json.dumps(status), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['status', 'apply'])
    parser.add_argument('--source', required=True)
    parser.add_argument('--build', required=True)
    parser.add_argument('--sha256', required=True)
    parser.add_argument('--confirm', action='store_true')
    parser.add_argument('--rollback', action='store_true')
    parser.add_argument('--wait-seconds', type=int, default=0)
    args = parser.parse_args()
    release_tag(args.source, args.build)
    require(re.fullmatch('[a-f0-9]{64}', args.sha256), 'Expected archive SHA-256')
    require(0 <= args.wait_seconds <= 1800, 'Wait must be between 0 and 1800 seconds')
    require(args.operation == 'status' or args.confirm, 'Applying requires explicit --confirm')
    if args.operation == 'status':
        try:
            approved_release(args.source, args.build, args.sha256)
            print('Approved release is available; nothing was changed.')
        except HTTPError as error:
            if error.code != 404:
                raise
            error.close()
            print('No approved release is available; nothing was changed.')
        return
    # An explicit one-shot process, bounded in time, not a persistent watcher.
    import fcntl
    lock_path = deploy_main.STORAGE / 'releases' / '.publish.lock'
    with lock_path.open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        subprocess.run(['git', 'fetch', 'origin', 'main'], cwd=deploy_main.PROJECT, check=True)
        deploy_main.check_source(deploy_main.git('rev-parse', 'HEAD'))
        deploy_main.git('merge-base', '--is-ancestor', args.source, 'origin/main')
        if not args.rollback:
            deploy_main.git('merge-base', '--is-ancestor', deploy_main.git('rev-parse', 'HEAD'), args.source)
        deadline = time.monotonic() + args.wait_seconds
        try:
            while True:
                announce_ready(args.source, args.build, args.sha256, deadline)
                try:
                    _, assets, metadata = approved_release(args.source, args.build, args.sha256)
                    break
                except HTTPError as error:
                    if error.code != 404 or time.monotonic() >= deadline:
                        raise
                    error.close()
                    time.sleep(min(30, max(0, deadline - time.monotonic())))
            folder = deploy_main.STORAGE / 'releases' / release_tag(args.source, args.build)
            download(assets, metadata, folder)
            apply(metadata, folder, rollback=args.rollback)
        finally:
            readiness = deploy_main.LIVE / 'deployment-prepared.json'
            if readiness.exists():
                data = json.loads(readiness.read_text())
                if data.get('source_commit') == args.source and data.get('sha256') == args.sha256:
                    readiness.unlink()


if __name__ == '__main__':
    main()
