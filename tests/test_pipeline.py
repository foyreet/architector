import hashlib
import json
from pathlib import Path
import tempfile
import threading
import unittest
import uuid
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import zipfile

import block_contracts as bc
import huggingface_models as hf
import kaggle_data as kg
import pipeline_runner as pr
from test_server import serve

ROOT = Path(__file__).resolve().parents[1]


def block(identifier, kind, inputs=None, settings=None):
    return {'id': identifier, 'name': identifier, 'block': {'kind': kind, 'version': 1, 'inputs': inputs or {}, 'settings': settings or {}}}


def edge(source, output, target, entry):
    return {'id': source + '-' + target, 'from': source, 'fromPort': output, 'to': target, 'toPort': entry, 'kind': 'data'}


def scenario():
    return {'format': 'architect', 'version': 3, 'name': 'CSV pipeline', 'nodes': [
        block('answer', 'openrouter', settings={'model': 'test/model'}),
        block('prompt', 'template', settings={'template': 'Classify {{text}} ({{label}})'}),
        block('csv', 'csv', {'file': 'train.csv'}, {'row_index': 1}),
        block('dataset', 'kaggle', {'source': 'owner/data/versions/2'})],
        'edges': [edge('dataset', 'dataset', 'csv', 'dataset'), edge('csv', 'row', 'prompt', 'row'), edge('prompt', 'text', 'answer', 'text')]}


