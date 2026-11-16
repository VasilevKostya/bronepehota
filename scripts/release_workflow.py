"""GitHub-side validation and publication of an already tested common bundle."""
import argparse
import json
import os
from pathlib import Path
import re
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from release_bundle import check, require
from release_main import MAIN, PAGES, REPOSITORY, release_tag
from verify_deployed import read, verify

API = 'https://api.github.com/repos/' + REPOSITORY


def api(path, method='GET', data=None, *, upload=None):
    url = path if path.startswith('https://uploads.github.com/') else API + path
    headers = {'Accept': 'application/vnd.github+json', 'User-Agent': 'bronepehota-release',
               'Authorization': 'Bearer ' + os.environ['GITHUB_TOKEN']}
    if upload is not None:
        headers['Content-Type'] = 'application/octet-stream'
        body = Path(upload).read_bytes()
    else:
        headers['Content-Type'] = 'application/json'
        body = None if data is None else json.dumps(data).encode()
    with urlopen(Request(url, data=body, headers=headers, method=method), timeout=120) as response:
        return json.load(response)


def validate_run(run_id, source):
    require(re.fullmatch('[0-9]+', str(run_id)) and re.fullmatch('[a-f0-9]{40}', source),
            'Invalid CI run or source SHA')
    run = api('/actions/runs/' + str(run_id))
    workflow = api('/actions/workflows/ci.yml')
    require(run['event'] in ['push', 'workflow_dispatch'] and run['head_branch'] == 'main'
            and run['head_sha'] == source and run['workflow_id'] == workflow['id']
            and run['status'] == 'completed' and run['conclusion'] == 'success'
            and run['head_repository']['full_name'] == REPOSITORY,
            'Candidate must come from a successful main CI run in this repository')
    comparison = api('/compare/' + source + '...main')
    require(comparison['status'] in ['ahead', 'identical'], 'Source is no longer part of main')


def summary(folder):
    metadata = json.loads((Path(folder) / 'release.json').read_text())
    source, build, sha = metadata['source_commit'], metadata['build'], metadata['sha256']
    text = ('## Candidate prepared — publication has not started\n\n'
            f'- Source: `{source}`\n- Build: `{build}`\n- Bundle SHA-256: `{sha}`\n'
            f'- CI run: `{os.environ["GITHUB_RUN_ID"]}`\n\n'
            'After the owner confirms this exact candidate, start this one-shot SSH command '
            'and then run **Publish approved build** with the same run ID, source and digest:\n\n'
            '```sh\npython3 /mnt/Share/kostya/bronepehota/tools/release_main.py apply '
            f'--source {source} --build {build} --sha256 {sha} --confirm --wait-seconds 1200\n```\n')
    with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as stream:
        stream.write(text)


def publish(folder, source, sha, run_id):
    require(os.environ.get('GITHUB_ACTOR', '').lower() == 'vasilevkostya', 'Only the owner may approve publication')
    metadata = check(folder, source=source, sha256=sha)
    tag = release_tag(source, metadata['build'])
    approval = {'source_commit': source, 'build': metadata['build'], 'sha256': sha,
                'actor': os.environ['GITHUB_ACTOR'], 'candidate_run': str(run_id),
                'publish_run': os.environ['GITHUB_RUN_ID']}
    approval_file = Path(folder) / 'approval.json'
    approval_file.write_text(json.dumps(approval, indent=2) + '\n', encoding='utf-8')
    try:
        release = api('/releases/tags/' + tag)
    except HTTPError as error:
        if error.code != 404:
            raise
        error.close()
        release = api('/releases', 'POST', {'tag_name': tag, 'target_commitish': source,
                      'name': 'Common site build ' + metadata['build'], 'draft': True,
                      'prerelease': False, 'make_latest': 'false',
                      'body': f'Owner-approved candidate. Source: {source}\nBuild: {metadata["build"]}\nSHA-256: {sha}\nCI: {run_id}'})
    require(release['target_commitish'] == source, 'Existing tag belongs to another source')
    if release['draft']:
        existing = {asset['name'] for asset in release['assets']}
        for name in ['site.zip', 'release.json', 'approval.json']:
            require(name not in existing, 'An interrupted draft needs inspection before retrying')
            api(release['upload_url'].split('{')[0] + '?name=' + name, 'POST', upload=Path(folder) / name)
        api('/releases/' + str(release['id']), 'PATCH', {'draft': False, 'make_latest': 'false'})
    else:
        from release_main import approved_release
        approved_release(source, metadata['build'], sha)
    print('Approved release published: ' + tag, flush=True)


