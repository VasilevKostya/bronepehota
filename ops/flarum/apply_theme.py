#!/usr/bin/env python3
"""Apply or roll back the private forum theme without replacing Flarum files."""

import argparse
import base64
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
import urllib.error
import urllib.request
import uuid

import forumctl as ctl

FIELDS = ('custom_less', 'custom_footer', 'theme_primary_color', 'theme_secondary_color',
          'theme_colored_header', 'color_scheme')
SITE_SOURCE = Path('/mnt/Hosting/kostya/bronepehota')
SOURCE = Path(__file__).resolve().parent


def query_json(query):
    result = ctl.run([*ctl.compose_args('exec', '-T', 'db'), 'mariadb',
                      '--defaults-extra-file=/run/secrets/db_root_client', '--batch', '--raw',
                      '--skip-column-names', '--execute', query], capture_output=True, text=True)
    return json.loads(result.stdout)


def private_mode():
    settings = query_json("SELECT JSON_OBJECTAGG(`key`,`value`) FROM forum.settings WHERE `key` IN ('mail_driver','allow_sign_up')")
    if settings != {'mail_driver': 'null', 'allow_sign_up': '0'}:
        raise RuntimeError('Refusing to alter a forum outside the authorized private mode.')


def font_payload():
    result = {}
    for relative, entry in json.loads((SOURCE / 'theme-assets.json').read_text()).items():
        path = (SITE_SOURCE / relative).resolve()
        if not path.is_relative_to(SITE_SOURCE) or not path.is_file():
            raise RuntimeError('Unexpected source asset path.')
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != entry['sha256']:
            raise RuntimeError('Source font/license differs from the repository manifest.')
        result[entry['destination']] = base64.b64encode(raw).decode()
    return result


