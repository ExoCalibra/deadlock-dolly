"""Current-value parsing and graphics diagnostic query/report contracts."""
import json
from pathlib import Path
import tempfile
import subprocess
import sys
import unittest
from unittest.mock import patch

from dolly import controller, graphics_profiles


def runtime_trace(module, values, response='', *, journal=True, query_error=False):
    """Simulated query boundary with actual private report-file bytes."""
    with tempfile.TemporaryDirectory(prefix='dolly-cvar-audit-') as directory:
        session = Path(directory)
        if journal:
            (session / module.JOURNAL).write_bytes(b'{}')
        calls = []
        record = {'profile': {'name': 'Audit fixture', 'values': values}}
        def query(command):
            calls.append(command)
            if query_error:
                raise RuntimeError('query unavailable')
            return response
        with patch.object(module, '_transaction', return_value=(record, None, None, None)) as transaction:
            try:
                result = module.audit_runtime(session, query)
                error = None
            except Exception as exc:
                result, error = None, {'type': type(exc).__name__, 'message': str(exc)}
            checked = transaction.call_count
        path = session / 'graphics-runtime.json'
        return {'query': calls, 'transaction_calls': checked, 'report': result, 'error': error,
                'bytes': path.read_bytes().hex() if path.exists() else None}


class ConvarResponseTests(unittest.TestCase):
    def test_pure_import_does_not_load_runtime_orchestrators(self):
        result = subprocess.run([sys.executable, '-c',
            'import sys; from dolly.convar_response import read_cvar_value; '
            'assert read_cvar_value("value", "value = 3") == 3; '
            'assert not ({"dolly.controller", "dolly.launcher", '
            '"dolly.graphics_profiles", "dolly.session_cleanup"} & sys.modules.keys())'],
            capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_controller_exports_and_graphics_use_same_parser(self):
        from dolly import convar_response
        self.assertIs(controller.read_cvar_value, convar_response.read_cvar_value)
        self.assertIs(graphics_profiles.read_cvar_value, convar_response.read_cvar_value)
        self.assertEqual(controller.NUMBER, convar_response.NUMBER)

    def test_scalar_boolean_and_scientific_values(self):
        name = 'r_effects_bloom'
        for text, expected in (('r_effects_bloom = true', 1.0), ('R_EFFECTS_BLOOM: FALSE', 0.0),
                               ('[Console] "r_effects_bloom" = "-.25e+2" ( def. "99" )', -25.0),
                               ('r_effects_bloom=+3.', 3.0), ('r_effects_bloom: .5 // caption 4', .5)):
            with self.subTest(text=text):
                actual = controller.read_cvar_value(name, text)
                self.assertEqual(actual, expected)
                self.assertIs(type(actual), float)

    def test_missing_default_only_nonfinite_and_name_collisions(self):
        name = 'r_effects_bloom'
        for text in ('', 'Unknown command r_effects_bloom', '"r_effects_bloom" ( def. "1" )',
                     'r_effects_bloom = nan', 'r_effects_bloom = inf', 'r_effects_bloom = 1e999',
                     'other_r_effects_bloom = 1', 'r_effects_bloom_extra = 1', 'r_effects_bloom = trueish'):
            with self.subTest(text=text):
                with self.assertRaises(ValueError) as caught:
                    controller.read_cvar_value(name, text)
                self.assertIs(type(caught.exception), ValueError)
                self.assertEqual(str(caught.exception), f'Could not read the current value of {name}. Export diagnostics.')

    def test_first_valid_current_value_wins(self):
        text = 'r_effects_bloom = 1e999\nr_effects_bloom = false\nr_effects_bloom = true'
        self.assertEqual(controller.read_cvar_value('r_effects_bloom', text), 0.0)

    def test_exact_vector_and_caption_exclusion(self):
        name = 'r_dof_override_ranges'
        for text in ('r_dof_override_ranges = "-1 0 2e1 .5" (default "9 9 9 9")',
                     'r_dof_override_ranges: -1 0 20 .5 // 9 9 9 9',
                     'r_dof_override_ranges: -1 0 20 .5 [caption 9]'):
            with self.subTest(text=text):
                self.assertEqual(controller.read_cvar_value(name, text), (-1.0, 0.0, 20.0, .5))
        for raw in ('1 2 3', '1 2 3 4 5', '1 2 3 nan', '1 2 3 1e999', '"1 2 3 4',
                    'invalid (default 1 2 3 4)'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                controller.read_cvar_value(name, name + ' = ' + raw)

    def test_invalid_vector_line_does_not_hide_later_valid_readback(self):
        name = 'r_dof_override_ranges'
        self.assertEqual(controller.read_cvar_value(name, name + ' = 1 2 3\n' + name + ' = 4 5 6 7'),
                         (4.0, 5.0, 6.0, 7.0))

    def test_runtime_audit_preserves_query_order_and_report_bytes(self):
        values = {'setting.r_effects_bloom': 'true', 'setting.shaderquality': '2',
                  'setting.r_citadel_shadow_quality': '2'}
        trace = runtime_trace(graphics_profiles, values, 'r_effects_bloom = false')
        self.assertEqual(trace['query'], ['r_effects_bloom', 'r_citadel_shadow_quality'])
        self.assertEqual(trace['report']['mismatches'], ['r_effects_bloom'])
        self.assertEqual(trace['report']['unreadable'], ['r_citadel_shadow_quality'])
        self.assertEqual(trace['report']['file_only'], ['setting.shaderquality'])
        self.assertFalse(trace['report']['visual_verified'])
        self.assertEqual(bytes.fromhex(trace['bytes']), (json.dumps(trace['report'], indent=2) + '\n').encode('utf-8'))

    def test_runtime_audit_empty_absent_and_failed_query_boundaries(self):
        trace = runtime_trace(graphics_profiles, {'setting.shaderquality': '2'})
        self.assertEqual(trace['query'], [])
        self.assertEqual(trace['report']['observed'], {})
        absent = runtime_trace(graphics_profiles, {}, journal=False)
        self.assertEqual(absent['transaction_calls'], 0)
        self.assertIsNone(absent['bytes'])
        failed = runtime_trace(graphics_profiles, {'setting.r_effects_bloom': '1'}, query_error=True)
        self.assertEqual(failed['error'], {'type': 'RuntimeError', 'message': 'query unavailable'})
        self.assertIsNone(failed['bytes'])


if __name__ == '__main__':
    unittest.main()
