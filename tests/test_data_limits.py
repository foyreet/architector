"""Boundary checks and full-size CSV → Unix broker → Python → saved history."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import socket
import struct
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
import zipfile

import block_contracts as bc
import code_sandbox as broker
from data_limits import JSON_DATA_BYTES, PYTHON_MESSAGE_BYTES, STEP_RECORD_BYTES
import kaggle_data as kg
import local_operations as local
import ml_operations as ml
import pipeline_runner as pr
import python_blocks as pb
from test_csv_full import graph


@contextmanager
def socket_broker(root, execute):
    path = str(root / 'code.sock')
    with patch.object(broker, 'run', side_effect=execute), patch.dict(os.environ, {'ARCHITECT_CODE_SOCKET': path}):
        server = broker.Server(path, broker.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        try: yield
        finally: server.shutdown(); server.server_close(); thread.join()


class DataLimitTests(unittest.TestCase):
    def test_json_boundary_and_artifact_envelope_roundtrip(self):
        # A valid 16 MiB JSON value needs a larger persisted artifact envelope.
        value = 'x' * (JSON_DATA_BYTES - 2)
        self.assertIs(pb.validate_json(value), value)
        with self.assertRaises(bc.ContractError) as caught: pb.validate_json(value + 'x')
        self.assertEqual(caught.exception.status, 413)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            ref = ml.save(root, 'python_data', value)
            path = ml.artifact_dir(root) / (ref['id'] + '.json')
            self.assertGreater(path.stat().st_size, JSON_DATA_BYTES)
            self.assertEqual(ml.load(root, ref, 'python_data'), value)
            with path.open('ab') as output: output.write(b' ')
            with self.assertRaisesRegex(bc.ContractError, 'контрольная сумма'): ml.load(root, ref, 'python_data')

    def test_32_mib_protocol_boundary_both_directions(self):
        with tempfile.TemporaryDirectory(prefix='limits-') as folder:
            root = Path(folder); calls = []
            payload = {'code': 'def run(inputs, params): return {}', 'inputs': {'text': ''}, 'params': {}, 'timeout': 10}
            payload['inputs']['text'] = 'x' * (PYTHON_MESSAGE_BYTES - len(ml.encode(payload)))
            def execute(request):
                calls.append(len(request['inputs']['text']))
                return {'result': {'data': request['inputs']['text']}}
            with socket_broker(root, execute):
                result = pb.sandbox(payload)
                self.assertEqual(result['result']['data'], payload['inputs']['text'])
                payload['inputs']['text'] += 'x'
                with self.assertRaises(bc.ContractError) as caught: pb.sandbox(payload)
                self.assertEqual(caught.exception.status, 413)
                self.assertEqual(len(calls), 1)
                # Broker checks oversized framed requests before reading a body.
                with socket.socket(socket.AF_UNIX) as connection:
                    connection.settimeout(3); connection.connect(str(root / 'code.sock'))
                    connection.sendall(struct.pack('!I', PYTHON_MESSAGE_BYTES + 1))
                    size = struct.unpack('!I', pb.receive(connection, 4))[0]
                    self.assertIn('error', json.loads(pb.receive(connection, size)))
            # A response reaching the envelope boundary passes; one byte over fails.
            response = {'result': {'data': ''}}
            overhead = len(json.dumps(response, ensure_ascii=False, allow_nan=False).encode())
            response['result']['data'] = 'x' * (PYTHON_MESSAGE_BYTES - overhead)
            small = {'code': 'def run(inputs, params): return {}', 'inputs': {}, 'params': {}, 'timeout': 10}
            # Unix socket paths can be reused after server shutdown.
            (root / 'code.sock').unlink()
            with socket_broker(root, lambda _: response):
                self.assertEqual(len(pb.sandbox(small)['result']['data']), PYTHON_MESSAGE_BYTES - overhead)
                response['result']['data'] += 'x'
                with self.assertRaisesRegex(bc.ContractError, 'Sandbox response too large'): pb.sandbox(small)

    def test_near_limit_csv_pipeline_keeps_all_rows_and_reopens_large_step(self):
        headers = [f'column-{i}-'.ljust(200, 'k') for i in range(10)]
        cell = 'v' * 200
        row = dict.fromkeys(headers, cell)
        row_bytes = len(json.dumps(row, ensure_ascii=False, separators=(',', ':')).encode()) + 1
        count = (JSON_DATA_BYTES - 1) // row_bytes
        text = ','.join(headers) + '\n' + (','.join([cell] * 10) + '\n') * count
        self.assertLess(len(text.encode()), local.MAX_CSV_BYTES)
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
            self.assertLess(path.stat().st_size, STEP_RECORD_BYTES)
            restored = pr.PipelineRunner(Mock(), kg, Mock(), root).step(run['id'], 'python')
            self.assertEqual(len(restored['outputs']['rows']), count)
            self.assertEqual(restored['outputs']['rows'][-1], row)
            with self.assertRaises(bc.ContractError): bc.validate_value([row] * (count + 1), {'type': 'rows'})
            # One extra CSV row fails explicitly, without a partial successful result.
            with zipfile.ZipFile(archive, 'w') as output: output.writestr('train.csv', text + ','.join([cell] * 10) + '\n')
            block = bc.normalize_block(graph(source)['nodes'][0]['block'])
            with self.assertRaisesRegex(bc.ContractError, 'частичное чтение не выполняется'): local.read_csv(block, kg)


if __name__ == '__main__': unittest.main()

