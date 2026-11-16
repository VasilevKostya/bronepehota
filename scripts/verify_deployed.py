"""Check the deployed release and its offline assets over HTTPS."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import time
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen
from urllib.error import HTTPError


def read(url, *, allow_not_found=False):
    try:
        with urlopen(Request(url, headers={"Cache-Control": "no-cache"}), timeout=20) as response:
            return response.read()
    except HTTPError as error:
        # The error document itself can carry HTTP 404. Its bytes are still
        # checked against the release hash by check(), just like every asset.
        if error.code != 404 or not allow_not_found:
            raise
        with error:
            return error.read()


def verify(base, expected, expected_source=None):
    build = json.loads(read(urljoin(base, "build.json")))
    if build["build"] != expected:
        raise ValueError("The CDN has not served the expected build yet")
    if expected_source is not None and build.get('source_commit') != expected_source:
        raise ValueError('Published source commit differs')
    manifest = json.loads(read(urljoin(base, "precache.json")))
    if manifest["build"] != expected or manifest["version"] != build["version"]:
        raise ValueError("Release metadata differs")
    files = manifest["files"]
    if len(files) != build["files"]:
        raise ValueError("Offline asset count differs")
    hashes=dict(manifest['hashes'])
    optional={}
    if 'assets/catalog-large.json' in files:
        optional=json.loads(read(urljoin(base,'assets/catalog-large.json')))
        for path,entry in optional.items():
            if entry['fallback'] not in files:
                raise ValueError('Missing offline image fallback: '+path)
            hashes[path]=entry['sha256']
        files=files+list(optional)

    def check(path):
        parsed = urlsplit(path)
        if parsed.scheme or parsed.netloc or path.startswith("/") or ".." in parsed.path.split("/"):
            raise ValueError("Unexpected asset path: " + path)
        try:
            data = read(urljoin(base, path), allow_not_found=path == '404.html')
        except Exception as error:
            raise ValueError(f'Published asset unavailable: {path}: {error}') from error
        if hashlib.sha256(data).hexdigest() != hashes[path]:
            raise ValueError("Published asset differs: " + path)
        return path

    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(check, files))
    home = read(base).decode("utf-8")
    if "<title>Правила — Бронепехота</title>" not in home:
        raise ValueError("The site root does not serve the rulebook")
    worker = read(urljoin(base, "sw.js")).decode("utf-8")
    if expected not in worker:
        raise ValueError("Service worker build differs")
    print(f"PASS: public site, service worker and {len(files)} assets ({len(optional)} optional images) match build {expected}; version {build['version']}.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    parser.add_argument("build")
    parser.add_argument("--attempts", type=int, default=6)
    parser.add_argument('--source')
    args = parser.parse_args()
    if args.attempts < 1:
        parser.error("--attempts must be positive")
    base = args.url.rstrip("/") + "/"
    parsed = urlsplit(base)
    if parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost"}):
        parser.error("Use HTTPS for the public site")
    for attempt in range(args.attempts):
        try:
            verify(base, args.build, args.source)
            return
        except Exception as error:
            if attempt + 1 == args.attempts:
                raise
            print(f"Waiting for the published release ({attempt + 1}/{args.attempts}): {error}", flush=True)
            time.sleep(10)


if __name__ == "__main__":
    main()
