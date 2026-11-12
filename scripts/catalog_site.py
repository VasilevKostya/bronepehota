"""Static catalogue surfaces. Data and image provenance live in content/catalog."""
import html
import json

def esc(value):
    return html.escape(str(value), quote=True)

def icon(name):
    return f'<span class="icon" style="--icon:url(icons/{name}.svg)" aria-hidden="true"></span>'

TERMS = {
    'rank': ('А', 'Армейский ранг', 'Уровень выучки бойца: используется при взаимодействии с техникой и орудиями, броске гранаты и проверке паники.', 'pravila-boevye-edinitsy.html#pehotnye-otryady'),
    'speed': ('Скорость', 'Скорость (Ск)', 'Число шагов за ход. Один шаг равен 4 см.', 'pravila-dvizhenie.html'),
    'range': ('Дальность', 'Дальность стрельбы', 'Тип и число кубиков для определения дальности выстрела.', 'pravila-strelba.html#dalnost-strelby'),
    'power': ('Мощность', 'Мощность выстрела', 'Тип и число кубиков для определения результата выстрела и урона.', 'pravila-strelba.html'),
    'melee': ('Ближний бой', 'Ближний бой (ББ)', 'Показатель мастерства бойца и силы его оружия в ближнем бою.', 'pravila-blizhniy-boy.html'),
    'properties': ('Свойства', 'Особые свойства (Св)', 'Особые способности бойца. Прочерк сохраняется как в исходном листе.', 'pravila-svoystva.html'),
    'armor': ('Броня', 'Броня (Бр)', 'Показатель защиты бойца. У техники сверяйте значение с её шкалой и правилами повреждений.', 'pravila-povrezhdeniya.html'),
    'repair': ('Рм', 'Ремонт', 'Свойство позволяет пехотинцу ремонтировать технику по правилам ремонта. Уничтоженная техника не ремонтируется.', 'pravila-svoystva.html#remont'),
    'jump': ('Пр', 'Прыжковый ускоритель', 'Число после «Пр» указывает дальность прыжка в шагах. Ограничения описаны в правиле ускорителей.', 'pravila-svoystva.html#rantsevye-pryzhkovye-uskoriteli'),
    'ammo': ('Боезапас', 'Боезапас (БК)', 'Число единиц боезапаса, показанное на листе. Для каждого орудия сохранена его собственная шкала.', 'pravila-strelba.html'),
}

def term(key, label=None):
    return f'<a class="term-link" data-term href="#term-{key}">{esc(label or TERMS[key][0])}</a>'

def glossary():
    entries = ''.join(f'<div id="term-{key}"><dt>{esc(title)}</dt><dd>{esc(text)} <a href="{url}">Правило{icon("arrow-right")}</a></dd></div>'
                      for key, (_, title, text, url) in TERMS.items())
    return '<details class="catalog-glossary" id="glossary"><summary>Обозначения и свойства</summary><dl>' + entries + '</dl></details>'

def image_tag(image, alt, large=False):
    attrs = f' data-large="{esc(image["large"])}"' if large else ''
    return f'<img src="{esc(image["small"])}"{attrs} alt="{esc(alt)}" width="{image["width"]}" height="{image["height"]}" loading="lazy" decoding="async">'

def group(unit):
    images = ''.join(image_tag(img, unit['name'] + (f' · боец {i + 1}' if unit['type'] == 'infantry' else '')) for i, img in enumerate(unit['figures']))
    if unit['type'] == 'infantry':
        ratio = sum(img['width'] / img['height'] for img in unit['figures'])
        return f'<span class="unit-group unit-group-infantry" style="--group-ratio:{ratio:.6f};--group-gaps:{len(unit["figures"])-1}">{images}</span>'
    return f'<span class="unit-group unit-group-single">{images}</span>'

def tags(unit):
    return ('<span class="variant-label">' + esc(unit['variant']) + '</span>' if unit['variant'] else '') + ('<span class="test-label">Тест</span>' if unit['test'] else '')

