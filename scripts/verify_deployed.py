"""Check the deployed release and its offline assets over HTTPS."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import time
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen


def read(url):
    with urlopen(Request(url, headers={"Cache-Control": "no-cache"}), timeout=20) as response:
        return response.read()


def verify(base, expected):
    build = json.loads(read(urljoin(base, "build.json")))
    if build["build"] != expected:
        raise ValueError("The CDN has not served the expected build yet")
    manifest = json.loads(read(urljoin(base, "precache.json")))
    if manifest["build"] != expected or manifest["version"] != build["version"]:
        raise ValueError("Release metadata differs")
    files = manifest["files"]
    if len(files) != build["files"]:
        raise ValueError("Offline asset count differs")

    def check(path):
        parsed = urlsplit(path)
        if parsed.scheme or parsed.netloc or path.startswith("/") or ".." in parsed.path.split("/"):
            raise ValueError("Unexpected asset path: " + path)
        data = read(urljoin(base, path))
        if hashlib.sha256(data).hexdigest() != manifest["hashes"][path]:
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
    print(f"PASS: public site, service worker and {len(files)} assets match build {expected}; version {build['version']}.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    parser.add_argument("build")
    parser.add_argument("--attempts", type=int, default=6)
    args = parser.parse_args()
    if args.attempts < 1:
        parser.error("--attempts must be positive")
    base = args.url.rstrip("/") + "/"
    parsed = urlsplit(base)
    if parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost"}):
        parser.error("Use HTTPS for the public site")
    for attempt in range(args.attempts):
        try:
            verify(base, args.build)
            return
        except Exception as error:
            if attempt + 1 == args.attempts:
                raise
            print(f"Waiting for the published release ({attempt + 1}/{args.attempts}): {error}", flush=True)
            time.sleep(10)


if __name__ == "__main__":
    main()
