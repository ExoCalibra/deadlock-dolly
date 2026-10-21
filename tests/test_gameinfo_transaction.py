"""Gameinfo restoration states, failed writes and compatibility boundaries."""
import hashlib
import json
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from dolly import launcher
from test_launcher import fake_game


def transaction_trace(module, scenario):
    """Run restoration on a fake installation; never start or inspect a process."""
    with tempfile.TemporaryDirectory(prefix='dolly-transaction-') as directory:
        root = Path(directory)
        paths = fake_game(root / 'installation')
        session = root / 'logs' / 'fixture'
        session.mkdir(parents=True)
        original = paths.gameinfo.read_bytes()
        mounted = b'patched gameinfo\r\n'
        backup = session / 'original.gameinfo.gi'
        backup.write_bytes(original)
        paths.gameinfo.write_bytes(mounted)
        record = {'owner': 'Deadlock Dolly', 'session_dir': str(session),
                  'original_gameinfo': str(paths.gameinfo),
                  'overlay_dir': str(paths.game_dir / 'citadel_dolly_fixture'),
                  'backup_name': backup.name, 'original_sha256': hashlib.sha256(original).hexdigest(),
                  'patched_sha256': hashlib.sha256(mounted).hexdigest(),
                  'original_mode': stat.S_IMODE(paths.gameinfo.stat().st_mode), 'config_state': 'mounted'}
        if scenario == 'prepared':
            record['config_state'] = 'prepared'
            paths.gameinfo.write_bytes(original)
        elif scenario == 'already_original':
            paths.gameinfo.write_bytes(original)
        elif scenario == 'restored_missing_backup':
            record['config_state'] = 'restored'
            backup.unlink()
        elif scenario == 'retry_conflict':
            record['config_state'] = 'conflict'
        elif scenario in ('external_edit', 'conflict_journal_failure'):
            paths.gameinfo.write_bytes(b'newer external bytes')
        elif scenario == 'missing_backup':
            backup.unlink()
        elif scenario == 'tampered_backup':
            backup.write_bytes(b'tampered')
        elif scenario == 'missing_target':
            paths.gameinfo.unlink()
        elif scenario == 'wrong_owner':
            record['owner'] = 'Other'
        elif scenario == 'wrong_session':
            record['session_dir'] = str(root / 'different')
        elif scenario == 'wrong_target':
            record['original_gameinfo'] = str(paths.gameinfo.with_name('other.gi'))
        elif scenario == 'wrong_overlay':
            record['overlay_dir'] = str(root / 'citadel_dolly_other')
        elif scenario == 'wrong_backup_name':
            record['backup_name'] = 'another.gi'
        elif scenario == 'wrong_hash':
            record['patched_sha256'] = 'invalid'
        journal = session / 'session.json'
        module._save_record(session, record)
        if scenario == 'truncated_journal':
            journal.write_bytes(b'{"owner":')
        elif scenario == 'duplicate_owner':
            journal.write_text('{"owner":"Other",' + journal.read_text(encoding='utf-8')[1:], encoding='utf-8')
        events = []
        real_write = module._atomic_write
        def normalize(value):
            return value.replace(json.dumps(str(root))[1:-1], '<ROOT>').replace(str(root), '<ROOT>')
        def content(data):
            return normalize(data.decode('utf-8')).encode('utf-8').hex()
        def write(path, data, mode=None):
            events.append({'path': path.relative_to(root).as_posix(), 'bytes': content(data), 'mode': mode})
            if scenario == 'target_write_failure' and path == paths.gameinfo:
                raise OSError('target locked')
            if scenario == 'partial_target_write' and path == paths.gameinfo:
                path.write_bytes(data[:5])
                raise OSError('partial external writer')
            if scenario in ('journal_write_failure', 'conflict_journal_failure') and path == journal:
                raise OSError('journal locked')
            real_write(path, data, mode)
        error = None
        result = None
        with patch.object(module, '_atomic_write', side_effect=write), patch.object(module.time, 'strftime', return_value='2000-01-01T00:00:00Z'):
            try:
                result = module._restore_record(session)
                if scenario == 'repeat':
                    result = module._restore_record(session)
            except Exception as exc:
                error = {'type': type(exc).__name__, 'message': normalize(str(exc)),
                         'cause': type(exc.__cause__).__name__ if exc.__cause__ else None}
        def snapshot(path):
            return None if not path.exists() else content(path.read_bytes())
        return {'result': result, 'error': error, 'writes': events,
                'target': snapshot(paths.gameinfo), 'backup': snapshot(backup),
                'journal': snapshot(journal), 'original': content(original), 'mounted': content(mounted)}


