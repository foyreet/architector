"""CSV reads every row, including old projects, and transports the full result."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import zipfile

import block_contracts as bc
import data_preview
import kaggle_data as kg
import local_operations
import ml_operations as ml
import pipeline_runner as pr


ROW_COUNT = 5203


def csv_text(count=ROW_COUNT):
    return 'value,label\n' + ''.join(f'{index},class{index % 2}\n' for index in range(count))


def graph(reference, settings=None):
    nodes = []
    for index, (identity, kind) in enumerate([('csv', 'csv'), ('python', 'python_code')]):
        nodes.append({'id': identity, 'typeId': 'type-' + kind, 'name': identity, 'description': '', 'x': index * 330, 'y': 80,
                      'block': {'kind': kind, 'version': 1,
                                'inputs': {'dataset': reference, 'file': 'train.csv'} if kind == 'csv' else {},
                                'settings': (settings or {}) if kind == 'csv' else {}}})
    return {'format': 'architect', 'version': 3, 'name': 'Все строки CSV', 'nodes': nodes,
            'types': [{'id': 'type-' + kind, 'name': kind, 'description': '', 'color': '#6366f1', 'block': {'kind': kind, 'version': 1}}
                      for kind in ['csv', 'python_code']],
            'edges': [{'id': 'rows', 'kind': 'data', 'from': 'csv', 'to': 'python', 'fromPort': 'rows', 'toPort': 'rows'}]}


class FullCSVTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='full-csv-')
        self.root = Path(self.temp.name)
        self.kg = patch.object(kg, 'ROOT', self.root); self.kg.start()
        self.local = ml.save(self.root, 'dataset', {'format': 'architect.uploaded-csv', 'name': 'train.csv', 'csv': csv_text()})
        self.remote = bc.artifact('dataset', 'kaggle', 'owner/data')
        self.path = kg.archive_path('owner/data'); self.path.parent.mkdir(parents=True, exist_ok=True)
        self.archive(csv_text())

    def tearDown(self):
        self.kg.stop(); self.temp.cleanup()

    def archive(self, text):
        with zipfile.ZipFile(self.path, 'w') as archive:
            archive.writestr('train.csv', text)

    def read(self, reference, settings=None):
        return bc.execute({'block': graph(reference, settings)['nodes'][0]['block']}, Mock(), kg, Mock())

    def test_default_and_legacy_limits_read_all_rows_from_both_sources(self):
        for source in [self.local, self.remote]:
            for settings in [{}, {'max_rows': 1}, {'max_rows': 100}, {'max_rows': 1000, 'row_index': ROW_COUNT - 1}]:
                with self.subTest(source=source['provider'], settings=settings):
                    result = self.read(source, settings)
                    rows = result['outputs']['rows']
                    self.assertEqual(len(rows), ROW_COUNT)
                    self.assertEqual(rows[-1]['value'], str(ROW_COUNT - 1))
                    self.assertEqual(result['outputs']['row'], rows[settings.get('row_index', 0)])
                    self.assertEqual(result['details']['row_count'], ROW_COUNT)
                    self.assertFalse(result['details']['truncated'])
                    self.assertEqual(bc.validate_value(rows, {'type': 'rows'}), rows)

    def test_invalid_tail_is_not_silently_ignored(self):
        self.archive(csv_text() + 'unexpected,extra,column\n')
        with self.assertRaisesRegex(bc.ContractError, 'Некорректная строка CSV'):
            self.read(self.remote, {'max_rows': 100})

    def test_selected_row_is_bounded_by_file_not_old_limit(self):
        with self.assertRaisesRegex(bc.ContractError, 'Выбранной строки нет'):
            self.read(self.local, {'row_index': ROW_COUNT})
        for index in [-1, True, 1.5]:
            with self.subTest(index=index), self.assertRaises(bc.ContractError):
                self.read(self.local, {'row_index': index})
        normalized = bc.normalize_block(graph(self.local, {'max_rows': 1, 'row_index': 5000})['nodes'][0]['block'])
        self.assertNotIn('max_rows', normalized['settings'])
        self.assertEqual(normalized['settings']['row_index'], 5000)

    def test_large_rows_are_accepted(self):
        rows = [{'value': 'x' * 32001} for _ in range(525)]
        self.assertIs(bc.validate_value(rows, {'type': 'rows'}), rows)

    def test_preview_paginates_full_file_beyond_old_page_cap(self):
        body = {'diagram': graph(self.local, {'max_rows': 1}), 'node_id': 'csv', 'page': 104}
        result = data_preview.preview(body, kg)
        self.assertEqual(result['profile']['rows'], ROW_COUNT)
        self.assertEqual(len(result['rows']), 3)
        self.assertEqual(result['rows'][-1]['value'], str(ROW_COUNT - 1))
        self.assertFalse(result['sources'][0]['truncated'])

    def test_pipeline_passes_every_row_to_python_and_persists_every_output(self):
        received = []
        def sandbox(payload):
            rows = payload['inputs']['rows']; received.append(rows)
            return {'result': {'rows': rows, 'report': {'row_count': len(rows)}}}
        runner = pr.PipelineRunner(Mock(), kg, Mock(), self.root)
        with patch('python_blocks.sandbox', side_effect=sandbox):
            record = runner.start({'diagram': graph(self.local, {'max_rows': 100, 'row_index': 5000})})
            runner.thread.join(10)
            self.assertFalse(runner.thread.is_alive())
        self.assertEqual(runner.get(record['id'])['status'], 'ready')
        self.assertEqual(len(received), 1)
        self.assertEqual(len(received[0]), ROW_COUNT)
        step = runner.step(record['id'], 'python')
        self.assertEqual(step['outputs']['rows'], received[0])
        self.assertEqual(step['outputs']['rows'][-1]['value'], str(ROW_COUNT - 1))
        self.assertEqual(step['outputs']['report']['row_count'], ROW_COUNT)


if __name__ == '__main__':
    unittest.main()

