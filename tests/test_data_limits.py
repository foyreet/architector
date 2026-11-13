"""Boundary checks and full-size CSV → Unix broker → Python → saved history."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
import zipfile

import block_contracts as bc
import code_sandbox as broker
import kaggle_data as kg
import ml_operations as ml
import pipeline_runner as pr
import python_blocks as pb
from test_csv_full import graph

MIB = 1024 * 1024


@contextmanager
def socket_broker(root, execute):
    path = str(root / 'code.sock')
    with patch.object(broker, 'run', side_effect=execute), patch.dict(os.environ, {'ARCHITECT_CODE_SOCKET': path}):
        server = broker.Server(path, broker.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        try: yield
        finally: server.shutdown(); server.server_close(); thread.join()


class DataLimitTests(unittest.TestCase):
    def test_python_split_passes_full_dataset_to_next_block(self):
        rows = [{str(column): i for column in range(7)} for i in range(64000)]
        def block(code, inputs):
            return bc.normalize_block({'kind': 'python_code', 'version': 1,
                                       'settings': {'code': code}, 'inputs': inputs}, required=True)
        split = "def run(inputs, params):\n    r = inputs['rows']\n    return {'data': [r[:38400], r[38400:51200], r[51200:]]}"
        summarize = "def run(inputs, params):\n    return {'report': [len(part) for part in inputs['data']]}"
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'ARCHITECT_CODE_SOCKET': ''}):
            result = pb.execute(block(split, {'rows': rows}), Path(folder))
            result = pb.execute(block(summarize, {'data': result['outputs']['data']}), Path(folder))
            self.assertEqual(result['outputs']['report'], [38400, 12800, 12800])

    def test_json_boundary_and_artifact_envelope_roundtrip(self):
        value = 'x' * (33 * MIB)
        self.assertIs(pb.validate_json(value), value)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            ref = ml.save(root, 'python_data', value)
            path = ml.artifact_dir(root) / (ref['id'] + '.json')
            self.assertGreater(path.stat().st_size, 32 * MIB)
            self.assertEqual(ml.load(root, ref, 'python_data'), value)
            with path.open('ab') as output: output.write(b' ')
            with self.assertRaisesRegex(bc.ContractError, 'контрольная сумма'): ml.load(root, ref, 'python_data')

    def test_32_mib_protocol_boundary_both_directions(self):
        with tempfile.TemporaryDirectory(prefix='limits-') as folder:
            root = Path(folder)
            payload = {'code': 'def run(inputs, params): return {}', 'inputs': {'text': ''}, 'params': {}, 'timeout': 10}
            payload['inputs']['text'] = 'x' * (33 * MIB - len(ml.encode(payload)))
            def execute(request):
                return {'result': {'data': request['inputs']['text']}}
            with socket_broker(root, execute):
                result = pb.sandbox(payload)
                self.assertEqual(result['result']['data'], payload['inputs']['text'])

    def test_large_csv_pipeline_keeps_all_rows_and_reopens_large_step(self):
        headers = [f'column-{i}-'.ljust(200, 'k') for i in range(10)]
        cell = 'v' * 200
        row = dict.fromkeys(headers, cell)
        row_bytes = len(json.dumps(row, ensure_ascii=False, separators=(',', ':')).encode()) + 1
        count = (34 * MIB) // row_bytes
        text = ','.join(headers) + '\n' + (','.join([cell] * 10) + '\n') * count
        self.assertGreater(len(text.encode()), 8 * MIB)
        self.assertGreater(count * row_bytes, 15 * 1024 * 1024)
        with tempfile.TemporaryDirectory(prefix='limits-') as folder, patch.object(kg, 'ROOT', Path(folder)):
            root = Path(folder); archive = kg.archive_path('owner/data'); archive.parent.mkdir(parents=True)
            with zipfile.ZipFile(archive, 'w') as output: output.writestr('train.csv', text)
            source = bc.artifact('dataset', 'kaggle', 'owner/data')
            received = []
            def execute(payload):
                rows = payload['inputs']['rows']; received.append(len(rows))
                return {'result': {'rows': rows, 'report': {'note': 'x' * 32000, 'count': len(rows)}}}
            runner = pr.PipelineRunner(Mock(), kg, Mock(), root)
            with socket_broker(root, execute):
                run = runner.start({'diagram': graph(source)})
                runner.thread.join(40)
                self.assertFalse(runner.thread.is_alive())
                completed = runner.get(run['id'])
                self.assertEqual(completed['status'], 'ready', completed.get('error'))
            self.assertEqual(received, [count])
            path = runner.run_path(run['id'], 'steps/0001.json')
            self.assertGreater(path.stat().st_size, 32 * 1024 * 1024)
            self.assertGreater(path.stat().st_size, 64 * MIB)
            restored = pr.PipelineRunner(Mock(), kg, Mock(), root).step(run['id'], 'python')
            self.assertEqual(len(restored['outputs']['rows']), count)
            self.assertEqual(restored['outputs']['rows'][-1], row)


if __name__ == '__main__': unittest.main()