def list_row(unit):
    count = f'{len(unit["figures"])} бойцов' if unit['type'] == 'infantry' else 'Ранг ' + ', '.join(map(str, unit['ranks']))
    label = ' · '.join(filter(None,[unit['name'],unit['variant'],unit['faction'],unit['type_label'],str(unit['cost'])+' очков','Тест' if unit['test'] else '']))
    return f'''<li class="catalog-row" data-unit="{unit['id']}"><a class="catalog-unit-link" href="{unit['url']}" aria-label="{esc(label)}">
{group(unit)}<span class="unit-identity"><strong>{esc(unit['name'])}</strong><span class="unit-tags">{tags(unit)}</span><span class="unit-subtitle">{esc(unit['faction'])} · {esc(unit['type_label'])}</span><span class="unit-count">{count}</span></span>
<span class="unit-faction">{esc(unit['faction'])}</span><span class="unit-kind">{esc(unit['type_label'])}</span><span class="unit-price">{unit['cost']} <span>оч.</span></span>{icon('arrow-right')}</a></li>'''

def options(values, title):
    return f'<option value="">{title}</option>' + ''.join(f'<option value="{esc(key)}">{esc(label)}</option>' for key, label in values)

def listing(units):
    factions = sorted({u['faction'] for u in units})
    types = [('infantry', 'Пехота'), ('vehicle', 'Техника'), ('cavalry', 'Кавалерия'), ('hero', 'Герои')]
    ranks = sorted({r for u in units for r in u['ranks']})
    filters = f'''<form id="catalog-form" class="catalog-form" role="search">
<label class="sr-only" for="catalog-query">Поиск подразделения, оружия или свойства</label><div class="catalog-search">{icon('magnifying-glass')}<input id="catalog-query" type="search" name="q" placeholder="Найти подразделение или оружие…" autocomplete="off" disabled><button type="submit" class="button" disabled>Найти</button></div>
<details class="catalog-filters" open><summary>Фильтры{icon('caret-down')}</summary><div class="catalog-filter-fields">
<label>Фракция<select name="faction" disabled>{options([(f,f) for f in factions], 'Все фракции')}</select></label>
<label>Тип<select name="type" disabled>{options(types, 'Все типы')}</select></label>
<fieldset class="cost-filter"><legend>Стоимость, оч.</legend><label><span class="sr-only">От</span><input name="min" type="number" min="0" step="1" inputmode="numeric" placeholder="от" disabled></label><span aria-hidden="true">—</span><label><span class="sr-only">До</span><input name="max" type="number" min="0" step="1" inputmode="numeric" placeholder="до" disabled></label></fieldset>
<details class="catalog-more"><summary>Ещё фильтры</summary><div><label>Армейский ранг<select name="rank" disabled>{options([(str(r),str(r)) for r in ranks], 'Любой ранг')}</select></label><label class="catalog-checkbox"><input name="test" type="checkbox" value="1" disabled> Только тестовые</label></div></details>
<button class="text-button catalog-reset" type="reset" disabled>Сбросить</button></div></details></form>'''
    return f'''<header class="catalog-heading"><h1>Каталог подразделений</h1><p>{len(units)} записей · {len(factions)} фракций</p></header>{filters}
<p class="catalog-results-info" id="catalog-results-info" role="status">Все подразделения</p><button type="button" class="button secondary" id="catalog-retry" hidden>Повторить загрузку поиска</button>
<div class="catalog-columns" aria-hidden="true"><span>Подразделение</span><span>Фракция</span><span>Тип</span><span>Стоимость</span></div>
<ul class="catalog-list" id="catalog-list">{''.join(list_row(u) for u in units)}</ul>
<div class="catalog-empty" id="catalog-empty" hidden><h2>Подразделения не найдены</h2><p>Попробуйте другое название или уменьшите число фильтров.</p><button type="button" class="button secondary" data-clear-catalog>Сбросить поиск и фильтры</button></div>
<noscript><p>Все карточки доступны. Для поиска и фильтров включите JavaScript.</p></noscript>'''

