"""Opt-in real Docker integration. Only disposable containers and temporary data."""
import os
from pathlib import Path
import sys
import tempfile
import threading
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import block_contracts as bc
import code_sandbox as broker
from data_limits import JSON_DATA_BYTES, PYTHON_MESSAGE_BYTES
import ml_operations as ml
import python_blocks as pb


def main():
    if os.environ.get('ARCHITECT_TEST_DOCKER') != '1':
        raise SystemExit('Set ARCHITECT_TEST_DOCKER=1 to run disposable Docker checks.')
    with tempfile.TemporaryDirectory(prefix='sandbox-limits-') as folder:
        root = Path(folder); path = str(root / 'code.sock')
        with broker.Server(path, broker.Handler) as server, patch.dict(os.environ, {'ARCHITECT_CODE_SOCKET': path}):
            thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
            try:
                for character in ('x', 'я'):
                    value = character * ((JSON_DATA_BYTES - 2) // len(character.encode()))
                    reference = ml.save(root, 'python_data', value)
                    block = bc.normalize_block({'kind':'python_code','version':1,'inputs':{'data':reference},
                        'settings':{'code':'def run(inputs, params):\n    return {"data": inputs["data"]}', 'timeout':30}})
                    result = pb.execute(block, root)
                    assert ml.load(root, result['outputs']['data'], 'python_data') == value
                    assert result['details']['runtime']['memory_mb'] == 512
                payload = {'code':'def run(inputs, params):\n    return {"report": {"bytes": len(inputs["a"]) + len(inputs["b"])}}',
                           'inputs':{'a':'x'*(15*1024*1024),'b':'y'*(15*1024*1024)},'params':{},'timeout':30}
                assert len(ml.encode(payload)) < PYTHON_MESSAGE_BYTES
                assert pb.sandbox(payload)['result']['report']['bytes'] == 30*1024*1024
                del payload
                # Exceed the container's own hard limit, never the host's budget.
                try:
                    pb.sandbox({'code':'def run(inputs, params):\n    return {"data": len(bytearray(600*1024*1024))}',
                                'inputs':{},'params':{},'timeout':30})
                    raise AssertionError('Container memory limit was not enforced')
                except bc.ContractError as error:
                    assert error.status == 422 and 'памяти' in str(error), error
                # A failed container must not poison subsequent runs.
                result = pb.sandbox({'code':'def run(inputs, params): return {"report": {"ok": True}}',
                                     'inputs':{},'params':{},'timeout':10})
                assert result['result']['report']['ok']
                print('PASS: real Docker, 16 MiB ASCII/Unicode data, 30 MiB request, 512 MiB memory isolation and recovery')
            finally: server.shutdown(); thread.join()


if __name__ == '__main__': main()

