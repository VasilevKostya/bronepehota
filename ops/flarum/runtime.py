#!/usr/bin/env python3
"""Start/stop the installed forum after checking its Share storage."""
import argparse
import subprocess
import time
import urllib.error
import urllib.request

import forumctl as ctl


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['start', 'stop'])
    action = parser.parse_args().action
    ctl.check()
    with ctl.operation_lock():
        if action == 'stop':
            ctl.compose('stop', '--timeout', '60', 'app', 'db')
            return
        ctl.compose('up', '-d', '--wait', '--wait-timeout', '150', 'db')
        ctl.compose('up', '-d', '--no-deps', 'app')
        deadline = time.monotonic() + 60
        while True:
            try:
                with urllib.request.urlopen('http://127.0.0.1:8086/', timeout=5) as response:
                    if response.status == 200:
                        print('Forum ready on loopback; public proxy remains unchanged.')
                        return
            except (OSError, urllib.error.URLError):
                pass
            if time.monotonic() >= deadline:
                raise RuntimeError('Forum did not become ready after startup.')
            time.sleep(1)


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, OSError, subprocess.CalledProcessError) as exc:
        raise SystemExit(str(exc)) from None
