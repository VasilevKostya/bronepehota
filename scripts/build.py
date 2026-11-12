"""Build a self-contained static site and PDF from the same reviewed content."""
from pathlib import Path
import argparse, json, html, shutil, hashlib, re
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]; DIST=ROOT/'dist'
RELEASE=json.loads((ROOT/'content/release.json').read_text(encoding='utf-8'))
CHAPTERS=[json.loads(p.read_text(encoding='utf-8')) for p in sorted((ROOT/'content/rules').glob('*.json'))]
EDITION=f"{RELEASE['edition']} {RELEASE['version']}"
PDF='bronepehota-ural-'+RELEASE['version']+'.pdf'
FORUM='https://github.com/VasilevKostya/bronepehota/discussions'
FORUM_ATTRS=f'href="{FORUM}" target="_blank" rel="noopener noreferrer" aria-label="Форум на GitHub — нужна сеть, откроется в новой вкладке" title="Форум на GitHub · нужен интернет · новая вкладка"'
def esc(x): return html.escape(str(x),quote=True)
def icon(name):return f'<span class="icon" style="--icon:url(icons/{name}.svg)" aria-hidden="true"></span>'
def url(ch):return 'pravila-'+ch['id']+'.html'
def section_url(ch,s):return url(ch)+'#'+s['id']
LINKS={s['title']:section_url(c,s) for c in CHAPTERS for s in c['sections'] if not s.get('intro')}
LINKS.update({'Тест брони Д12':'pravila-povrezhdeniya.html#test-broni-d12','Тест выживания Д6':'pravila-povrezhdeniya.html#test-vyzhivaniya-d6','Ближний бой':'pravila-blizhniy-boy.html','Паника':'pravila-panika.html','Захват боевых машин':'pravila-svoystva.html#zahvat-boevyh-mashin'})
link_pattern=re.compile('|'.join(re.escape(k) for k in sorted(LINKS,key=len,reverse=True) if len(k)>9))
def inline(text):
    return link_pattern.sub(lambda m:f'<a href="{LINKS[m.group()]}">{m.group()}</a>',esc(text))
def nav(current=None):
    return '<nav class="chapter-nav" aria-label="Главы правил"><ol>'+''.join(f'<li><a href="{url(c)}"'+(' aria-current="page"' if current==c['id'] else '')+f'><span class="number">{c["number"]:02}</span><span>{esc(c["title"])}</span></a></li>' for c in CHAPTERS)+'</ol></nav>'
def status():return f'<div class="offline-control"><button type="button" class="offline-label" data-refresh-offline disabled title="Проверить и загрузить обновления с сайта">{icon("download-simple")}<span data-offline>Сохранение для чтения без интернета…</span></button><span class="offline-feedback" data-offline-feedback role="status"></span></div>'
def frame(title,content,current=None,toc=''):
    catalog = current == 'catalog'
    header_tools = (f'<div class="catalog-header-status">{status()}</div>' if catalog else f'''<form class="top-search" action="search.html" role="search"><button aria-label="Найти правило" type="submit">{icon('magnifying-glass')}</button><input name="q" type="search" aria-label="Поиск по правилам" placeholder="Найти правило…" autocomplete="off"><kbd aria-hidden="true">Ctrl K</kbd></form><a class="button pdf-top" href="{PDF}" download>{icon('download-simple')}Скачать PDF</a>''')
    sidebar = '' if catalog else f'<aside class="sidebar">{nav(current)}<div class="sidebar-bottom">{status()}<button class="text-button" data-retry hidden>Повторить сохранение</button><a href="changes.html">Редакция и изменения</a></div></aside>'
    mobile_actions = (f'<a href="index.html">{icon("book-open")}Правила</a><a href="catalog.html" aria-current="page">{icon("list")}Каталог</a>' if catalog else f'<button data-open-chapters aria-haspopup="dialog">{icon("list")}Оглавление</button><a href="search.html">{icon("magnifying-glass")}Поиск</a>')
    mobile_actions += f'<a {FORUM_ATTRS}>{icon("chat-circle")}Форум</a>'
    if not catalog: mobile_actions += f'<a href="{PDF}" download>{icon("download-simple")}PDF</a>'
    body=f'''<a class="skip" href="#main">Перейти к содержанию</a>
<header class="topbar"><a class="brand" href="index.html" aria-label="Бронепехота — главная"><strong>БРОНЕПЕХОТА</strong><span>{EDITION}</span></a>
<nav class="global-nav" aria-label="Основная навигация"><a href="index.html" class="{'active' if not catalog else ''}">Правила</a><a href="catalog.html" class="{'active' if catalog else ''}">Каталог</a><a {FORUM_ATTRS}>Форум<small>GitHub</small></a></nav>
<button class="menu-button" data-open-chapters aria-label="Открыть оглавление" aria-haspopup="dialog">{icon('list')}</button>
{header_tools}</header>
<div class="shell">{sidebar}
<main id="main" class="main" tabindex="-1">{content}<footer class="site-footer"><span>{EDITION} · {RELEASE['date'][8:10]}.{RELEASE['date'][5:7]}.{RELEASE['date'][:4]}</span><a href="changes.html">История изменений</a><a href="{PDF}" download>Правила в PDF</a></footer></main></div>
<div class="mobile-bar"><nav class="mobile-actions" aria-label="Быстрые действия">{mobile_actions}</nav><div class="mobile-status">{status()}<button class="text-button" data-retry hidden>Повторить</button></div></div>
<dialog class="chapter-dialog" aria-labelledby="dialog-title"><div class="dialog-head"><h2 id="dialog-title">Оглавление</h2><button class="dialog-close" aria-label="Закрыть оглавление">{icon('x')}</button></div>{nav(current)}<a class="button secondary" href="catalog.html">Каталог подразделений</a></dialog>
<div class="update-banner" role="status" hidden><span>Есть обновление сайта. Обновить сохранённые материалы?</span><button data-update>Обновить</button><button data-dismiss aria-label="Отложить обновление">Позже</button></div>'''
    extras = '<link rel="stylesheet" href="assets/catalog.css"><script type="module" src="assets/catalog.js"></script>' if catalog else ''
    return f'''<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><title>{esc(title)} — Бронепехота</title><meta name="description" content="Уральская версия правил Бронепехоты: главы, поиск и PDF. Читайте во время партии с телефона или компьютера."><meta name="theme-color" content="#30483b"><meta name="bp-version" content="{RELEASE['version']}"><link rel="icon" href="assets/icons/book-open.svg" type="image/svg+xml"><link rel="stylesheet" href="assets/site.css"><link rel="preload" href="assets/fonts/PT_Sans-Web-Regular.ttf" as="font" type="font/ttf" crossorigin><script type="module" src="assets/app.js"></script>{extras}</head><body class="{'catalog-page' if catalog else 'rules-page'}">{body}<noscript><p class="main">Главы и PDF доступны без JavaScript. Для поиска и сохранения офлайн-версии включите JavaScript.</p></noscript></body></html>'''
