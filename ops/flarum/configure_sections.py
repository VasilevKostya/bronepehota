#!/usr/bin/env python3
"""Configure the three authorized sections of the private forum through its API."""

import json
import os
from pathlib import Path
import re
import subprocess
import time
import urllib.error
import urllib.request

import forumctl as ctl


def main():
    os.umask(0o077)
    ctl.check()
    sections = json.loads(Path(__file__).with_name('sections.json').read_text())
    credentials = json.loads((ctl.ROOT / 'secrets/admin_credentials.json').read_text())
    prefix = ctl.compose_args('exec', '-T', 'db')
    token = None

    def request(path, body=None, method=None):
        headers = {'Accept': 'application/json'}
        if body is not None:
            headers['Content-Type'] = 'application/json'
        if token:
            headers['Authorization'] = 'Token ' + token
        req = urllib.request.Request(credentials['url'] + path, headers=headers, method=method,
                                     data=json.dumps(body).encode() if body is not None else None)
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                raw = response.read()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as error:
            # Authentication requests may contain credentials. Never log their body.
            raise RuntimeError(f'Forum API returned HTTP {error.code} at {path}.') from None

    with ctl.operation_lock():
        try:
            auth = request('/api/token', {'identification': credentials['username'],
                                         'password': credentials['password'], 'remember': False})
            token = auth['token']
            tags = request('/api/tags')['data']
            slugs = {tag['attributes']['slug'] for tag in tags}
            planned = {section['slug'] for section in sections}
            if slugs - (planned | {'general'}) or {'general', 'rules-questions'} <= slugs:
                raise RuntimeError('Unexpected existing tags; refusing to reorder or replace them.')
            previous = ctl.backup()
            print('Pre-sections backup:', previous, flush=True)
            deadline = time.monotonic() + 30
            while True:
                try:
                    request('/api/tags')
                    break
                except (ConnectionError, TimeoutError, urllib.error.URLError):
                    if time.monotonic() >= deadline:
                        raise RuntimeError('Forum did not become ready after its backup.') from None
                    time.sleep(0.5)
            by_slug = {tag['attributes']['slug']: tag for tag in tags}
            fallback = by_slug.get('general') or by_slug.get('rules-questions')
            color = fallback['attributes'].get('color') if fallback else '#888'
            ids = {}
            for section in sections:
                current = by_slug.get(section['slug'])
                if section['slug'] == 'rules-questions' and current is None:
                    current = by_slug.get('general')
                attributes = dict(section, isPrimary=True, isHidden=False)
                if current:
                    data = {'type': 'tags', 'id': current['id'], 'attributes': attributes}
                    tag = request('/api/tags/' + current['id'], {'data': data}, 'PATCH')['data']
                else:
                    attributes['color'] = color
                    tag = request('/api/tags', {'data': {'type': 'tags', 'attributes': attributes}})['data']
                ids[section['slug']] = tag['id']
            request('/api/tags/order', {'order': [{'id': ids[s['slug']]} for s in sections]})

            # A restricted tag does not inherit global discussion permissions.
            rows = ctl.run(ctl.sql_command(prefix, 'SELECT group_id,permission FROM forum.group_permission'),
                           capture_output=True, text=True).stdout.splitlines()
            permissions = {}
            for row in rows:
                group, permission = row.split('\t', 1)
                if permission in ('viewForum', 'startDiscussion') or permission.startswith('discussion.'):
                    permissions.setdefault(permission, set()).add(int(group))
            permissions['startDiscussion'] = {4}
            permissions['discussion.startWithoutApproval'] = {4}
            for permission, groups in sorted(permissions.items()):
                request('/api/permission', {'permission': f'tag{ids["announcements"]}.{permission}',
                                            'groupIds': sorted(groups)})
            request('/api/tags/' + ids['announcements'], {'data': {
                'type': 'tags', 'id': ids['announcements'], 'attributes': {'isRestricted': True}}}, 'PATCH')
            for slug in ('rules-questions', 'suggestions'):
                request('/api/tags/' + ids[slug], {'data': {
                    'type': 'tags', 'id': ids[slug], 'attributes': {'isRestricted': False}}}, 'PATCH')
            settings = ctl.run(ctl.sql_command(prefix,
                "SELECT `key`,`value` FROM forum.settings WHERE `key` IN ('allow_sign_up','mail_driver') ORDER BY `key`"),
                capture_output=True, text=True).stdout
            if 'allow_sign_up\t0' not in settings or 'mail_driver\tnull' not in settings:
                raise RuntimeError('Private mode unexpectedly changed.')
            print('Configured section IDs:', json.dumps(ids), flush=True)
            print('Mail and sign-up remain disabled. Public configuration was not changed.', flush=True)
        finally:
            if token:
                if not re.fullmatch('[A-Za-z0-9_-]+', token):
                    raise RuntimeError('Unexpected session token format.')
                query = "DELETE FROM forum.access_tokens WHERE token='" + token + "';"
                result = subprocess.run([*prefix, 'mariadb', '--defaults-extra-file=/run/secrets/db_root_client'],
                                        input=query, text=True, capture_output=True)
                if result.returncode:
                    raise RuntimeError('Temporary API session cleanup failed.')
                print('Temporary configuration session revoked.', flush=True)


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, OSError, ValueError, subprocess.CalledProcessError) as exc:
        raise SystemExit(str(exc)) from exc