class PipelineTests(unittest.TestCase):
    def setUp(self):
        (ROOT / 'workspace/tmp').mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.patches = [patch.object(kg, 'ROOT', self.root), patch.object(hf, 'ROOT', self.root), patch.dict(kg.JOBS, {}, clear=True),
                        patch.dict(hf.JOBS, {}, clear=True), patch.dict(pr.os.environ, {}, clear=True)]
        for item in self.patches:
            item.start()
        path = kg.archive_path('owner/data/versions/2')
        path.parent.mkdir(parents=True, exist_ok=True)
        self.csv = b'text,label\nfirst,one\nsecond,two\n'
        with zipfile.ZipFile(path, 'w') as archive:
            archive.writestr('train.csv', self.csv)
        self.completion = Mock(return_value={'text': 'Answer!', 'model': 'test/resolved', 'usage': {'total_tokens': 11}})
        self.runner = pr.PipelineRunner(self.completion, kg, hf, self.root)

    def tearDown(self):
        if self.runner.thread:
            self.runner.thread.join(5)
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def start(self, diagram=None, **extra):
        return self.runner.start({'diagram': diagram or scenario(), 'secrets': {'openrouter': 'test-secret-key'}, **extra})

    def finish(self, run):
        self.runner.thread.join(5)
        self.assertFalse(self.runner.thread.is_alive())
        return self.runner.get(run['id'])

    def test_editor_snapshot_preserves_layout_without_transport_secrets(self):
        graph = scenario()
        graph['types'] = []
        graph['api_key'] = 'not-part-of-the-diagram'
        for index, node in enumerate(graph['nodes']):
            kind = node['block']['kind']
            graph['types'].append({'id': 'type_' + kind, 'name': kind, 'description': '',
                                   'color': '#5368e8', 'block': {'kind': kind, 'version': 1}})
            node.update(typeId='type_' + kind, description='Сохранённое описание',
                        x=-120 + index * 300, y=250, width=320, height=220)
        run = self.finish(self.start(graph))
        saved = self.runner.get(run['id'])['editor_diagram']
        self.assertEqual(saved['nodes'][0]['x'], -120)
        self.assertEqual(saved['nodes'][0]['width'], 320)
        self.assertEqual(saved['edges'], graph['edges'])
        self.assertNotIn('api_key', saved)
        self.assertNotIn('test-secret-key', json.dumps(saved))
        self.assertNotIn('x', run['diagram']['nodes'][0])
        graph['nodes'][0]['x'] = 999
        self.assertEqual(self.runner.get(run['id'])['editor_diagram']['nodes'][0]['x'], -120)

    def test_full_chain_persists_values_versions_and_restarts(self):
        run = self.finish(self.start())
        self.assertEqual(run['status'], 'ready', run)
        self.assertEqual(run['order'], ['dataset', 'csv', 'prompt', 'answer'])
        self.completion.assert_called_once()
        self.assertEqual(self.completion.call_args.args[0]['prompt'], 'Classify second (two)')
        self.assertEqual(self.completion.call_args.args[0]['api_key'], 'test-secret-key')
        dataset = self.runner.step(run['id'], 'dataset')
        self.assertEqual(dataset['versions']['dataset_version'], '2')
        self.assertEqual(len(dataset['versions']['archive_sha256']), 64)
        csv = self.runner.step(run['id'], 'csv')
        self.assertEqual(csv['details']['sha256'], hashlib.sha256(self.csv).hexdigest())
        self.assertEqual(csv['outputs']['row'], {'text': 'second', 'label': 'two'})
        answer = self.runner.step(run['id'], 'answer')
        self.assertEqual(answer['versions']['response_model'], 'test/resolved')
        self.assertEqual(answer['outputs'], {'text': 'Answer!'})
        restored = pr.PipelineRunner(self.completion, kg, hf, self.root)
        self.assertEqual(restored.get(run['id']), run)
        self.assertEqual(restored.history()['runs'][0]['id'], run['id'])
        for path in (self.root / 'workspace/runs').rglob('*.json'):
            self.assertNotIn('test-secret-key', path.read_text())

    def test_validation_rejects_cycles_missing_and_bad_ports_before_calls(self):
        cases = []
        value = scenario(); value['edges'].append(edge('answer', 'text', 'dataset', 'source')); cases.append(value)
        value = scenario(); value['edges'].pop(); cases.append(value)
        value = scenario(); value['edges'][1]['fromPort'] = 'rows'; cases.append(value)
        value = scenario(); duplicate = dict(value['edges'][0], id='duplicate'); value['edges'].append(duplicate); cases.append(value)
        value = scenario(); value['nodes'].append(block('local', 'local_model')); cases.append(value)
        value = scenario(); value['nodes'][0]['block']['settings']['model'] = ''; cases.append(value)
        value = scenario(); value['nodes'][2]['block']['settings'] = {'row_index': -1}; cases.append(value)
        for diagram in cases:
            with self.subTest(diagram=diagram), self.assertRaises(bc.ContractError):
                self.start(diagram)
        self.completion.assert_not_called()
        self.assertEqual(self.runner.history()['runs'], [])

    def test_missing_key_and_invalid_provider_inputs_prevent_work(self):
        with self.assertRaises(bc.ContractError):
            self.start(secrets={})
        value = scenario(); value['nodes'][-1]['block']['inputs']['source'] = 'https://evil.test/file'
        with self.assertRaises(kg.KaggleError):
            self.start(value)
        self.assertEqual(self.runner.history()['runs'], [])

    def test_failure_skips_downstream_and_does_not_retry(self):
        diagram = scenario(); diagram['nodes'][1]['block']['settings']['template'] = '{{missing}}'
        run = self.finish(self.start(diagram))
        self.assertEqual(run['status'], 'error')
        self.assertEqual(run['nodes']['prompt']['status'], 'error')
        self.assertEqual(run['nodes']['answer']['status'], 'skipped')
        self.completion.assert_not_called()
        self.assertIn('missing', self.runner.step(run['id'], 'prompt')['error'])
        self.completion.side_effect = serve.ApiError('Provider failed', 502)
        run = self.finish(self.start())
        self.completion.assert_called_once()
        self.assertEqual(run['status'], 'error')
        self.assertIn('Provider failed', run['error'])

    def test_idempotent_start_and_single_active_run(self):
        entered, release = threading.Event(), threading.Event()
        def completion(_):
            entered.set(); release.wait(3)
            return {'text': 'done'}
        self.completion.side_effect = completion
        run_id = str(uuid.uuid4())
        first = self.start(run_id=run_id)
        self.assertTrue(entered.wait(3))
        try:
            self.assertEqual(self.start(run_id=run_id)['id'], first['id'])
            with self.assertRaises(bc.ContractError) as error:
                self.start()
            self.assertEqual(error.exception.status, 409)
            diagram = scenario(); diagram['name'] = 'different'
            with self.assertRaises(bc.ContractError):
                self.start(diagram, run_id=run_id)
        finally:
            release.set()
        self.assertEqual(self.finish(first)['status'], 'ready')
        self.start(run_id=run_id)
        self.completion.assert_called_once()

    def test_cancel_retains_current_response_and_skips_next(self):
        entered, release = threading.Event(), threading.Event()
        def completion(_):
            entered.set(); release.wait(3)
            return {'text': 'paid result'}
        self.completion.side_effect = completion
        diagram = scenario()
        diagram['nodes'].append(block('second', 'openrouter', settings={'model': 'test/model'}))
        diagram['edges'].append(edge('answer', 'text', 'second', 'text'))
        run = self.start(diagram)
        self.assertTrue(entered.wait(3))
        self.runner.cancel(run['id']); release.set()
        run = self.finish(run)
        self.assertEqual(run['status'], 'cancelled')
        self.assertEqual(run['nodes']['second']['status'], 'cancelled')
        self.assertEqual(self.runner.step(run['id'], 'answer')['outputs']['text'], 'paid result')
        self.completion.assert_called_once()

    def test_interrupted_run_is_not_resumed(self):
        run = self.finish(self.start())
        run['status'] = 'running'; run['nodes']['answer']['status'] = 'running'
        self.runner.save(run)
        restored = pr.PipelineRunner(self.completion, kg, hf, self.root)
        self.assertEqual(restored.get(run['id'])['status'], 'error')
        self.assertEqual(restored.get(run['id'])['nodes']['answer']['status'], 'error')
        self.completion.assert_called_once()

    def test_storage_failure_happens_before_provider_call(self):
        with patch.object(self.runner, 'save', side_effect=bc.ContractError('disk full', 507)):
            with self.assertRaises(bc.ContractError):
                self.start()
        self.completion.assert_not_called()

    def test_history_rejects_traversal_and_symlinks(self):
        with self.assertRaises(bc.ContractError):
            self.runner.get('../file')
        run_id = str(uuid.uuid4())
        (self.root / 'workspace/runs' / run_id).symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(bc.ContractError):
            self.start(run_id=run_id)

    def test_huggingface_pins_revision_and_records_checksums(self):
        diagram = {'format': 'architect', 'version': 3, 'nodes': [block('model', 'huggingface', {'repo': 'owner/model'}, {'revision': 'main', 'files': ['config.json']})], 'edges': []}
        artifact = bc.artifact('model', 'huggingface', 'owner/model', 'b' * 40)
        with patch.object(hf, 'model_info', return_value={'commit': 'b' * 40}), patch.object(hf, 'request', return_value={'status': 'ready', 'artifact': artifact}) as download, patch.object(hf, 'read_manifest', return_value={'files': [{'name': 'config.json', 'digest': 'a' * 64, 'algorithm': 'sha256'}]}):
            run = self.finish(self.start(diagram))
        self.assertEqual(run['status'], 'ready', run)
        self.assertEqual(download.call_args.args[0]['commit'], 'b' * 40)
        step = self.runner.step(run['id'], 'model')
        self.assertEqual(step['block']['settings']['commit'], 'b' * 40)
        self.assertEqual(step['versions']['files'][0]['digest'], 'a' * 64)

    def test_local_operations_handle_delimiter_bom_and_unsafe_templates(self):
        value = bc.normalize_block(block('prompt', 'template', {'row': {'text': '{{other}}'}}, {'template': 'Text: {{ text }}'})['block'], required=True)
        self.assertEqual(bc.execute({'block': value}, self.completion, kg, hf)['outputs']['text'], 'Text: {{other}}')
        value['settings']['template'] = '{{text'
        with self.assertRaises(bc.ContractError):
            bc.execute({'block': value}, self.completion, kg, hf)
        path = kg.archive_path('owner/data/versions/2')
        with zipfile.ZipFile(path, 'w') as archive:
            archive.writestr('train.csv', '\ufefftext;label\n"hello; world";one\nsecond;two\n')
        value = bc.normalize_block(block('csv', 'csv', {'dataset': bc.artifact('dataset', 'kaggle', 'owner/data/versions/2'), 'file': 'train.csv'}, {'delimiter': ';', 'max_rows': 1})['block'], required=True)
        result = bc.execute({'block': value}, self.completion, kg, hf)
        self.assertEqual(result['outputs']['row']['text'], 'hello; world')
        self.assertFalse(result['details']['truncated'])
        self.assertEqual(len(result['outputs']['rows']), 2)
        with zipfile.ZipFile(path, 'w') as archive:
            archive.writestr('train.csv', 'text,text\na,b\n')
        with self.assertRaises(bc.ContractError):
            bc.execute({'block': dict(value, settings=dict(value['settings'], delimiter=','))}, self.completion, kg, hf)

    def test_http_routes_and_origin_guard(self):
        server = serve.ThreadingHTTPServer(('127.0.0.1', 0), serve.Handler)
        server.pipeline_runner = self.runner
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        url = f'http://127.0.0.1:{server.server_port}'
        def request(action, body, origin=None):
            headers = {'Content-Type': 'application/json', 'X-Architect-Request': '1'}
            if origin:
                headers['Origin'] = origin
            return urlopen(Request(url + '/api/pipelines/' + action, data=json.dumps(body).encode(), headers=headers))
        try:
            with self.assertRaises(HTTPError) as error:
                request('start', {'diagram': scenario()}, 'https://evil.test')
            self.assertEqual(error.exception.code, 403); error.exception.close()
            with request('start', {'diagram': scenario(), 'secrets': {'openrouter': 'test-secret-key'}}) as response:
                run = self.finish(json.load(response))
            with request('step', {'run_id': run['id'], 'node_id': 'answer'}) as response:
                self.assertEqual(json.load(response)['outputs']['text'], 'Answer!')
            with request('runs', {}) as response:
                self.assertEqual(len(json.load(response)['runs']), 1)
        finally:
            server.shutdown(); server.server_close(); thread.join()

