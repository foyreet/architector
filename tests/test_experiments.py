from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
import uuid
from unittest.mock import Mock, patch

import block_contracts as bc
import experiments as ex
import huggingface_models as hf
import kaggle_data as kg
import pipeline_runner as pr
import project_store as ps
from test_projects import local_graph


class ExperimentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.runner = pr.PipelineRunner(Mock(), kg, hf, self.root)

    def record(self, kind='ml_evaluate', status='ready'):
        run_id = str(uuid.uuid4())
        record = {'id': run_id, 'name': 'Experiment', 'created_at': '2026-10-24T10:00:00+00:00',
                  'started_at': '2026-10-24T10:00:01+00:00', 'finished_at': '2026-10-24T10:00:04+00:00',
                  'status': status, 'order': ['node'], 'events': [],
                  'diagram': {'nodes': [{'id': 'node', 'name': 'Model', 'block': bc.normalize_block({'kind': kind, 'version': 1})}]},
                  'nodes': {'node': {'name': 'Model', 'status': 'ready'}}}
        self.runner.save(record)
        return record

    def step(self, record, details, outputs=None):
        self.runner.write(self.runner.run_path(record['id'], 'steps/0000.json'),
                          {'details': details, 'outputs': outputs or {}, 'block': record['diagram']['nodes'][0]['block']})

    def test_metrics_zero_duration_and_missing_files(self):
        record = self.record()
        self.step(record, {'accuracy': 0, 'macro_f1': 0.25, 'test_rows': 30, 'predictions': ['private']})
        result = ex.comparison(self.runner, record['id'])
        self.assertEqual(result['duration'], 3)
        self.assertEqual(result['metrics']['node/accuracy']['value'], 0)
        self.assertNotIn('predictions', str(result))
        self.runner.run_path(record['id'], 'steps/0000.json').unlink()
        result = ex.comparison(self.runner, record['id'])
        self.assertFalse(result['metrics'])
        self.assertTrue(result['warnings'])

    def test_custom_numeric_metrics_and_code_fingerprint(self):
        record = self.record('python_code')
        self.step(record, {'logs': 'private log', 'runtime': {'image': 'sha256:test'}},
                  {'report': {'cv': {'mean_accuracy': .9, 'std': .02}, 'message': 'text', 'flag': True, 'scores': [.8, .9]}})
        result = ex.comparison(self.runner, record['id'])
        self.assertEqual(set(result['metrics']), {'node/cv / mean_accuracy', 'node/cv / std'})
        self.assertIn('node/code_sha256', result['parameters'])
        self.assertNotIn('node/code', result['parameters'])
        self.assertNotIn('private log', str(result))
        self.assertEqual(result['versions']['node/runtime / image']['value'], 'sha256:test')

    def test_notes_persistence_conflicts_and_active_run(self):
        record = self.record(status='running'); self.runner.current = deepcopy(record)
        body = {'run_id': record['id'], 'experiment': {'title': 'Baseline', 'hypothesis': 'Test', 'tags': ['base', 'base']}}
        result = ex.request(self.runner, body, 'experiment')
        self.assertEqual(result['experiment']['revision'], 1)
        self.assertEqual(result['experiment']['tags'], ['base'])
        self.assertEqual(self.runner.current['experiment'], result['experiment'])
        self.runner.save(self.runner.current)
        self.assertEqual(self.runner.read(record['id'])['experiment']['title'], 'Baseline')
        with self.assertRaises(bc.ContractError) as error:
            ex.request(self.runner, body, 'experiment')
        self.assertEqual(error.exception.status, 409)
        with self.assertRaises(bc.ContractError): ex.notes({'tags': ['x' * 33]})

    def test_selection_and_storage_isolation(self):
        record = self.record()
        for ids in ([], [record['id']] * 2, [str(uuid.uuid4()) for _ in range(7)], ['../run']):
            with self.assertRaises(bc.ContractError): ex.request(self.runner, {'run_ids': ids}, 'compare')
        other = pr.PipelineRunner(Mock(), kg, hf, self.root / 'other-account')
        with self.assertRaises(bc.ContractError) as error:
            ex.request(other, {'run_ids': [record['id']]}, 'compare')
        self.assertEqual(error.exception.status, 404)

    def test_notes_roundtrip_with_project_history(self):
        store = ps.ProjectStore(self.root)
        project = store.save({'diagram': local_graph(), 'name': 'Demo', 'description': ''}, create=True)
        runner = pr.PipelineRunner(Mock(), kg, hf, self.root, store.folder(project['project']['id']) + '/runs')
        run = runner.start({'diagram': local_graph()}); runner.thread.join(5)
        self.assertEqual(runner.get(run['id'])['status'], 'ready')
        ex.request(runner, {'run_id': run['id'], 'experiment': {'title': 'Baseline', 'conclusion': 'Works'}}, 'experiment')
        package = store.export(project['project']['id'], include_history=True)
        imported = store.import_package({'package': package})
        exported = store.export(imported['project']['id'], include_history=True)
        self.assertEqual(exported['history'][0]['record']['experiment']['title'], 'Baseline')


if __name__ == '__main__': unittest.main()