def profile_table(unit):
    # Reserve enough width for the widest full-height figure, including its weapon.
    ratio = max(p['image']['width'] / p['image']['height'] for p in unit['profiles'])
    heads = ''.join(f'<th scope="col" id="fighter-{i+1}"><span>{esc(p["label"])}</span>{image_tag(p["image"],unit["name"]+" · "+p["label"],True)}</th>' for i, p in enumerate(unit['profiles']))
    rows = []
    for key in ('rank','speed','range','power','melee','properties','armor'):
        cells = []
        for i, p in enumerate(unit['profiles']):
            value = p['stats'][key]
            rendered = term('repair',value) if value == 'Рм' else term('jump',value) if value.startswith('Пр') else esc(value)
            cells.append(f'<td headers="stat-{key} fighter-{i+1}">{rendered}</td>')
        rows.append(f'<tr><th scope="row" id="stat-{key}">{term(key)}</th>{"".join(cells)}</tr>')
    return f'''<section aria-labelledby="profiles-title"><div class="unit-section-heading"><h2 id="profiles-title">Состав и характеристики</h2><a href="#glossary" data-term>Обозначения{icon('arrow-right')}</a></div>
<div class="fighter-table-wrap" tabindex="0" role="region" aria-label="Бойцы и их характеристики; таблица прокручивается по горизонтали" data-scroll-table><table class="fighter-table" style="--fighters:{len(unit['profiles'])};--figure-ratio:{ratio:.6f}"><caption class="sr-only">{esc(unit['name'])} — индивидуальные параметры</caption><thead><tr><th scope="col"><span class="sr-only">Характеристика</span><span class="table-scroll-hint" data-scroll-hint hidden>Листайте{icon('arrow-right')}</span></th>{heads}</tr></thead><tbody>{''.join(rows)}</tbody></table></div></section>'''

def scale(values, label):
    return '<span class="value-scale" aria-label="' + esc(label) + '">' + ''.join('<span>'+str(v)+'</span>' for v in values) + '</span>'

def technical_body(unit):
    stats = [('Армейский ранг', unit['rank'])]
    for label, key in [('Скорострельность','rate'),('Скорость','speed'),('Броня','armor'),('Жизни','life')]:
        if key in unit:
            stats.append((label, unit[key]))
    portrait = image_tag(unit['figures'][0], unit['name'], True)
    body = '<section class="technical-overview"><div class="technical-portrait">'+portrait+'</div><dl class="technical-stats">'+''.join(f'<div><dt>{label}</dt><dd>{value}</dd></div>' for label,value in stats)+'</dl></section>'
    if unit.get('segments'):
        body += '<section class="unit-section"><h2>Прочность и скорость</h2><div class="durability-segments">'
        for segment in unit['segments']:
            start,end,speed,zone,*armor = segment
            body += f'<div class="durability-segment zone-{zone}"><p><strong>Скорость {speed}</strong>' + (f'<span>Броня {armor[0]}</span>' if armor else '')+'</p>'+scale(range(start,end-1,-1),'Шкала от '+str(start)+' до '+str(end))+'</div>'
        body += '</div><p class="unit-caption">Уничтоженная техника удаляется с поля и не ремонтируется.</p></section>'
    if unit.get('life'):
        body += '<section class="unit-section"><h2>Жизни</h2>'+scale(range(unit['life'],0,-1),'Шкала жизней')+'</section>'
    if unit.get('ammo'):
        body += '<section class="unit-section"><h2>Общий боезапас</h2>'+scale(range(unit['ammo'],0,-1),'Общий боезапас')+'</section>'
    body += '<section class="unit-section"><div class="unit-section-heading"><h2>Вооружение</h2><a href="#glossary" data-term>Обозначения'+icon('arrow-right')+'</a></div><div class="weapon-list">'
    for weapon in unit.get('weapons', []):
        body += '<article class="weapon"><h3>'+esc(weapon['name'])+'</h3>'
        if weapon['images']:
            body += '<div class="weapon-images">'+''.join(image_tag(i,weapon['name'],True) for i in weapon['images'])+'</div>'
        body += '<dl class="weapon-stats">'
        for label,key in [('Дальность','range'),('Мощность','power'),('Ближний бой','melee')]:
            if weapon.get(key) is not None:
                body += f'<div><dt>{term(key,label)}</dt><dd>{esc(weapon[key])}</dd></div>'
        body += '</dl>'
        if weapon['ammo'] is not None:
            body += '<div class="weapon-ammo">'+term('ammo')+scale(range(weapon['ammo'],0,-1),'Боезапас: '+str(weapon['ammo']))+'</div>'
        if weapon.get('note'):
            body += '<p>'+esc(weapon['note'])+'</p>'
        body += '</article>'
    body += '</div></section>'
    for ability in unit.get('abilities', []):
        body += '<section class="unit-section"><h2>'+esc(ability['title'])+'</h2><p>'+esc(ability['text'])+'</p></section>'
    for note in unit.get('notes', []):
        body += '<p class="unit-note">'+esc(note)+'</p>'
    for note in unit.get('clarifications', []):
        body += '<aside class="editor-note"><strong>'+icon('warning')+'Требует уточнения</strong><p>'+esc(note)+'</p></aside>'
    return body