class GameinfoTransactionTests(unittest.TestCase):
    def test_transaction_import_does_not_load_orchestrators(self):
        result = subprocess.run([sys.executable, '-c',
            'import sys; import dolly.gameinfo_transaction; '
            'assert not ({"dolly.launcher", "dolly.controller", '
            '"dolly.graphics_profiles", "dolly.session_cleanup"} & sys.modules.keys())'],
            capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_restores_then_journals_and_repeat_is_noop(self):
        trace = transaction_trace(launcher, 'repeat')
        self.assertTrue(trace['result'])
        self.assertEqual(trace['target'], trace['original'])
        self.assertEqual([entry['path'] for entry in trace['writes']],
                         ['steamapps/common/installation/game/citadel/gameinfo.gi', 'logs/fixture/session.json'])

    def test_prepared_and_already_original_only_update_journal(self):
        for scenario in ('prepared', 'already_original'):
            with self.subTest(scenario=scenario):
                trace = transaction_trace(launcher, scenario)
                self.assertEqual(trace['target'], trace['original'])
                self.assertEqual([entry['path'] for entry in trace['writes']], ['logs/fixture/session.json'])

    def test_restored_state_does_not_require_backup_or_rewrite_target(self):
        trace = transaction_trace(launcher, 'restored_missing_backup')
        self.assertTrue(trace['result'])
        self.assertEqual(trace['target'], trace['mounted'])
        self.assertIsNone(trace['backup'])
        self.assertEqual(trace['writes'], [])

    def test_external_edit_is_preserved_and_conflict_journaled(self):
        trace = transaction_trace(launcher, 'external_edit')
        self.assertEqual(bytes.fromhex(trace['target']), b'newer external bytes')
        self.assertEqual(trace['error']['type'], 'LaunchError')
        self.assertEqual(json.loads(bytes.fromhex(trace['journal']))['config_state'], 'conflict')
        self.assertEqual(trace['backup'], trace['original'])

    def test_bad_journal_or_backup_produces_no_writes(self):
        for scenario in ('missing_backup', 'tampered_backup', 'missing_target', 'wrong_owner',
                         'wrong_session', 'wrong_target', 'wrong_overlay', 'wrong_backup_name',
                         'wrong_hash', 'truncated_journal'):
            with self.subTest(scenario=scenario):
                trace = transaction_trace(launcher, scenario)
                self.assertEqual(trace['error']['type'], 'LaunchError')
                self.assertEqual(trace['writes'], [])

    def test_write_failure_retains_pending_journal_and_backup(self):
        for scenario in ('target_write_failure', 'partial_target_write', 'journal_write_failure'):
            with self.subTest(scenario=scenario):
                trace = transaction_trace(launcher, scenario)
                self.assertEqual(trace['error']['type'], 'LaunchError')
                self.assertEqual(trace['error']['cause'], 'OSError')
                self.assertEqual(json.loads(bytes.fromhex(trace['journal']))['config_state'], 'mounted')
                self.assertEqual(trace['backup'], trace['original'])
                expected = {'target_write_failure': trace['mounted'],
                            'partial_target_write': bytes.fromhex(trace['original'])[:5].hex(),
                            'journal_write_failure': trace['original']}[scenario]
                self.assertEqual(trace['target'], expected)

    def test_validator_patch_is_used_and_its_launch_error_stays_unwrapped(self):
        with tempfile.TemporaryDirectory() as directory:
            session = Path(directory)
            record = {'owner': 'Deadlock Dolly', 'session_dir': str(session),
                      'original_gameinfo': str(session / 'gameinfo.gi')}
            launcher._save_record(session, record)
            error = launcher.LaunchError('installation rejected')
            with patch.object(launcher, 'validate_game', side_effect=error) as validate:
                with self.assertRaises(launcher.LaunchError) as caught:
                    launcher._load_record(session)
            validate.assert_called_once_with(session)
            self.assertIs(caught.exception, error)

    def test_restore_resolves_load_and_save_patch_points(self):
        with tempfile.TemporaryDirectory() as directory:
            session = Path(directory)
            with patch.object(launcher, '_load_record', return_value={'config_state': 'restored'}) as load:
                self.assertTrue(launcher._restore_record(session))
            load.assert_called_once_with(session)
            target = session / 'gameinfo.gi'
            target.write_bytes(b'original')
            (session / 'original.gameinfo.gi').write_bytes(b'original')
            record = {'original_gameinfo': str(target), 'backup_name': 'original.gameinfo.gi',
                      'original_sha256': hashlib.sha256(b'original').hexdigest()}
            with patch.object(launcher, '_load_record', return_value=record), patch.object(launcher, '_save_record') as save:
                self.assertTrue(launcher._restore_record(session))
            save.assert_called_once_with(session, record)
            self.assertEqual(record['config_state'], 'restored')


if __name__ == '__main__':
    unittest.main()
