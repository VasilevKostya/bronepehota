import gzip
import importlib.util
import io
import json
from pathlib import Path
import shutil
import tarfile
import unittest
import uuid
from unittest.mock import patch


spec = importlib.util.spec_from_file_location('forumctl', Path(__file__).parents[1] / 'ops/flarum/forumctl.py')
forumctl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(forumctl)


class ForumBackupSafetyTests(unittest.TestCase):
    def setUp(self):
        temporary_root = Path(__file__).parents[1] / 'tmp/flarum-tests'
        temporary_root.mkdir(parents=True, exist_ok=True)
        self.root = temporary_root.resolve() / uuid.uuid4().hex
        self.root.mkdir()

        def cleanup():
            if self.root.is_symlink() or self.root.resolve().parent != temporary_root.resolve():
                raise RuntimeError('Unsafe test cleanup path')
            shutil.rmtree(self.root)

        self.addCleanup(cleanup)

    def archive(self, path, name='notes.txt', content=b'forum data'):
        with tarfile.open(path, 'w:gz') as archive:
            member = tarfile.TarInfo(name)
            member.size = len(content)
            archive.addfile(member, io.BytesIO(content))

    def backup(self):
        with gzip.open(self.root / 'database.sql.gz', 'wb') as output:
            output.write('SELECT "Бронепехота";\n'.encode())
        for filename in ('app.tar.gz', 'deployment.tar.gz'):
            self.archive(self.root / filename)
        manifest = {'schema': 1, 'database_image': forumctl.DB_IMAGE, 'table_checksums': {},
                    'sha256': {name: forumctl.sha256(self.root / name) for name in forumctl.ARCHIVES}}
        (self.root / 'manifest.json').write_text(json.dumps(manifest))
        return manifest

    def test_complete_backup_can_be_verified_and_extracted(self):
        manifest = self.backup()
        self.assertEqual(forumctl.verify_backup(self.root), manifest)
        destination = self.root / 'restored'
        destination.mkdir()
        forumctl.extract_safe(self.root / 'app.tar.gz', destination)
        self.assertEqual((destination / 'notes.txt').read_bytes(), b'forum data')

    def test_damaged_dump_is_rejected_before_restore(self):
        self.backup()
        with (self.root / 'database.sql.gz').open('ab') as output:
            output.write(b'damage')
        with self.assertRaisesRegex(RuntimeError, 'checksum mismatch'):
            forumctl.verify_backup(self.root)

    def test_incomplete_manifest_is_rejected(self):
        manifest = self.backup()
        del manifest['sha256']['app.tar.gz']
        (self.root / 'manifest.json').write_text(json.dumps(manifest))
        with self.assertRaisesRegex(RuntimeError, 'incomplete'):
            forumctl.verify_backup(self.root)

    def test_unexpected_database_image_is_rejected(self):
        manifest = self.backup()
        manifest['database_image'] = 'mariadb:latest'
        (self.root / 'manifest.json').write_text(json.dumps(manifest))
        with self.assertRaisesRegex(RuntimeError, 'pinned'):
            forumctl.verify_backup(self.root)

    def test_path_traversal_in_archive_is_rejected_without_writing_outside(self):
        archive = self.root / 'malicious.tar.gz'
        destination = self.root / 'restored'
        destination.mkdir()
        self.archive(archive, '../escaped.txt')
        with self.assertRaises(tarfile.FilterError):
            forumctl.extract_safe(archive, destination)
        self.assertFalse((self.root / 'escaped.txt').exists())

    def test_external_symlink_in_archive_is_rejected(self):
        archive = self.root / 'malicious.tar.gz'
        destination = self.root / 'restored'
        destination.mkdir()
        with tarfile.open(archive, 'w:gz') as output:
            member = tarfile.TarInfo('external')
            member.type = tarfile.SYMTYPE
            member.linkname = '../private'
            output.addfile(member)
        with self.assertRaises(tarfile.FilterError):
            forumctl.extract_safe(archive, destination)

    def test_missing_share_mount_prevents_operations(self):
        with patch.object(forumctl, 'SHARE', self.root):
            with self.assertRaisesRegex(RuntimeError, 'mounted filesystem'):
                forumctl.guard_storage()

    def test_backup_path_must_remain_inside_private_backup_directory(self):
        with patch.object(forumctl, 'ROOT', self.root):
            with self.assertRaisesRegex(RuntimeError, 'private backups'):
                forumctl.backup_path('../../outside')


if __name__ == '__main__':
    unittest.main()
