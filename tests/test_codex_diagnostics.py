from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
import uuid

import block_contracts as bc
import codex_edits
import project_store as ps
from test_codex_edits import empty


class DiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = ps.ProjectStore(Path(self.temp.name))
        self.pid = self.store.save({'diagram': empty(), 'name': 'Тест'}, create=True)['project']['id']
        self.draft = codex_edits.Draft(empty(), self.store, self.pid)
        self.run_id = str(uuid.uuid4())
        self.base = self.store.folder(self.pid) + '/runs/' + self.run_id
        self.record = {'id': self.run_id, 'name': 'Тест', 'status': 'running',
                       'created_at': '2026-01-01', 'order': ['csv'],
                       'nodes': {'csv': {'name': 'CSV', 'status': 'error', 'error': 'Нет train.csv'}},
                       'events': [{'node_id': 'csv', 'message': 'Нет train.csv', 'time': '2026-01-01'}],
                       'diagram': {'private_input': 'not-for-diagnostics'}}
        self.store.write(self.base + '/run.json', self.record)
        self.store.write(self.base + '/steps/0000.json', {
            'node_id': 'csv', 'status': 'error', 'error': 'Нет train.csv',
            'details': {'logs': 'token=private-token\nBearer private-bearer\n' + 'x' * 20000},
            'outputs': {'rows': [{'private': 'not-for-diagnostics'}]}, 'block': {'private': 'not-for-diagnostics'}})

    def tearDown(self):
        self.temp.cleanup()

    def test_read_only_bounded_diagnostics_without_inputs_outputs_or_credentials(self):
        before = deepcopy(self.draft.graph)
        listing = self.draft.call('diagram_runs', {})
        self.assertEqual(listing['runs'][0]['id'], self.run_id)
        result = self.draft.call('diagram_run_logs', {'run_id': self.run_id, 'node_id': 'csv'})
        serialized = json.dumps(result, ensure_ascii=False)
        self.assertIn('Нет train.csv', serialized)
        for forbidden in ('private-token', 'private-bearer', 'not-for-diagnostics'):
            self.assertNotIn(forbidden, serialized)
        self.assertLess(len(result['step']['logs']), 12100)
        self.assertEqual(self.draft.graph, before)
        self.assertEqual(self.store.read(self.base + '/run.json'), self.record)

    def test_scope_path_and_symlink_guards(self):
        other_pid = self.store.save({'diagram': empty(), 'name': 'Другой'}, create=True)['project']['id']
        other_store = ps.ProjectStore(self.store.root / 'another-account')
        for draft in (codex_edits.Draft(empty(), self.store, other_pid),
                      codex_edits.Draft(empty(), self.store), codex_edits.Draft(empty(), other_store)):
            self.assertEqual(draft.call('diagram_runs', {})['runs'], [])
            with self.assertRaises(bc.ContractError):
                draft.call('diagram_run_logs', {'run_id': self.run_id})
        for args in ({'run_id': '../../server-access'}, {'run_id': self.run_id, 'node_id': '../csv'},
                     {'run_id': self.run_id, 'node_id': 'unknown'}, {'run_id': self.run_id, 'path': '/etc/passwd'}):
            with self.assertRaises(bc.ContractError):
                self.draft.call('diagram_run_logs', args)
        path = self.store.path(self.base + '/steps/0000.json')
        path.rename(path.with_suffix('.saved'))
        path.symlink_to(path.with_suffix('.saved'))
        with self.assertRaises(bc.ContractError):
            self.draft.call('diagram_run_logs', {'run_id': self.run_id, 'node_id': 'csv'})

    def test_missing_step_and_event_limits(self):
        self.store.path(self.base + '/steps/0000.json').unlink()
        self.record['events'] *= 40
        self.store.write(self.base + '/run.json', self.record)
        result = self.draft.call('diagram_run_logs', {'run_id': self.run_id, 'node_id': 'csv'})
        self.assertEqual(len(result['events']), 30)
        self.assertTrue(result['events_truncated'])
        self.assertIn('ещё не сохранён', result['note'])


if __name__ == '__main__':
    unittest.main()

