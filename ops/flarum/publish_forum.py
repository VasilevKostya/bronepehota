#!/usr/bin/env python3
"""Stage and activate the approved /forum/ reverse proxy, with rollback."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import subprocess
import sys
import urllib.request
import uuid

import forumctl as ctl

URL = 'https://bronepehota.leonet.site/forum'
NGINX = Path('/mnt/Hosting/kostya/nginx/bronepehota.conf')
SOURCE = Path(__file__).resolve().parent
STATE = ctl.ROOT / 'publication'
BASE_SHA = '6a1aa9331c2da3b1b3669d4c3da8e450b91a1dfdd60d437105b6b7e7931de49b'
SNAPSHOT = ctl.ROOT / 'secrets/publication-before.json'


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def php(code, payload=''):
    return ctl.compose('exec', '-T', '--user', '33:33', 'app', 'php', '-r', code,
                       input=payload, text=True, capture_output=True).stdout


def settings():
    return json.loads(php('''require 'vendor/autoload.php';
    $app=(require 'site.php')->bootApp();
    $s=$app->getContainer()->make(\\Flarum\\Settings\\SettingsRepositoryInterface::class);
    $out=[]; foreach (['mail_driver','allow_sign_up','welcome_title','welcome_message'] as $k) $out[$k]=$s->get($k);
    echo json_encode($out);'''))


def prepare():
    if os.getuid() != pwd.getpwnam('kostya').pw_uid:
        raise RuntimeError('Run prepare as kostya.')
    ctl.check()
    with ctl.operation_lock():
        if STATE.exists() or SNAPSHOT.exists():
            raise RuntimeError('Publication already prepared; inspect existing state.')
        old = NGINX.read_bytes()
        if digest(old) != BASE_SHA:
            raise RuntimeError('Nginx changed; rebase the candidate first.')
        current = settings()
        if current['mail_driver'] != 'null' or current['allow_sign_up'] != '0':
            raise RuntimeError('Unexpected mail or registration state.')
        config = php("echo base64_encode(file_get_contents('config.php'));")
        ctl.write_new(SNAPSHOT, json.dumps({'config': config, 'settings': current}))
        backup = ctl.backup()
        STATE.mkdir(mode=0o700)
        snippet = (SOURCE / 'nginx-forum.inc').read_text()
        anchor = '    location / {\n'
        text = old.decode()
        if text.count(anchor) != 1:
            raise RuntimeError('Unexpected Nginx layout.')
        candidate = text.replace(anchor, '\n'.join('    '+line for line in snippet.splitlines())+'\n\n'+anchor, 1)
        ctl.write_new(STATE / 'nginx.before', text)
        ctl.write_new(STATE / 'nginx.candidate', candidate)
        ctl.write_new(STATE / 'prepared.json', json.dumps({
            'url': URL, 'nginx_before': BASE_SHA, 'nginx_after': digest(candidate.encode()),
            'backup': str(backup), 'status': 'prepared',
        }, indent=2)+'\n')
        print('Prepared:', STATE, '\nBackup:', backup)


def application(public):
    if os.getuid() != pwd.getpwnam('kostya').pw_uid:
        raise RuntimeError('Application operation must run as kostya.')
    ctl.check()
    with ctl.operation_lock():
        saved = json.loads(SNAPSHOT.read_text())
        payload = {'public': public, 'url': URL, **saved}
        php('''$p=json_decode(stream_get_contents(STDIN),true,flags:JSON_THROW_ON_ERROR);
        $old=base64_decode($p['config'],true);
        if ($old===false) throw new RuntimeException('Invalid config snapshot');
        if ($p['public']) {
            $c=require 'config.php';
            if (!in_array($c['url'],['http://127.0.0.1:8086',$p['url']],true)) throw new RuntimeException('Unexpected URL');
            $c['url']=$p['url']; $c['debug']=false;
            $new="<?php\\nreturn ".var_export($c,true).";\\n";
        } else $new=$old;
        file_put_contents('config.php.publication-new',$new,LOCK_EX);
        chmod('config.php.publication-new',0600);
        rename('config.php.publication-new','config.php');
        require 'vendor/autoload.php';
        $app=(require 'site.php')->bootApp();
        $s=$app->getContainer()->make(\\Flarum\\Settings\\SettingsRepositoryInterface::class);
        foreach (['mail_driver','allow_sign_up'] as $key) {
            if ($s->get($key)!==$p['settings'][$key]) throw new RuntimeException('Access settings changed');
        }
        $values=$p['public'] ? ['welcome_title'=>'Форум «Бронепехоты»',
          'welcome_message'=>'Вопросы по правилам, предложения и объявления. Учётные записи создаёт администратор; почта пока отключена.'] :
          array_intersect_key($p['settings'],array_flip(['welcome_title','welcome_message']));
        foreach($values as $key=>$value) $s->set($key,$value);
        ''', json.dumps(payload))
        ctl.compose('exec','-T','--user','33:33','app','php','flarum','cache:clear',
                    stdout=subprocess.DEVNULL)
        import apply_theme
        apply_theme.install_fonts(apply_theme.font_payload())
        # Keep operator tools targeting loopback; config.php controls public URLs.
        print('Application URL:', URL if public else 'http://127.0.0.1:8086')


def replace_nginx(raw):
    temporary = NGINX.with_name('.bronepehota-forum-'+uuid.uuid4().hex)
    fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    with os.fdopen(fd, 'wb') as out:
        out.write(raw)
    os.chown(temporary, 0, 0)
    os.replace(temporary, NGINX)


def as_operator(action):
    subprocess.run(['runuser','-u','kostya','--','/usr/bin/python3',str(SOURCE / 'publish_forum.py'),action],check=True)


def verify():
    for path in ('/', '/tags', '/api/discussions'):
        with urllib.request.urlopen(URL+path, timeout=30) as response:
            if response.status != 200:
                raise RuntimeError('Public forum HTTP check failed.')
            raw = response.read()
        if path == '/':
            html = raw.decode()
            if 'http://127.0.0.1:8086' in html or URL not in html:
                raise RuntimeError('Public base URL mismatch.')
            links = re.findall(r'(?:href|src)="('+re.escape(URL)+r'/assets/[^"<>]+)"',html)
            if len(links) < 2:
                raise RuntimeError('Missing frontend assets.')
            for link in links:
                with urllib.request.urlopen(link.replace('&amp;', '&'),timeout=30) as asset:
                    if asset.status != 200: raise RuntimeError('Frontend asset failed.')
    print('Public HTTPS, tags, discussions and frontend assets: OK')


def activate(rollback=False):
    if os.geteuid() != 0:
        raise RuntimeError('Nginx needs sudo: run this command in your SSH terminal.')
    state = json.loads((STATE / 'prepared.json').read_text())
    before, candidate = (STATE / 'nginx.before').read_bytes(), (STATE / 'nginx.candidate').read_bytes()
    if digest(before) != state['nginx_before'] or digest(candidate) != state['nginx_after']:
        raise RuntimeError('Candidate checksum mismatch.')
    if NGINX.is_symlink() or digest(NGINX.read_bytes()) not in (state['nginx_before'],state['nginx_after']):
        raise RuntimeError('Nginx changed since preparation.')
    if rollback:
        replace_nginx(before)
        subprocess.run(['nginx','-t'],check=True)
        subprocess.run(['systemctl','reload','nginx'],check=True)
        as_operator('application-private')
        print('Rolled back to private loopback forum.')
        return
    try:
        replace_nginx(candidate)
        subprocess.run(['nginx','-t'],check=True)
        as_operator('application-public')
        subprocess.run(['systemctl','reload','nginx'],check=True)
        verify()
    except BaseException:
        replace_nginx(before)
        subprocess.run(['nginx','-t'],check=True)
        subprocess.run(['systemctl','reload','nginx'],check=True)
        as_operator('application-private')
        raise
    print('Published:', URL+'/')


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['prepare','activate','rollback','verify','application-public','application-private'])
    action=parser.parse_args().action
    os.umask(0o077)
    try:
        if action=='prepare': prepare()
        elif action=='activate': activate()
        elif action=='rollback': activate(True)
        elif action=='verify': verify()
        else: application(action=='application-public')
    except (RuntimeError,OSError,ValueError,subprocess.CalledProcessError) as exc:
        raise SystemExit(str(exc)) from None