def table(b):
    return '<div class="table-wrap" tabindex="0" role="region" aria-label="'+esc(b['title'])+'"><table><caption>'+esc(b['title'])+'</caption><thead><tr>'+''.join('<th scope="col">'+esc(v)+'</th>' for v in b['headers'])+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+inline(v)+'</td>' for v in row)+'</tr>' for row in b['rows'])+'</tbody></table></div>'
def blocks_html(blocks):
    pieces=[];in_list=False
    for i,b in enumerate(blocks):
        t=b['type']
        if t!='bullet' and in_list:pieces.append('</ul>');in_list=False
        if t=='bullet':
            if not in_list:pieces.append('<ul>');in_list=True
            pieces.append('<li>'+inline(b['text'])+'</li>')
        elif t=='p':pieces.append('<p>'+inline(b['text'])+'</p>')
        elif t=='note':pieces.append('<aside class="editor-note"><strong>'+icon('warning')+'Требует уточнения</strong><p>'+inline(b['text'])+'</p></aside>')
        elif t=='table':pieces.append(table(b))
        elif t=='figure':
            path='assets/rules/'+b['file'];w,h=Image.open(ROOT/path).size
            fig=f'<figure class="figure"><a href="{path}" target="_blank" style="width:min(100%,{w}px)" aria-label="Открыть изображение крупно: {esc(b["caption"])}"><img src="{path}" alt="{esc(b["caption"])}" width="{w}" height="{h}" decoding="async"></a><figcaption>{esc(b["caption"])}</figcaption></figure>'
            if i+1<len(blocks) and blocks[i+1].get('transcription'):fig='<details class="source-image"><summary>Оригинальная иллюстрация из правил</summary>'+fig+'</details>'
            pieces.append(fig)
    if in_list:pieces.append('</ul>')
    return ''.join(pieces)
def plain(b):
    if b['type']=='table':return b['title']+' '+ ' '.join(b['headers'])+' '+ ' '.join(' '.join(row) for row in b['rows'])
    return b.get('text',b.get('caption',''))
