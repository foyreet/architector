from copy import deepcopy
import json
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import block_contracts as bc
import codex_chat as chat
import codex_edits as edits
import project_store as ps
import subgraphs


def empty():
    return {'format': 'architect', 'version': 3, 'name': 'Тест', 'types': [], 'nodes': [], 'edges': [], 'definitions': []}


class EditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = ps.ProjectStore(Path(self.temp.name))
        self.draft = edits.Draft(empty())

    def tearDown(self):
        self.temp.cleanup()

    def add(self):
        self.draft.call('diagram_add_blocks', {'blocks': [
            {'id': 'kg', 'kind': 'kaggle', 'inputs': {'source': 'uciml/iris'}},
            {'id': 'csv', 'kind': 'csv', 'inputs': {'file': 'Iris.csv'}}]})

    def test_catalog_types_defaults_and_private_custom_contracts(self):
        catalog = self.draft.call('diagram_catalog', {'kinds': ['ml_train', 'python_code']})['blocks']
        self.assertEqual(catalog[0]['outputs'][0]['type'], 'trained_model')
        self.assertIn('code', [s['id'] for s in catalog[1]['settings']])
        with self.assertRaises(bc.ContractError): self.draft.call('diagram_catalog', {'kinds': ['invented']})
        self.add()
        packed = subgraphs.pack({'diagram': self.draft.graph, 'selected': ['csv'], 'name': 'Мой CSV'})
        pinned = edits.Draft(packed['diagram'])
        kind = packed['contracts'][0]['kind']
        contract = pinned.call('diagram_catalog', {'kinds': [kind]})['blocks'][0]
        self.assertEqual(contract['label'], 'Мой CSV')
        pinned.call('diagram_add_blocks', {'blocks': [{'id': 'reused', 'kind': kind}]})
        self.assertEqual(pinned.graph['definitions'], packed['diagram']['definitions'])

    def test_new_catalog_prefers_python_and_keeps_existing_kinds(self):
        hidden = {'note', 'template', 'ml_prepare', 'ml_split', 'ml_train', 'ml_evaluate', 'ml_save'}
        kinds = {block['kind'] for block in self.draft.call('diagram_catalog', {})['blocks']}
        self.assertFalse(kinds & hidden)
        self.assertTrue({'python_code', 'csv', 'kaggle', 'openrouter', 'huggingface', 'gpu_train'} <= kinds)
        self.draft.call('diagram_add_blocks', {'blocks': [{'id': 'legacy', 'kind': 'template'}]})
        kinds = {block['kind'] for block in self.draft.call('diagram_catalog', {})['blocks']}
        self.assertIn('template', kinds)
        self.assertNotIn('note', kinds)
        self.draft.call('diagram_update_blocks', {'blocks': [{'id': 'legacy', 'settings': {'template': 'Hello {{text}}'}}]})
        self.assertEqual(self.draft.graph['nodes'][0]['block']['kind'], 'template')

    def test_edits_are_staged_atomic_and_typed(self):
        self.add()
        before = deepcopy(self.draft.graph)
        for name, arguments in [
            ('diagram_update_blocks', {'blocks': [{'id': 'csv', 'settings': {'row_index': 20}}, {'id': 'absent', 'name': 'bad'}]}),
            ('diagram_update_blocks', {'blocks': [{'id': 'csv', 'settings': {'invented': 1}}]}),
            ('diagram_connect', {'connections': [{'from': 'kg', 'to': 'csv', 'from_port': 'bad', 'to_port': 'dataset'}]}),
            ('diagram_add_blocks', {'blocks': [{'id': 'csv', 'kind': 'csv'}]}),
            ('shell', {'command': 'touch /tmp/unwanted'}),
        ]:
            with self.assertRaises(bc.ContractError): self.draft.call(name, arguments)
            self.assertEqual(self.draft.graph, before)
        self.draft.call('diagram_update_blocks', {'blocks': [{'id': 'csv', 'settings': {'row_index': 20}}]})
        self.assertEqual(self.draft.graph['nodes'][1]['block']['inputs']['file'], 'Iris.csv')
        self.assertEqual(self.draft.graph['nodes'][0]['x'], before['nodes'][0]['x'])
        self.draft.call('diagram_connect', {'connections': [{'from': 'kg', 'to': 'csv', 'from_port': 'dataset', 'to_port': 'dataset'}]})
        self.assertTrue(self.draft.call('diagram_check', {})['ready'])
        self.assertEqual(self.draft.base, edits.Draft(empty()).graph)
        self.assertFalse(self.store.path('projects').exists())
        self.draft.call('diagram_remove', {'node_ids': ['kg']})
        self.assertEqual(self.draft.graph['edges'], [])
        self.assertFalse(self.draft.check()['ready'])

    def test_proposal_is_private_bound_to_base_and_project_and_never_saves(self):
        initial = self.store.save({'diagram': empty(), 'name': 'Тест'}, create=True)
        pid = initial['project']['id']
        self.add()
        proposal = self.draft.proposal(self.store, pid)
        body = {'project_id': pid, 'proposal_id': proposal['id'], 'diagram': empty()}
        prepared = edits.prepare(self.store, body)
        self.assertEqual(len(prepared['diagram']['nodes']), 2)
        self.assertEqual(self.store.get(pid)['diagram']['nodes'], [])
        self.assertEqual(self.store.get(pid)['project']['revision'], initial['project']['revision'])
        for altered in [dict(body, project_id=None), dict(body, diagram=dict(empty(), name='Ручная правка')),
                        dict(body, proposal_id='../../secret')]:
            with self.assertRaises(bc.ContractError): edits.prepare(self.store, altered)
        other = ps.ProjectStore(self.store.root / 'other')
        with self.assertRaises(bc.ContractError): edits.prepare(other, body)
        self.store.save({'project_id': pid, 'revision': initial['project']['revision'],
                         'diagram': dict(empty(), name='Новая редакция'), 'name': 'Новая редакция'})
        with self.assertRaises(bc.ContractError): edits.prepare(self.store, body)

    def test_worker_persists_proposal_without_modifying_project_and_optout_has_no_tools(self):
        calls = []
        def answer(prompt, draft=None):
            calls.append(draft)
            if draft:
                self.assertEqual(draft.call('diagram_runs', {})['runs'], [])
                draft.call('diagram_add_blocks', {'blocks': [{'id': 'train', 'kind': 'ml_train', 'settings': {'n_estimators': 200}}]})
            return 'Подготовлено'
        connection = SimpleNamespace(status=lambda: {'connected': True}, answer=answer)
        user = {'id': 'test'}
        with patch.object(chat, 'client', return_value=connection):
            for include in [True, False]:
                chat.request(self.store.root, user, {'message': 'Создай обучение', 'diagram': empty(), 'include_context': include}, 'send')
                for _ in range(200):
                    record = chat.request(self.store.root, user, {}, 'history')
                    if not record['pending']: break
                    time.sleep(.01)
                self.assertFalse(record['error'])
                self.assertEqual('proposal' in record['messages'][-1], include)
        self.assertIsNotNone(calls[0]); self.assertIsNone(calls[1])
        self.assertFalse(self.store.path('projects').exists())


if __name__ == '__main__': unittest.main()

