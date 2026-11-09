import json
import os
import threading
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import block_contracts as bc
from test_server import serve


class ContractTests(unittest.TestCase):
    def test_catalog_and_normalization(self):
        self.assertEqual(set(bc.CONTRACTS), {'note', 'kaggle', 'csv', 'template', 'openrouter', 'huggingface', 'local_model',
                                                 'ml_prepare', 'ml_split', 'ml_train', 'gpu_train', 'ml_evaluate', 'ml_save', 'python_code'})
        for contract in bc.CONTRACTS.values():
            value = bc.normalize_block({'kind': contract['kind'], 'version': 1})
            self.assertEqual(value['kind'], contract['kind'])
            for section in ('inputs', 'outputs'):
                self.assertTrue(all(port['type'] in bc.CATALOG['types'] for port in contract[section]))
            self.assertIsInstance(contract['operation']['available'], bool)
        value = bc.normalize_block({'kind': 'openrouter', 'version': 1, 'operation': 'evil',
                                   'inputs': {'text': 'hello', 'api_key': 'secret'},
                                   'settings': {'model': 'test/model', 'api_key': 'secret', 'command': 'evil'}})
        self.assertEqual(value['inputs'], {'text': 'hello'})
        self.assertEqual(value['settings']['max_tokens'], 1024)
        self.assertNotIn('secret', json.dumps(value))
        self.assertNotIn('evil', json.dumps(value))

    def test_invalid_versions_fields_and_required_inputs(self):
        cases = [None, {'kind': 'unknown', 'version': 1}, {'kind': 'kaggle', 'version': 2},
                 {'kind': 'kaggle', 'version': True}, {'kind': 'openrouter', 'version': 1, 'inputs': []},
                 {'kind': 'openrouter', 'version': 1, 'settings': {'max_tokens': True}},
                 {'kind': 'openrouter', 'version': 1, 'settings': {'temperature': float('nan')}},
                 {'kind': 'csv', 'version': 1, 'settings': {'row_index': -1}},
                 {'kind': 'huggingface', 'version': 1, 'settings': {'commit': 'main'}},
                 {'kind': 'template', 'version': 1, 'inputs': {'row': {'nested': {'bad': 1}}}}]
        for value in cases:
            with self.subTest(value=value), self.assertRaises(bc.ContractError):
                bc.normalize_block(value)
        for kind in ('kaggle', 'csv', 'template', 'openrouter', 'huggingface', 'local_model'):
            with self.subTest(kind=kind), self.assertRaises(bc.ContractError):
                bc.normalize_block({'kind': kind, 'version': 1}, required=True)

    def test_artifacts_are_typed_references_without_paths(self):
        dataset = bc.artifact('dataset', 'kaggle', 'owner/data')
        model = bc.artifact('model', 'huggingface', 'owner/model', 'a' * 40)
        self.assertEqual(bc.normalize_block({'kind': 'csv', 'version': 1, 'inputs': {'dataset': dataset}})['inputs']['dataset'], dataset)
        self.assertEqual(bc.normalize_block({'kind': 'local_model', 'version': 1, 'inputs': {'model': model}})['inputs']['model'], model)
        for value in ('/etc/passwd', model, dict(dataset, path='/etc/passwd'), dict(dataset, id='../file'), dict(dataset, provider='arbitrary')):
            with self.subTest(value=value), self.assertRaises(bc.ContractError):
                bc.validate_artifact(value, 'dataset')

    def test_common_execution_is_allowlisted(self):
        completion, kaggle, hf = Mock(), Mock(), Mock()
        completion.return_value = {'text': 'response', 'usage': {}}
        block = {'kind': 'openrouter', 'version': 1, 'inputs': {'text': 'hello'}, 'settings': {'model': 'test/model'}}
        result = bc.execute({'block': block, 'secrets': {'api_key': 'secret'}}, completion, kaggle, hf)
        self.assertEqual(result['outputs'], {'text': 'response'})
        self.assertEqual(completion.call_args.args[0]['prompt'], 'hello')
        self.assertEqual(completion.call_args.args[0]['api_key'], 'secret')
        self.assertNotIn('secret', json.dumps(result))
        block = {'kind': 'kaggle', 'version': 1, 'inputs': {'source': 'owner/data'}}
        kaggle.request.return_value = {'status': 'downloading'}
        self.assertEqual(bc.execute({'block': block}, completion, kaggle, hf)['outputs'], {})
        ref = bc.artifact('dataset', 'kaggle', 'owner/data')
        kaggle.request.return_value = {'status': 'ready', 'artifact': ref}
        self.assertEqual(bc.execute({'block': block}, completion, kaggle, hf, poll=True)['outputs'], {'dataset': ref})
        kaggle.request.assert_called_with({'dataset': 'owner/data'}, 'files')
        block = {'kind': 'huggingface', 'version': 1, 'inputs': {'repo': 'owner/model'}, 'settings': {'commit': 'b' * 40, 'files': ['config.json']}}
        ref = bc.artifact('model', 'huggingface', 'owner/model', 'b' * 40)
        hf.request.return_value = {'status': 'ready', 'artifact': ref}
        self.assertEqual(bc.execute({'block': block}, completion, kaggle, hf)['outputs'], {'model': ref})
        hf.request.assert_called_with({'repo': 'owner/model', 'commit': 'b' * 40, 'files': ['config.json'], 'token': ''}, 'download')

    def test_unimplemented_operations_are_explicit(self):
        completion, kaggle, hf = Mock(), Mock(), Mock()
        for block in (
            {'kind': 'local_model', 'version': 1, 'inputs': {'model': bc.artifact('model', 'huggingface', 'owner/model', 'a' * 40), 'text': 'hello'}},
        ):
            with self.assertRaises(bc.ContractError) as caught:
                bc.execute({'block': block}, completion, kaggle, hf)
            self.assertEqual(caught.exception.status, 501)
        completion.assert_not_called(); kaggle.request.assert_not_called(); hf.request.assert_not_called()


class ContractHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = serve.ThreadingHTTPServer(('127.0.0.1', 0), serve.Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f'http://127.0.0.1:{cls.server.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.thread.join()

    def test_registry_and_origin_guards(self):
        with urlopen(self.url + '/api/blocks/contracts') as response:
            self.assertEqual(json.load(response), bc.CATALOG)
        for path in ('/api/blocks/execute', '/api/blocks/result'):
            with patch.object(bc, 'execute') as operation:
                request = Request(self.url + path, data=b'{}', headers={'Content-Type': 'application/json',
                    'X-Architect-Request': '1', 'Origin': 'https://evil.test'})
                with self.assertRaises(HTTPError) as caught:
                    urlopen(request)
                self.assertEqual(caught.exception.code, 403); caught.exception.close()
                operation.assert_not_called()

    def test_typed_api_returns_outputs(self):
        body = {'block': {'kind': 'openrouter', 'version': 1, 'inputs': {'text': 'hello'}, 'settings': {'model': 'test/model'}},
                'secrets': {'api_key': 'test-only'}}
        request = Request(self.url + '/api/blocks/execute', data=json.dumps(body).encode(),
                          headers={'Content-Type': 'application/json', 'X-Architect-Request': '1'})
        with patch.object(serve, 'provider_request', return_value={'choices': [{'message': {'content': 'answer'}, 'finish_reason': 'stop'}]}):
            with urlopen(request) as response:
                data = json.load(response)
        self.assertEqual(data['status'], 'ready')
        self.assertEqual(data['outputs'], {'text': 'answer'})
        self.assertNotIn('test-only', json.dumps(data))

