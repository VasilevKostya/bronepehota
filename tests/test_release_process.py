"""Release integrity, approval boundaries, and coordinated source/site rollback."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import shutil
import sys
import uuid
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import deploy_main
import release_bundle as bundle
import release_main
import release_workflow

SOURCE = '1' * 40
OLD_BUILD = 'a' * 16
NEW_BUILD = 'b' * 16


def site(root, build=NEW_BUILD, source=SOURCE):
    files = {'index.html': '<title>Правила — Бронепехота</title>',
             '404.html': 'missing', 'assets/catalog-large.json': '{}'}
    hashes = {name: hashlib.sha256(text.encode()).hexdigest() for name, text in files.items()}
    files['precache.json'] = json.dumps({'build': build, 'version': '0.3',
                                        'files': list(hashes), 'hashes': hashes})
    files['build.json'] = json.dumps({'build': build, 'version': '0.3',
                                     'files': len(hashes), 'source_commit': source})
    files['sw.js'] = 'const BUILD=' + repr(build)
    files['.nojekyll'] = ''
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')


class TemporaryCase(unittest.TestCase):
    def setUp(self):
        (ROOT / 'tmp').mkdir(exist_ok=True)
        parent = (ROOT / 'tmp').resolve()
        self.root = parent / ('release-test-' + uuid.uuid4().hex)
        self.root.mkdir()
        def cleanup():
            if self.root.is_symlink() or self.root.resolve().parent != parent:
                raise RuntimeError('Unsafe test cleanup target')
            shutil.rmtree(self.root)
        self.addCleanup(cleanup)


class BundleTests(TemporaryCase):
    def setUp(self):
        super().setUp()
        self.dist = self.root / 'dist'
        site(self.dist)
        self.folder = self.root / 'candidate'
        self.meta = bundle.pack(self.dist, self.folder, SOURCE)

    def test_same_approved_bytes_extract_for_either_target(self):
        for name in ['pages', 'main']:
            target = self.root / name
            bundle.check(self.folder, source=SOURCE, sha256=self.meta['sha256'], extract=target)
            self.assertEqual(deploy_main.inventory(target), deploy_main.inventory(self.dist))

    def test_wrong_source_build_or_digest_cannot_be_applied(self):
        for options in [{'source': '2' * 40}, {'build': OLD_BUILD}, {'sha256': '0' * 64}]:
            with self.subTest(options=options), self.assertRaises(ValueError):
                bundle.check(self.folder, **options)

    def test_corrupt_archive_is_rejected_before_extraction(self):
        archive = self.folder / 'site.zip'
        archive.write_bytes(archive.read_bytes() + b'corrupt')
        with self.assertRaisesRegex(ValueError, 'archive changed'):
            bundle.check(self.folder, extract=self.root / 'rejected')
        self.assertFalse((self.root / 'rejected').exists())

    def test_wrong_manifest_hash_is_rejected_even_if_outer_archive_matches(self):
        manifest = json.loads((self.dist / 'precache.json').read_text())
        manifest['hashes']['index.html'] = '0' * 64
        (self.dist / 'precache.json').write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, 'Manifest hash differs'):
            bundle.pack(self.dist, self.root / 'bad-candidate', SOURCE)

    def test_traversal_hidden_files_and_windows_drives_are_rejected(self):
        for path in ['../outside', '/outside', 'C:/outside', '.git/config', 'assets/../../key', '.', 'a\\b']:
            with self.subTest(path=path), self.assertRaises(ValueError):
                bundle.safe_name(path)

    def test_legacy_build_without_source_cannot_be_promoted(self):
        metadata = json.loads((self.dist / 'build.json').read_text())
        del metadata['source_commit']
        (self.dist / 'build.json').write_text(json.dumps(metadata))
        with self.assertRaisesRegex(ValueError, 'requested source'):
            bundle.pack(self.dist, self.root / 'legacy', SOURCE)

    def test_server_acknowledgement_is_not_part_of_the_shared_bundle(self):
        (self.dist / 'deployment-status.json').write_text('{"state":"old"}')
        metadata = bundle.pack(self.dist, self.root / 'with-status', SOURCE)
        self.assertNotIn('deployment-status.json', metadata['files'])


class ApprovalTests(unittest.TestCase):
    def test_stale_or_different_server_readiness_blocks_pages_before_publication(self):
        ready = {'state': 'waiting', 'source_commit': SOURCE, 'build': NEW_BUILD,
                 'sha256': '0' * 64, 'heartbeat_at': 1000, 'expires_at': 2000}
        for change in [{'heartbeat_at': 1}, {'expires_at': 1100}, {'sha256': '1' * 64}]:
            with self.subTest(change=change), patch.object(release_workflow, 'check', return_value={'build': NEW_BUILD}), \
                 patch.object(release_workflow, 'read', return_value=json.dumps({**ready, **change}).encode()), \
                 patch.object(release_workflow.time, 'time', return_value=1000):
                with self.assertRaisesRegex(ValueError, 'one-shot SSH command'):
                    release_workflow.require_server_ready('candidate', SOURCE, '0' * 64)

    def test_only_successful_push_from_main_and_exact_commit_is_eligible(self):
        valid = {'event': 'push', 'head_branch': 'main', 'head_sha': SOURCE, 'workflow_id': 9,
                 'status': 'completed', 'conclusion': 'success',
                 'head_repository': {'full_name': release_main.REPOSITORY}}
        for change in [{'event': 'pull_request'}, {'head_sha': '2' * 40},
                       {'conclusion': 'failure'}, {'head_branch': 'other'}, {'workflow_id': 8}]:
            with self.subTest(change=change), patch.object(release_workflow, 'api',
                    side_effect=[{**valid, **change}, {'id': 9}]), self.assertRaises(ValueError):
                release_workflow.validate_run('123', SOURCE)
        with patch.object(release_workflow, 'api', side_effect=[valid, {'id': 9}, {'status': 'ahead'}]):
            release_workflow.validate_run('123', SOURCE)
        with patch.object(release_workflow, 'api', side_effect=[{**valid, 'event': 'workflow_dispatch'},
                         {'id': 9}, {'status': 'identical'}]):
            release_workflow.validate_run('123', SOURCE)

    def test_unconfirmed_apply_stops_before_network_or_server_writes(self):
        args = ['release_main.py', 'apply', '--source', SOURCE, '--build', NEW_BUILD, '--sha256', '0' * 64]
        with patch.object(sys, 'argv', args), patch.object(release_main, 'approved_release') as network:
            with self.assertRaisesRegex(ValueError, 'explicit --confirm'):
                release_main.main()
            network.assert_not_called()

    def test_release_by_another_actor_is_not_accepted(self):
        meta = {'schema': 1, 'source_commit': SOURCE, 'build': NEW_BUILD, 'sha256': '0' * 64,
                'archive': 'site.zip', 'bytes': 1, 'files': {'index.html': '0' * 64}}
        prefix = 'https://github.com/' + release_main.REPOSITORY + '/releases/download/' + release_main.release_tag(SOURCE, NEW_BUILD) + '/'
        release = {'draft': False, 'prerelease': False, 'target_commitish': SOURCE,
                   'assets': [{'name': name, 'browser_download_url': prefix + name}
                              for name in ['site.zip', 'release.json', 'approval.json']]}
        approval = {'source_commit': SOURCE, 'build': NEW_BUILD, 'sha256': '0' * 64, 'actor': 'someone-else'}
        with patch.object(release_main, 'get_json', side_effect=[release, meta, approval]):
            with self.assertRaisesRegex(ValueError, 'Approval does not match'):
                release_main.approved_release(SOURCE, NEW_BUILD, '0' * 64)


class ControllerRollbackTests(TemporaryCase):
    def test_server_acknowledges_only_after_finalization(self):
        state = self.root / 'deployments' / NEW_BUILD / 'state.json'
        state.parent.mkdir(parents=True)
        meta = {'source_commit': SOURCE, 'build': NEW_BUILD, 'sha256': '0' * 64}
        data = {**meta, 'archive_sha256': meta['sha256'], 'phase': 'published'}
        state.write_text(json.dumps(data))
        live = self.root / 'live'
        live.mkdir()
        def finalize(operation, *_):
            self.assertEqual(operation, 'finalize')
            self.assertFalse((live / 'deployment-status.json').exists())
            state.write_text(json.dumps({**data, 'phase': 'verified'}))
        with patch.object(deploy_main, 'STORAGE', self.root), patch.object(deploy_main, 'LIVE', live), \
             patch.object(release_main.subprocess, 'run'), patch.object(deploy_main, 'git'), \
             patch.object(release_main, 'wait_for_pages'), \
             patch.object(release_main, 'verify'), patch.object(release_main, 'run_deployer', side_effect=finalize):
            release_main.apply(meta, self.root / 'candidate')
        acknowledgement = json.loads((live / 'deployment-status.json').read_text())
        self.assertEqual(acknowledgement, {**meta, 'state': 'verified'})

    def test_workflow_does_not_accept_matching_build_without_server_acknowledgement(self):
        metadata = {'build': NEW_BUILD}
        with patch.object(release_workflow, 'check', return_value=metadata), \
             patch.object(release_workflow, 'read', return_value=json.dumps({'build': NEW_BUILD,
                           'source_commit': SOURCE}).encode()), \
             patch.object(release_workflow.time, 'monotonic', side_effect=[0, 2]), \
             patch.object(release_workflow, 'verify') as verify:
            with self.assertRaisesRegex(ValueError, 'incomplete'):
                release_workflow.wait_for_main(self.root, SOURCE, '0' * 64, 1)
            verify.assert_not_called()

    def test_failed_public_verification_rolls_back_and_cannot_finalize(self):
        state = self.root / 'deployments' / NEW_BUILD / 'state.json'
        state.parent.mkdir(parents=True)
        meta = {'source_commit': SOURCE, 'build': NEW_BUILD, 'sha256': '0' * 64}
        state.write_text(json.dumps({**meta, 'archive_sha256': meta['sha256'], 'phase': 'published'}))
        with patch.object(deploy_main, 'STORAGE', self.root), patch.object(release_main.subprocess, 'run'), \
             patch.object(release_main, 'wait_for_pages'), \
             patch.object(deploy_main, 'git'), patch.object(release_main, 'run_deployer') as deploy, \
             patch.object(release_main, 'verify', side_effect=[None, RuntimeError('unavailable')]):
            with self.assertRaisesRegex(RuntimeError, 'unavailable'):
                release_main.apply(meta, self.root / 'candidate')
            self.assertEqual([call.args[0] for call in deploy.call_args_list], ['rollback'])


@unittest.skipUnless(sys.platform == 'linux', 'Atomic directory exchange requires Linux')
class AtomicSourceTests(TemporaryCase):
    def setUp(self):
        super().setUp()
        self.project = self.root / 'project'
        self.project.mkdir()
        def git(*args):
            return subprocess.check_output(['git', *args], cwd=self.project, text=True).strip()
        self.git = git
        git('init', '-b', 'main')
        git('config', 'user.name', 'Release test')
        git('config', 'user.email', 'release-test@example.invalid')
        (self.project / '.gitignore').write_text('dist/\n.deploy-*/\n')
        (self.project / 'source.txt').write_text('old')
        git('add', '.')
        git('commit', '-m', 'old')
        self.old = git('rev-parse', 'HEAD')
        (self.project / 'source.txt').write_text('new')
        git('commit', '-am', 'new')
        self.new = git('rev-parse', 'HEAD')
        git('reset', '--keep', self.old)
        self.live = self.project / 'dist'
        self.stage = self.project / '.deploy-test'
        self.live.mkdir(); self.stage.mkdir()
        (self.live / 'marker').write_text('old')
        (self.stage / 'marker').write_text('new')
        self.addCleanup(patch.stopall)
        patch.object(deploy_main, 'PROJECT', self.project).start()
        patch.object(deploy_main, 'LIVE', self.live).start()

    def test_publication_and_rollback_switch_source_and_site_together(self):
        deploy_main.switch_release(self.stage, self.old, self.new)
        self.assertEqual(self.git('rev-parse', 'HEAD'), self.new)
        self.assertEqual((self.live / 'marker').read_text(), 'new')
        deploy_main.switch_release(self.stage, self.new, self.old, rollback=True)
        self.assertEqual(self.git('rev-parse', 'HEAD'), self.old)
        self.assertEqual((self.live / 'marker').read_text(), 'old')

    def test_failed_source_update_returns_original_site(self):
        real_git = deploy_main.git
        def failure(*args):
            if args[0] == 'merge':
                raise RuntimeError('source update failed')
            return real_git(*args)
        with patch.object(deploy_main, 'git', side_effect=failure):
            with self.assertRaisesRegex(RuntimeError, 'source update failed'):
                deploy_main.switch_release(self.stage, self.old, self.new)
        self.assertEqual((self.live / 'marker').read_text(), 'old')
        self.assertEqual(self.git('rev-parse', 'HEAD'), self.old)

    def test_dirty_source_is_preserved_and_blocks_publication(self):
        (self.project / 'source.txt').write_text('user edit')
        with self.assertRaisesRegex(RuntimeError, 'local changes'):
            deploy_main.switch_release(self.stage, self.old, self.new)
        self.assertEqual((self.live / 'marker').read_text(), 'old')
        self.assertEqual((self.project / 'source.txt').read_text(), 'user edit')

    def test_full_bundle_drops_obsolete_files_but_keeps_them_in_backup(self):
        site(self.live, OLD_BUILD, self.old)
        (self.live / 'obsolete.html').write_text('old route')
        (self.stage / 'marker').unlink()
        self.stage.rmdir()
        storage = self.root / 'storage'
        candidate_site = self.root / 'candidate-site'
        site(candidate_site, NEW_BUILD, self.new)
        candidate = storage / 'releases' / 'candidate'
        metadata = bundle.pack(candidate_site, candidate, self.new)
        folder = storage / 'deployments' / NEW_BUILD
        previous_umask = os.umask(0o027)
        try:
            with patch.object(deploy_main, 'STORAGE', storage):
                deploy_main.prepare(candidate / 'site.zip', OLD_BUILD, NEW_BUILD, folder,
                                    self.stage, source=self.new, full=True)
        finally:
            os.umask(previous_umask)
        self.assertEqual(deploy_main.inventory(self.stage), metadata['files'])
        self.assertEqual((self.stage / 'assets').stat().st_mode & 0o777, 0o755)
        self.assertEqual((self.live / 'obsolete.html').read_text(), 'old route')
        self.assertEqual((folder / 'restore-check/dist/obsolete.html').read_text(), 'old route')

    def test_legacy_switch_without_source_metadata_remains_usable(self):
        deploy_main.switch_release(self.stage)
        self.assertEqual((self.live / 'marker').read_text(), 'new')
        self.assertEqual(self.git('rev-parse', 'HEAD'), self.old)

    def test_readiness_heartbeat_is_not_a_product_change(self):
        before = deploy_main.inventory(self.live)
        (self.live / 'deployment-prepared.json').write_text('{"state":"prepared"}')
        self.assertEqual(deploy_main.inventory(self.live), before)


if __name__ == '__main__':
    unittest.main()
