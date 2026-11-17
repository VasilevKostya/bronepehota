#!/usr/bin/env python3
"""Install the private loopback forum with disabled mail and sign-up."""

import json
import os
from pathlib import Path
import secrets
import subprocess

import forumctl as ctl


EXTENSIONS = [
    'flarum-approval', 'flarum-bbcode', 'flarum-emoji', 'flarum-lang-english',
    'flarum-flags', 'flarum-likes', 'flarum-lock', 'flarum-markdown',
    'flarum-mentions', 'flarum-statistics', 'flarum-sticky',
    'flarum-subscriptions', 'flarum-suspend', 'flarum-tags', 'flarum-lang-russian',
]


def installed():
    result = subprocess.run(ctl.compose_args(
        'run', '--rm', '--no-deps', '-T', '--entrypoint', 'php', 'app', '-r',
        'exit(file_exists("config.php") ? 20 : 0);'),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if result.returncode not in (0, 20):
        raise RuntimeError('Unable to check installation state.')
    return result.returncode == 20


def logged(command, name):
    path = ctl.ROOT / 'composer-cache' / f'{Path(name).stem}-{secrets.token_hex(4)}.log'
    with path.open('x') as output:
        result = subprocess.run(command, stdout=output, stderr=subprocess.STDOUT)
    if result.returncode:
        raise RuntimeError(f'Private setup step failed; protected server log: {path}')


def main():
    os.umask(0o077)
    ctl.check()
    with ctl.operation_lock():
        if installed():
            raise RuntimeError('Already installed; refusing to reinstall or replace credentials.')
        credentials_path = ctl.ROOT / 'secrets/admin_credentials.json'
        install_path = ctl.ROOT / 'secrets/private_install.json'
        if credentials_path.exists() or install_path.exists():
            raise RuntimeError('Previous private setup artifacts exist; inspect before retrying.')
        ctl.compose('up', '-d', '--wait', 'db')
        previous = ctl.backup()
        print('Pre-install backup:', previous, flush=True)
        logged(ctl.compose_args(
            'run', '--rm', '--no-deps', '-T', '--entrypoint', 'composer',
            '-e', 'COMPOSER_ALLOW_SUPERUSER=1', '-e', 'COMPOSER_HOME=/composer-cache/home',
            '-e', 'COMPOSER_CACHE_DIR=/composer-cache/cache', 'bootstrap', 'require',
            '--update-no-dev', '--prefer-dist', '--no-interaction', '--no-progress',
            '--optimize-autoloader', 'flarum-lang/russian:2.0.85'), 'private-locale-install.log')
        credentials = {
            'url': 'http://127.0.0.1:8086', 'username': 'kostya',
            'email': 'kostya@forum.invalid', 'password': secrets.token_urlsafe(32),
        }
        ctl.write_new(credentials_path, json.dumps(credentials, ensure_ascii=False, indent=2) + '\n')
        configuration = {
            'debug': False, 'baseUrl': credentials['url'],
            'databaseConfiguration': {
                'driver': 'mariadb', 'host': 'db', 'port': 3306,
                'database': 'forum', 'username': 'forum', 'prefix': '',
                'password': (ctl.ROOT / 'secrets/db_password').read_text().strip(),
            },
            'adminUser': {key: credentials[key] for key in ('username', 'password', 'email')},
            'settings': {
                'forum_title': 'Бронепехота', 'forum_description': 'Закрытая установка форума',
                'welcome_title': 'Закрытый форум «Бронепехоты»',
                'welcome_message': 'Доступ через SSH-туннель. Регистрация и отправка писем отключены.',
                'allow_sign_up': '0', 'mail_driver': 'null', 'mail_from': 'noreply@forum.invalid',
                'default_locale': 'ru',
            },
            'extensions': ','.join(EXTENSIONS), 'queue': {'driver': 'sync'},
        }
        ctl.write_new(install_path, json.dumps(configuration, ensure_ascii=False, indent=2) + '\n')
        logged(ctl.compose_args(
            'run', '--rm', '--no-deps', '-T', '--volume', f'{install_path}:/run/forum-install.json:ro',
            '--entrypoint', 'php', 'app', 'flarum', 'install', '--file',
            '/run/forum-install.json', '--no-interaction'), 'private-flarum-install.log')
        ctl.compose('run', '--rm', '--no-deps', '-T', '--entrypoint', 'sh', 'app', '-c',
                    'chown -R www-data:www-data /var/www/html && chmod 640 /var/www/html/config.php')
        ctl.compose('up', '-d', 'app')
        print('Private installation completed. Mail and sign-up are disabled.')
        print('Administrator credentials are stored only in:', credentials_path)


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, OSError, ValueError, subprocess.CalledProcessError) as exc:
        raise SystemExit(str(exc)) from exc