def install_fonts(payload):
    code = r'''
    $files = json_decode(stream_get_contents(STDIN), true, flags: JSON_THROW_ON_ERROR);
    $root = '/var/www/html/public/assets/field-manual';
    if (is_link($root)) throw new RuntimeException('Unsafe asset root');
    foreach ($files as $relative => $encoded) {
        if (!preg_match('~^(fonts|licenses)/[A-Za-z0-9_.-]+$~', $relative)) throw new RuntimeException('Unsafe asset name');
        $path = $root.'/'.$relative;
        if (is_link(dirname($path)) || is_link($path)) throw new RuntimeException('Unsafe asset destination');
        if (!is_dir(dirname($path))) mkdir(dirname($path), 0755, true);
        $raw = base64_decode($encoded, true);
        if ($raw === false) throw new RuntimeException('Invalid asset encoding');
        if (!is_file($path) || hash_file('sha256', $path) !== hash('sha256', $raw)) {
            file_put_contents($path.'.new', $raw, LOCK_EX);
            chmod($path.'.new', 0644);
            rename($path.'.new', $path);
        }
        if (hash_file('sha256', $path) !== hash('sha256', $raw)) throw new RuntimeException('Asset hash mismatch');
    }
    echo count($files).' local fonts/licenses verified.'.PHP_EOL;
    '''
    ctl.compose('exec', '-T', '--user', '33:33', 'app', 'php', '-r', code,
                input=json.dumps(payload), text=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rollback', metavar='SNAPSHOT_NAME')
    args = parser.parse_args()
    os.umask(0o077)
    ctl.check()
    with ctl.operation_lock():
        private_mode()
        fonts = font_payload()
        css = (SOURCE / 'field-manual.less').read_text()
        ctl.compose('exec', '-T', '--user', '33:33', 'app', 'php', '-r',
                    'require "vendor/autoload.php"; $parser=new Less_Parser; $parser->parse(stream_get_contents(STDIN)); $parser->getCss(); echo "LESS syntax OK\n";',
                    input=css, text=True)
        before = query_json('SELECT JSON_OBJECTAGG(`key`,`value`) FROM forum.settings WHERE `key` IN (' + ','.join("'"+field+"'" for field in FIELDS) + ')')
        before = {field: before.get(field, '') for field in FIELDS}
        colors = query_json("SELECT JSON_ARRAYAGG(JSON_OBJECT('id',id,'color',color)) FROM forum.tags WHERE slug IN ('rules-questions','suggestions','announcements')")
        token = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:8]
        snapshot = ctl.ROOT / 'secrets' / ('theme-before-' + token + '.json')
        ctl.write_new(snapshot, json.dumps({'settings': before, 'colors': colors}, ensure_ascii=False, indent=2) + '\n')
        if args.rollback:
            path = ctl.ROOT / 'secrets' / args.rollback
            if path.resolve().parent != ctl.ROOT / 'secrets' or path.is_symlink() or not path.name.startswith('theme-before-'):
                raise RuntimeError('Rollback must use a protected theme snapshot filename.')
            saved = json.loads(path.read_text())
            settings, colors = saved['settings'], saved['colors']
            if set(settings) != set(FIELDS):
                raise RuntimeError('Invalid theme rollback settings.')
        else:
            settings = {'custom_less': css, 'custom_footer': (SOURCE / 'field-manual-footer.html').read_text(),
                        'theme_primary_color': '#30483b', 'theme_secondary_color': '#5d713e',
                        'theme_colored_header': '1', 'color_scheme': 'light'}
            colors = [dict(entry, color='#5d713e') for entry in colors]
        previous = ctl.backup()
        print('Pre-theme backup:', previous, flush=True)
        credentials = json.loads((ctl.ROOT / 'secrets/admin_credentials.json').read_text())
        auth_token = None

        def request(path, body=None, method=None):
            headers = {'Accept': 'application/json'}
            if body is not None:
                headers['Content-Type'] = 'application/json'
            if auth_token:
                headers['Authorization'] = 'Token ' + auth_token
            req = urllib.request.Request(credentials['url'] + path, headers=headers, method=method,
                                         data=json.dumps(body).encode() if body is not None else None)
            with urllib.request.urlopen(req, timeout=60) as response:
                raw = response.read()
                return json.loads(raw) if raw and 'json' in response.headers.get('Content-Type', '') else None

        deadline = time.monotonic() + 40
        while True:
            try:
                request('/api/tags')
                break
            except (ConnectionError, TimeoutError, urllib.error.URLError):
                if time.monotonic() > deadline:
                    raise RuntimeError('Forum did not become ready after backup.') from None
                time.sleep(.5)
        try:
            auth_token = request('/api/token', {'identification': credentials['username'],
                                               'password': credentials['password'], 'remember': False})['token']
            request('/api/settings', settings)
            for tag in colors:
                request('/api/tags/' + str(tag['id']), {'data': {'type': 'tags', 'id': str(tag['id']),
                         'attributes': {'color': tag['color']}}}, 'PATCH')
            ctl.compose('exec', '-T', '--user', '33:33', 'app', 'php', 'flarum', 'cache:clear')
            install_fonts(fonts)
            private_mode()
            print('Theme applied to the private forum only.', flush=True)
            print('Rollback snapshot:', snapshot.name, flush=True)
        finally:
            if auth_token:
                if not re.fullmatch('[A-Za-z0-9_-]+', auth_token):
                    raise RuntimeError('Unexpected temporary session format.')
                result = subprocess.run([*ctl.compose_args('exec', '-T', 'db'), 'mariadb',
                                         '--defaults-extra-file=/run/secrets/db_root_client'],
                                        input="DELETE FROM forum.access_tokens WHERE token='"+auth_token+"';", text=True, capture_output=True)
                if result.returncode:
                    raise RuntimeError('Temporary theme session cleanup failed.')


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, OSError, ValueError, subprocess.CalledProcessError) as exc:
        raise SystemExit(str(exc)) from exc
