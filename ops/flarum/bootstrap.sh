#!/bin/sh
set -eu
umask 0027
if [ -n "$(find /var/www/html -mindepth 1 -maxdepth 1 -print -quit)" ]; then
    printf '%s\n' 'Refusing to overwrite a non-empty app directory.' >&2
    exit 1
fi
export COMPOSER_ALLOW_SUPERUSER=1
export COMPOSER_HOME=/composer-cache/home
export COMPOSER_CACHE_DIR=/composer-cache/cache
composer create-project --no-install --no-interaction --prefer-dist flarum/flarum:2.0.0 /var/www/html
composer require --no-update --no-interaction flarum/core:2.0.2 flarum-lang/russian:2.0.85
composer install --no-dev --prefer-dist --no-interaction --no-progress --optimize-autoloader
composer check-platform-reqs --no-dev
chown -R www-data:www-data /var/www/html
printf '%s\n' 'Flarum files prepared. Web installation has not been performed.'
