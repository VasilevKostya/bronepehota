"""Create and verify the immutable bundle shared by both publishing targets."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import zipfile

SCHEMA = 1
OPERATIONAL_FILES = {'deployment-status.json', 'deployment-status.json.tmp',
                     'deployment-prepared.json', 'deployment-prepared.json.tmp'}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def safe_name(name):
    require(isinstance(name, str) and bool(name) and '\\' not in name and ':' not in name,
            'Invalid bundle path')
    path = PurePosixPath(name)
    require(path.parts and not path.is_absolute() and '..' not in path.parts and path.as_posix() == name,
            'Unsafe bundle path: ' + name)
    require(not any(part.startswith('.') for part in path.parts) or name == '.nojekyll',
            'Non-public file in bundle: ' + name)
    return name


def validate_metadata(meta, source=None, sha256=None, build=None):
    require(meta.get('schema') == SCHEMA, 'Unsupported bundle schema')
    require(re.fullmatch('[a-f0-9]{40}', meta.get('source_commit', '')), 'Invalid source commit')
    require(re.fullmatch('[a-f0-9]{16}', meta.get('build', '')), 'Invalid build')
    require(re.fullmatch('[a-f0-9]{64}', meta.get('sha256', '')), 'Invalid archive digest')
    require(meta.get('archive') == 'site.zip' and isinstance(meta.get('bytes'), int)
            and meta['bytes'] > 0, 'Invalid archive metadata')
    require(isinstance(meta.get('files'), dict) and meta['files'], 'Missing file inventory')
    for name, value in meta['files'].items():
        safe_name(name)
        require(re.fullmatch('[a-f0-9]{64}', value), 'Invalid file digest')
    for expected, actual, label in [(source, meta['source_commit'], 'source'),
                                    (sha256, meta['sha256'], 'digest'), (build, meta['build'], 'build')]:
        require(expected is None or expected == actual, 'Approved ' + label + ' differs')


def check(folder, *, source=None, sha256=None, build=None, extract=None):
    folder = Path(folder)
    meta = json.loads((folder / 'release.json').read_text(encoding='utf-8'))
    validate_metadata(meta, source, sha256, build)
    archive = folder / meta['archive']
    require(archive.stat().st_size == meta['bytes'] and digest(archive) == meta['sha256'],
            'Bundle archive changed')
    with zipfile.ZipFile(archive) as bundle:
        entries = bundle.infolist()
        require(len(entries) == len(meta['files']) and len({e.filename for e in entries}) == len(entries)
                and {e.filename for e in entries} == set(meta['files']), 'Bundle inventory differs')
        for entry in entries:
            safe_name(entry.filename)
            require(not entry.is_dir() and not stat.S_ISLNK(entry.external_attr >> 16),
                    'Only ordinary files are allowed')
            with bundle.open(entry) as stream:
                require(hashlib.file_digest(stream, 'sha256').hexdigest() == meta['files'][entry.filename],
                        'Bundle file changed: ' + entry.filename)
        metadata = json.loads(bundle.read('build.json'))
        manifest = json.loads(bundle.read('precache.json'))
        require(metadata.get('source_commit') == meta['source_commit'], 'Build source differs')
        require(metadata['build'] == manifest['build'] == meta['build'], 'Build IDs differ')
        require(metadata['version'] == manifest['version'] == meta['version'], 'Versions differ')
        require(metadata['files'] == len(manifest['files']), 'Manifest count differs')
        for name in manifest['files']:
            require(meta['files'].get(name) == manifest['hashes'][name], 'Manifest hash differs: ' + name)
        for name, entry in json.loads(bundle.read('assets/catalog-large.json')).items():
            require(meta['files'].get(name) == entry['sha256'] and entry['fallback'] in manifest['files'],
                    'Optional image or fallback differs: ' + name)
        require(meta['build'] in bundle.read('sw.js').decode('utf-8'), 'Worker build differs')
        if extract is not None:
            target = Path(extract)
            require(not target.exists(), 'Extraction target already exists')
            target.mkdir(parents=True)
            for entry in entries:
                path = target / entry.filename
                path.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(entry) as incoming, path.open('xb') as outgoing:
                    import shutil
                    shutil.copyfileobj(incoming, outgoing)
                path.chmod(0o644)
            for path in [target, *target.rglob('*')]:
                if path.is_dir():
                    path.chmod(0o755)
    return meta


def pack(dist, output, source):
    dist, output = Path(dist), Path(output)
    require(re.fullmatch('[a-f0-9]{40}', source), 'Expected full source commit')
    metadata = json.loads((dist / 'build.json').read_text(encoding='utf-8'))
    require(metadata.get('source_commit') == source, 'Build was not generated from the requested source')
    files = {}
    for path in sorted(dist.rglob('*')):
        require(not path.is_symlink(), 'Symlink in site tree')
        if path.is_file():
            name = safe_name(path.relative_to(dist).as_posix())
            if name in OPERATIONAL_FILES:
                continue
            files[name] = digest(path)
    output.mkdir(parents=True, exist_ok=False)
    with zipfile.ZipFile(output / 'site.zip', 'w', compression=zipfile.ZIP_STORED) as bundle:
        for name in files:
            entry = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            entry.external_attr = (stat.S_IFREG | 0o644) << 16
            bundle.writestr(entry, (dist / name).read_bytes())
    meta = {'schema': SCHEMA, 'source_commit': source, 'build': metadata['build'],
            'version': metadata['version'], 'archive': 'site.zip', 'sha256': digest(output / 'site.zip'),
            'bytes': (output / 'site.zip').stat().st_size, 'files': files}
    (output / 'release.json').write_text(json.dumps(meta, indent=2) + '\n', encoding='utf-8')
    check(output, source=source)
    return meta


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    create = sub.add_parser('pack')
    create.add_argument('--dist', default='dist')
    create.add_argument('--output', required=True)
    create.add_argument('--source', required=True)
    inspect = sub.add_parser('check')
    inspect.add_argument('folder')
    inspect.add_argument('--source', required=True)
    inspect.add_argument('--sha256', required=True)
    inspect.add_argument('--build')
    inspect.add_argument('--extract')
    args = parser.parse_args()
    if args.command == 'pack':
        head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
        require(head == args.source, 'Checkout differs from requested source')
        require(not subprocess.check_output(['git', 'status', '--porcelain']),
                'Only a clean committed checkout can create a publishing candidate')
        meta = pack(args.dist, args.output, args.source)
    else:
        meta = check(args.folder, source=args.source, sha256=args.sha256, build=args.build, extract=args.extract)
    print(json.dumps({k: meta[k] for k in ['source_commit', 'build', 'sha256', 'bytes']}))


if __name__ == '__main__':
    main()