def build(skip_pdf=False):
    DIST.mkdir(exist_ok=True)
    # Generated PDFs from earlier editions must not enter the new offline release.
    for previous_pdf in DIST.glob('bronepehota-ural-*.pdf'):
        if previous_pdf.name != PDF:previous_pdf.unlink()
    shutil.copytree(ROOT/'assets',DIST/'assets',dirs_exist_ok=True,ignore=shutil.ignore_patterns('units'))
    from catalog_media import build_media
    build_media(ROOT,DIST)
    index=[]
    for pos,c in enumerate(CHAPTERS):
        secs=c['sections'];toc=''.join(f'<a href="#{s["id"]}" class="{"sub" if s["level"]==3 else ""}">{esc(s["title"])}</a>' for s in secs if not s.get('intro'))
        content=f'<div class="breadcrumbs"><a href="index.html">Правила</a><span>/</span>{esc(c["title"])}</div><header class="chapter-header"><span class="chapter-label">ГЛАВА {c["number"]:02}</span><h1>{esc(c["title"])}</h1></header>'
        if toc:content+='<details class="mobile-toc"><summary>В этой главе</summary>'+toc+'</details>'
        content+='<div class="content-layout"><article class="article">'
        for s in secs:
            heading='' if s.get('intro') else f'<h{s["level"]}><a class="heading-link" href="#{s["id"]}">{esc(s["title"])}</a></h{s["level"]}>'
            context=f'<a class="section-context" href="{url(c)}#main">{icon("arrow-left")}<span>{c["number"]:02} · {esc(c["title"])}</span></a>'
            content+=f'<section id="{s["id"]}" class="rule-section" data-searchable>{context}{heading}{blocks_html(s["blocks"])}</section>'
            index.append({'id':c['id']+'/'+s['id'],'title':s['title'],'chapter':c['title'],'number':c['number'],'url':section_url(c,s),'text':' '.join(plain(b) for b in s['blocks'])})
        content+='</article><aside class="local-toc" aria-label="В этой главе"><p>В ЭТОЙ ГЛАВЕ</p>'+toc+'</aside></div><nav class="chapter-pager" aria-label="Соседние главы">'
        if pos:content+=f'<a href="{url(CHAPTERS[pos-1])}">{icon("arrow-left")}{esc(CHAPTERS[pos-1]["title"])}</a>'
        else:content+='<span></span>'
        if pos+1<len(CHAPTERS):content+=f'<a href="{url(CHAPTERS[pos+1])}">{esc(CHAPTERS[pos+1]["title"])}{icon("arrow-right")}</a>'
        content+='</nav>'
        (DIST/url(c)).write_text(frame(c['title'],content,c['id']),encoding='utf-8')
    (DIST/'assets/search-index.json').write_text(json.dumps(index,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    descriptions=['Что такое Бронепехота и как устроена партия','Поле, армии, кубики и обозначения','Пехота, машины, пилоты и артиллерия','Инициатива и последовательность действий','Передвижение, препятствия и типы техники','Повреждения, броня и выживание пилота','Дальность, мощность, боезапас и гранаты','Атака, защита, поддержка и таран','Захват, ремонт, прыжки и транспортировка','Проверка паники и возвращение в бой']
    home=f'<div class="home"><div class="breadcrumbs">{EDITION}</div><h1>Правила под рукой</h1><p class="lede">Бронепехота — научно-фантастическая игра о сражениях пехотных отрядов, боевых машин и артиллерии. Выберите главу или найдите нужное правило.</p><div class="quick-links"><a class="button secondary" href="pravila-povrezhdeniya.html#test-broni-d12">Тест брони Д12</a><a class="button secondary" href="pravila-blizhniy-boy.html">Ближний бой</a><a class="button secondary" href="pravila-panika.html">Паника</a></div><ol class="home-list">'
    for c,d in zip(CHAPTERS,descriptions):home+=f'<li><a href="{url(c)}"><span class="num">{c["number"]:02}</span><span><strong>{esc(c["title"])}</strong><small>{d}</small></span>{icon("arrow-right")}</a></li>'
    home+=f'</ol><div class="release-row"><p><strong>Все правила одним файлом</strong><br>PDF для чтения и печати · {EDITION}</p><a class="button" href="{PDF}" download>{icon("download-simple")}Скачать PDF</a></div></div>'
    (DIST/'index.html').write_text(frame('Правила',home),encoding='utf-8')
    from catalog_site import build_catalog
    build_catalog(ROOT,DIST,frame)
    (DIST/'armies.html').write_text('<!doctype html><html lang="ru"><meta charset="utf-8"><meta http-equiv="refresh" content="0;url=catalog.html"><title>Каталог подразделений</title><a href="catalog.html">Перейти к каталогу подразделений</a></html>',encoding='utf-8')
    search='<div class="search-page"><div class="breadcrumbs"><a href="index.html">Правила</a><span>/</span>Поиск</div><h1>Поиск по правилам</h1><form class="search-form" role="search"><input type="search" name="q" id="rule-query" aria-label="Что найти в правилах" placeholder="Например, броня или гранаты" autocomplete="off"><button class="button" type="submit">Найти</button></form><p class="search-info" id="search-info" role="status">Ищем по тексту, таблицам и обозначениям.</p><div id="search-content"></div></div>'
    (DIST/'search.html').write_text(frame('Поиск',search),encoding='utf-8')
    history=''.join('<h2>'+esc(RELEASE['edition']+' '+r['version'])+'</h2><p>'+esc(r['date'])+'</p><ul>'+''.join('<li>'+esc(x)+'</li>' for x in r['changes'])+'</ul>' for r in RELEASE.get('history',[]))
    changes='<div class="home"><div class="breadcrumbs"><a href="index.html">Правила</a><span>/</span>Редакция</div><h1>Редакция и изменения</h1><h2>'+EDITION+'</h2><p>'+RELEASE['date']+'</p><ul>'+''.join('<li>'+esc(x)+'</li>' for x in RELEASE['changes'])+'</ul><p>Основа правил — предоставленная фанатская редакция. Согласованные изменения механики перечислены в истории выпусков. Нерешённые вопросы выделены примечаниями «Требует уточнения».</p>'+history+'<h2>Редакционные исправления</h2><p>При первоначальном переносе восстановлены пробелы в склеенных словах, объединены разорванные переносом страницы предложения и исправлены очевидные опечатки. Изменения игровой механики фиксируются отдельно для каждой редакции.</p><h2>Чтение без интернета</h2><p>При первом открытии сайт сохраняет все главы, 105 карточек каталога, небольшие изображения, поиск и PDF. Увеличенные изображения сохраняются по мере просмотра. Дождитесь статуса «Доступно без интернета». Сохранение относится к этому браузеру и устройству. Если очистить данные сайта, материалы потребуется загрузить заново.</p><p>При появлении новой сборки сайт загружает только изменённые файлы и предлагает обновление. До его принятия доступна сохранённая редакция. Для ручной проверки нажмите «Доступно без интернета»: появится прогресс, после подготовки сайт переключится на новую сборку. При обрыве можно повторить загрузку; уже сохранённые файлы не потребуется скачивать заново.</p></div>'
    changes=changes.replace('<h2>Чтение без интернета</h2>',f'<h2>Обсуждение правил</h2><p><a {FORUM_ATTRS}>Форум на GitHub</a> — вопросы по правилам, предложения по изменениям и объявления о новых редакциях. Читать можно без регистрации; чтобы участвовать, войдите в GitHub. Форум открывается в новой вкладке и требует интернета.</p><p>Обсуждение и отмеченный ответ сами по себе не меняют правила. Изменения утверждает владелец проекта и включает в следующую редакцию сайта и PDF.</p><h2>Чтение без интернета</h2>')
    (DIST/'changes.html').write_text(frame('Редакция и изменения',changes),encoding='utf-8')
    (DIST/'404.html').write_text(frame('Страница не найдена','<div class="empty-page"><h1>Страница не найдена</h1><p>Возможно, ссылка изменилась. Откройте оглавление или воспользуйтесь поиском.</p><a class="button" href="index.html">К правилам</a></div>'),encoding='utf-8')
    (DIST/'.nojekyll').write_text('',encoding='utf-8')
    if not skip_pdf:
        from make_pdf import make_pdf
        make_pdf(CHAPTERS,RELEASE,DIST/PDF)
    # Every release is an atomic, complete offline set, including the PDF.
    files=sorted(p for p in DIST.rglob('*') if p.is_file() and p.name not in ('sw.js','build.json','precache.json')
                 and not any(part.startswith('.') for part in p.relative_to(DIST).parts))
    digest=hashlib.sha256()
    for p in files:digest.update(p.relative_to(DIST).as_posix().encode());digest.update(p.read_bytes())
    # Large cutouts are optional and cached when viewed; the complete build still hashes them.
    files=[p for p in files if 'assets/units/large/' not in p.relative_to(DIST).as_posix()]
    build_id=digest.hexdigest()[:16];manifest=[p.relative_to(DIST).as_posix() for p in files]
    config={'version':RELEASE['version'],'build':build_id,'files':manifest,'hashes':{p.relative_to(DIST).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in files},'sizes':{p.relative_to(DIST).as_posix():p.stat().st_size for p in files}}
    (DIST/'precache.json').write_text(json.dumps(config,ensure_ascii=False),encoding='utf-8')
    sw=(ROOT/'assets/sw-template.js').read_text(encoding='utf-8').replace('__BUILD__',build_id).replace('__VERSION__',RELEASE['version'])
    (DIST/'sw.js').write_text(sw,encoding='utf-8')
    (DIST/'build.json').write_text(json.dumps({'version':RELEASE['version'],'build':build_id,'chapters':len(CHAPTERS),'sections':len(index),'files':len(manifest)}),encoding='utf-8')
    print(f'Built {len(CHAPTERS)} chapters, {len(index)} searchable sections, {len(manifest)} offline assets. Build {build_id}')
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--skip-pdf',action='store_true');args=parser.parse_args();build(args.skip_pdf)
