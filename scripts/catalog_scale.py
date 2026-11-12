"""Reviewed body landmarks, independent of weapons and transparent image padding."""
import json
import math


def body_metrics(image, anchor):
    if anchor['sha256'] != image['small_sha256']:
        raise ValueError('Body landmarks need review after image change: ' + image['id'])
    head, feet = anchor['head_y'], anchor['feet_y']
    pose = anchor.get('pose_ratio', 1)
    if not all(math.isfinite(n) for n in (head, feet, pose)) or not (
        0 <= head < feet < image['height'] and 0.5 <= pose <= 1
    ):
        raise ValueError('Invalid body landmarks: ' + image['id'])
    # A kneeling figure stays shorter without stretching its anatomy.
    reference = (feet - head) / pose
    return {'width': image['width'] / reference,
            'height': image['height'] / reference,
            'above': feet / reference,
            'below': (image['height'] - feet) / reference}


def attach_body_metrics(units, path):
    anchors = json.loads(path.read_text(encoding='utf-8'))['images']
    expected = {im['id'] for u in units if u['type'] == 'infantry' for im in u['figures']}
    if set(anchors) != expected:
        raise ValueError('Every infantry image needs reviewed body landmarks; missing: '
                         + ', '.join(sorted(expected - set(anchors)))
                         + '; stale: ' + ', '.join(sorted(set(anchors) - expected)))
    for unit in units:
        if unit['type'] != 'infantry':
            continue
        for im in unit['figures'] + [p['image'] for p in unit['profiles']]:
            im['_body'] = body_metrics(im, anchors[im['id']])


def stage_metrics(images):
    above = max(im['_body']['above'] for im in images)
    below = max(im['_body']['below'] for im in images)
    return {'ratio': above + below, 'below': below,
            'widest': max(im['_body']['width'] for im in images),
            'total_width': sum(im['_body']['width'] for im in images)}
