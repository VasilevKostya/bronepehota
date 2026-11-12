import copy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from catalog_scale import attach_body_metrics, body_metrics, stage_metrics


class BodyScaleTests(unittest.TestCase):
    def test_raised_weapon_changes_headroom_not_body_height(self):
        regular = {'id': 'regular', 'width': 90, 'height': 120, 'small_sha256': 'a'}
        raised = {'id': 'raised', 'width': 90, 'height': 190, 'small_sha256': 'b'}
        a = body_metrics(regular, {'sha256': 'a', 'head_y': 10, 'feet_y': 110})
        b = body_metrics(raised, {'sha256': 'b', 'head_y': 80, 'feet_y': 180})
        self.assertEqual(a['width'], b['width'])
        self.assertAlmostEqual(a['height'] / 120 * 100, b['height'] / 190 * 100)
        self.assertGreater(b['above'], a['above'])

    def test_feet_share_baseline_despite_different_bottom_padding(self):
        images = []
        for height, feet in [(120, 110), (140, 110), (180, 160)]:
            image = {'id': str(height), 'width': 90, 'height': height, 'small_sha256': 'a'}
            image['_body'] = body_metrics(image, {'sha256': 'a', 'head_y': feet-100, 'feet_y': feet})
            images.append(image)
        stage = stage_metrics(images)
        for im in images:
            body = im['_body']
            offset = stage['below'] - body['below']
            self.assertAlmostEqual(offset + body['below'], stage['below'])
            self.assertGreaterEqual(offset, 0)
            self.assertLessEqual(offset + body['height'], stage['ratio'])

    def test_kneeling_pose_is_not_enlarged_to_standing_height(self):
        image = {'id': 'kneeling', 'width': 90, 'height': 100, 'small_sha256': 'a'}
        body = body_metrics(image, {'sha256': 'a', 'head_y': 10, 'feet_y': 90, 'pose_ratio': 0.8})
        self.assertAlmostEqual(body['width'], 0.9)
        self.assertAlmostEqual(body['height'] * 80 / 100, 0.8)

    def test_stale_image_annotation_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'need review'):
            body_metrics({'id': 'changed', 'small_sha256': 'new'}, {'sha256': 'old'})

    def test_invalid_landmarks_are_rejected(self):
        image = {'id': 'bad', 'width': 100, 'height': 120, 'small_sha256': 'a'}
        for head, feet, pose in [(110, 10, 1), (10, 120, 1), (-1, 110, 1), (10, 110, 0), (float('nan'), 110, 1)]:
            with self.subTest(head=head, feet=feet, pose=pose), self.assertRaises(ValueError):
                body_metrics(image, {'sha256': 'a', 'head_y': head, 'feet_y': feet, 'pose_ratio': pose})

    def test_every_reviewed_catalogue_profile_has_valid_complete_geometry(self):
        units = json.loads((ROOT/'content/catalog/catalog.json').read_text(encoding='utf-8'))['units']
        unchanged = copy.deepcopy([u for u in units if u['type'] != 'infantry'])
        attach_body_metrics(units, ROOT/'content/catalog/body-anchors.json')
        self.assertEqual(unchanged, [u for u in units if u['type'] != 'infantry'])
        count = 0
        for unit in units:
            if unit['type'] != 'infantry':
                continue
            stage = stage_metrics(unit['figures'])
            for profile, image in zip(unit['profiles'], unit['figures'], strict=True):
                self.assertEqual(profile['image']['_body'], image['_body'])
                body = image['_body']
                self.assertGreater(body['width'], 0)
                self.assertLessEqual(body['above'], stage['ratio'] - stage['below'] + 1e-9)
                self.assertLessEqual(body['below'], stage['below'])
                count += 1
        self.assertEqual(count, 414)


if __name__ == '__main__':
    unittest.main()