def detail(unit, units):
    count = f' · {len(unit["figures"])} бойцов' if unit['type'] == 'infantry' else ''
    related = [u for u in units if u['id'] != unit['id'] and u['name'].casefold().replace('ё','е') == unit['name'].casefold().replace('ё','е')]
    content = f'''<div class="unit-topline"><a href="catalog.html" data-catalog-back>{icon('arrow-left')}К каталогу</a><a href="{unit['url']}" data-share-unit>{icon('link')}Ссылка</a><span class="sr-only" role="status" data-copy-status></span></div>
<header class="unit-heading"><div><h1>{esc(unit['name'])}</h1><p>{esc(unit['faction'])} · {esc(unit['type_label'])}{count}</p><div class="unit-tags">{tags(unit)}</div></div><p class="unit-price">{unit['cost']} <span>оч.</span></p></header>
<div class="copy-link-fallback" hidden><label>Ссылка на подразделение<input readonly type="url" aria-label="Ссылка на подразделение"></label></div>'''
    content += profile_table(unit) if unit['type'] == 'infantry' else technical_body(unit)
    content += glossary()
    if related:
        content += '<nav class="related-variants" aria-label="Другие варианты подразделения"><h2>Другие варианты</h2>'+''.join(f'<a href="{u["url"]}">{esc(u["name"])} · {esc(u["variant"])} · {u["cost"]} оч.</a>' for u in related)+'</nav>'
    return content

def build_catalog(root, dist, frame):
    units = json.loads((root/'content/catalog/catalog.json').read_text(encoding='utf-8'))['units']
    (dist/'catalog.html').write_text(frame('Каталог подразделений',listing(units),'catalog'),encoding='utf-8')
    for unit in units:
        (dist/unit['url']).write_text(frame(unit['name'] + (' · '+unit['variant'] if unit['variant'] else ''),detail(unit,units),'catalog'),encoding='utf-8')
    fields = ('id','name','variant','faction','cost','type','type_label','ranks','test','aliases','search_text','url')
    (dist/'assets/catalog-index.json').write_text(json.dumps([{k:u[k] for k in fields} for u in units],ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    optional = {}
    for unit in units:
        images = unit['figures']+[i for w in unit.get('weapons',[]) for i in w['images']]
        for image in images:
            optional[image['large']] = {'sha256':image['large_sha256'],'fallback':image['small']}
    (dist/'assets/catalog-large.json').write_text(json.dumps(optional,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