def wait_for_main(folder, source, sha, seconds):
    metadata = check(folder, source=source, sha256=sha)
    deadline = time.monotonic() + seconds
    while True:
        try:
            live = json.loads(read(MAIN + 'deployment-status.json'))
            if (live.get('state') == 'verified' and live.get('build') == metadata['build']
                    and live.get('source_commit') == source and live.get('sha256') == sha):
                break
        except (OSError, ValueError):
            pass
        require(time.monotonic() < deadline,
                'Main server did not confirm the common release. Publication is incomplete; inspect the one-shot SSH process and use the recorded rollback.')
        time.sleep(10)
    verify(MAIN, metadata['build'], source)
    verify(PAGES, metadata['build'], source)
    with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as stream:
        stream.write(f'## Both sites verified\n\nSource: `{source}`\n\nBuild: `{metadata["build"]}`\n\nSHA-256: `{sha}`\n')


def require_server_ready(folder, source, sha, state=None):
    metadata = check(folder, source=source, sha256=sha)
    ready = json.loads(read(MAIN + 'deployment-prepared.json'))
    now = time.time()
    phase_matches = ready.get('state') in ['waiting', 'prepared'] if state is None else ready.get('state') == state
    require(phase_matches and ready.get('source_commit') == source
            and ready.get('build') == metadata['build'] and ready.get('sha256') == sha
            and 0 <= now - ready.get('heartbeat_at', 0) <= 90
            and ready.get('expires_at', 0) >= now + 180,
            'Start the confirmed one-shot SSH command for this exact candidate before publishing')


def wait_server_prepared(folder, source, sha, seconds=600):
    deadline = time.monotonic() + seconds
    while True:
        try:
            require_server_ready(folder, source, sha, 'prepared')
            return
        except (OSError, ValueError):
            require(time.monotonic() < deadline, 'Server did not prepare the verified backup and candidate; Pages was not changed')
            time.sleep(10)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['validate-run', 'summary', 'publish', 'wait', 'restore-download', 'require-server-ready', 'wait-server-prepared'])
    parser.add_argument('--folder', default='candidate')
    parser.add_argument('--source')
    parser.add_argument('--sha256')
    parser.add_argument('--run-id')
    parser.add_argument('--tag')
    parser.add_argument('--seconds', type=int, default=900)
    args = parser.parse_args()
    if args.command == 'validate-run':
        validate_run(args.run_id, args.source)
    elif args.command == 'summary':
        summary(args.folder)
    elif args.command == 'publish':
        publish(args.folder, args.source, args.sha256, args.run_id)
    elif args.command == 'restore-download':
        require(re.fullmatch('site-' + args.source + '-[a-f0-9]{16}', args.tag or ''),
                'Rollback tag must belong to the approved source')
        from release_main import approved_release, download
        _, assets, metadata = approved_release(args.source, args.tag[-16:], args.sha256)
        download(assets, metadata, Path(args.folder))
    elif args.command == 'require-server-ready':
        require_server_ready(args.folder, args.source, args.sha256)
    elif args.command == 'wait-server-prepared':
        wait_server_prepared(args.folder, args.source, args.sha256)
    else:
        require(0 < args.seconds <= 1200, 'Invalid publication deadline')
        wait_for_main(args.folder, args.source, args.sha256, args.seconds)


if __name__ == '__main__':
    main()
