"""Import reviewed unit profiles and accepted cutouts; never read instructions from sources.

Run locally when the source materials change. CI builds from the resulting catalog.json
and public WebP assets, without needing the private/source image workspace.
"""
from pathlib import Path
from collections import Counter
import json, hashlib, re, shutil

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'content/catalog'
EXTRACTION = ROOT / 'Извлечение-изображений'
FACTIONS = {'Империя': 'Империя', 'Протекторат': 'Протекторат', 'Рутения': 'Рутения',
            'Мертвый Флот': 'Мёртвый флот', 'Снежные волки': 'Снежные волки', 'Наемники': 'Наёмники'}
FIELDS = ['rank', 'speed', 'range', 'power', 'melee', 'properties', 'armor']

def read(path):
    return json.loads(path.read_text(encoding='utf-8'))

def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

def prepare():
    infantry = read(DATA / 'infantry.json')['units']
    technical = read(DATA / 'technical.json')['units']
    sheets = {x['source_id']: x for x in read(EXTRACTION / 'inventory/sources.json')['files'] if x['included']}
    objects = [x for x in read(EXTRACTION / 'catalogs/objects.json')['objects'] if x['is_current_accepted']]
    assert len(infantry) == 70 and len(technical) == 35 and len(objects) == 554
    assert set(sheets) == {x['source_id'] for x in infantry + technical}
    images, provenance = {}, []
    for obj in objects:
        image = {'id': obj['object_id'], 'width': obj['native_width'], 'height': obj['native_height']}
        for size, field in [('small', 'webp_native'), ('large', 'webp_x4')]:
            source = EXTRACTION / obj[field]
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            assert digest == obj[field + '_sha256'], source
            relative = 'assets/units/' + size + '/' + obj['object_id'].lower() + '.webp'
            target = ROOT / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            image[size] = relative
            image[size + '_sha256'] = digest
        images[obj['object_id']] = image
        provenance.append({'object_id': obj['object_id'], 'source_id': obj['source_id'],
                           'revision': obj['revision'], 'source_sha256': obj['source_sha256'],
                           'bbox': [obj['bbox_x'], obj['bbox_y'], obj['bbox_w'], obj['bbox_h']]})

    names = Counter(x['name'].lower().replace('ё', 'е') for x in infantry)
    units = []
    for record in infantry + technical:
        source_id = record['source_id']
        sheet = sheets[source_id]
        source_objects = sorted((x for x in objects if x['source_id'] == source_id), key=lambda x: x['object_id'])
        figures = [images[x['object_id']] for x in source_objects if x['object_type'] != 'weapon']
        weapons = [images[x['object_id']] for x in source_objects if x['object_type'] == 'weapon']
        unit_id = source_id.lower()
        is_infantry = sheet['category'] == 'Пехота'
        variant = ''
        if is_infantry:
            if record['variant'] in ('Л', 'Л1', 'Л2', 'Л-вариант'):
                variant = record['variant'].replace('-вариант', '')
            elif record['variant'].startswith('Новые') or record['variant'] == 'новый':
                variant = 'Новый лист'
            elif record['variant'] == 'новые':
                variant = 'Новые'
            elif record['variant'] == 'старые':
                variant = 'Старые'
            elif record['variant'].startswith('вариант 2'):
                variant = 'Вариант 2'
            elif names[record['name'].lower().replace('ё', 'е')] > 1:
                variant = 'Без суффикса'
        unit = {'id': unit_id, 'source_id': source_id, 'name': record['name'], 'variant': variant,
                'faction': FACTIONS[sheet['faction']], 'cost': record['cost'],
                'type': 'infantry' if is_infantry else record['type'],
                'type_label': 'Пехота' if is_infantry else record['type_label'],
                'test': '(ТЕСТ)' in sheet['filename'], 'figures': figures,
                'aliases': [Path(sheet['filename']).stem, record.get('code', '')],
                'source': {'file': sheet['filename'], 'sha256': sheet['sha256']},
                'url': 'unit-' + unit_id + '.html'}
        if is_infantry:
            assert len(figures) == len(record['rows']) == record['count'], source_id
            unit['profiles'] = [{'label': 'Боец ' + str(i + 1), 'image': figures[i],
                                 'stats': dict(zip(FIELDS, row))} for i, row in enumerate(record['rows'])]
            unit['ranks'] = sorted({int(row[0]) for row in record['rows']})
        else:
            unit['ranks'] = [record['rank']]
            for key in ('rank', 'rate', 'speed', 'armor', 'life', 'ammo', 'segments', 'notes', 'abilities', 'clarifications'):
                if key in record:
                    unit[key] = record[key]
            unit['weapons'] = []
            groups = [[0, 1], [2, 3], [4], [5, 6]] if unit['type'] == 'cavalry' else [[i] for i in range(len(weapons))]
            for i, weapon in enumerate(record['weapons']):
                unit['weapons'].append({**weapon, 'images': [weapons[j] for j in groups[i]] if weapons else []})
            if unit['type'] != 'hero':
                assert sum(len(w['images']) for w in unit['weapons']) == len(weapons)
        unit['search_text'] = ' '.join([unit['faction'], unit['type_label'], str(unit['cost']), variant,
                                      *unit['aliases'], json.dumps(unit.get('profiles', []), ensure_ascii=False),
                                      json.dumps(unit.get('weapons', []), ensure_ascii=False),
                                      json.dumps(unit.get('abilities', []), ensure_ascii=False)])
        # Search only game content, never image IDs, filenames or asset hashes.
        if is_infantry:
            stats = ' '.join(' '.join(row) for row in record['rows'])
            if 'Рм' in stats:
                stats += ' ремонт'
            if 'Пр' in stats:
                stats += ' прыжок прыжковый ускоритель'
        else:
            stats = ' '.join(' '.join(str(v) for k, v in w.items() if k != 'images' and v is not None) for w in unit['weapons'])
            stats += ' ' + ' '.join(a['title'] + ' ' + a['text'] for a in unit.get('abilities', []))
        unit['search_text'] = ' '.join([unit['faction'], unit['type_label'], str(unit['cost']), variant, *unit['aliases'], stats])
        units.append(unit)
    # Alphabetic reference index; no hidden or preferred version of a unit.
    units.sort(key=lambda x: (x['name'].casefold().replace('ё', 'е'), x['variant'], x['id']))
    write(DATA / 'catalog.json', {'schema_version': 1, 'updated': '2026-11-12', 'units': units})
    write(DATA / 'image-provenance.json', provenance)
    print(f'Prepared {len(units)} units; {len(objects)} accepted cutouts in two sizes.')

if __name__ == '__main__':
    prepare()
