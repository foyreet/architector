from copy import deepcopy
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace

import block_contracts as bc
import huggingface_models as hf
import kaggle_data as kg
import pipeline_runner as pr
import project_store as ps
import subgraphs as sg
from test_pipeline import scenario

ROOT = Path(__file__).resolve().parents[1]


def full_graph():
    graph = scenario(); graph['types'] = []
    for i, node in enumerate(graph['nodes']):
        node.update(typeId='type-' + node['id'], description='', x=i*300, y=0)
        graph['types'].append({'id': node['typeId'], 'name': node['name'], 'description': '', 'color': '#6366f1',
                              'block': {'kind': node['block']['kind'], 'version': 1}})
    return graph


def local_graph():
    graph = full_graph()
    graph['nodes'] = [n for n in graph['nodes'] if n['id'] == 'prompt']
    graph['nodes'][0]['block']['inputs'] = {'row': {'text': 'hello', 'label': 'test'}}
    graph['types'] = [t for t in graph['types'] if t['id'] == 'type-prompt']
    graph['edges'] = []
    return graph


class ProjectTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = ps.ProjectStore(self.root)
        self.patches = [patch.object(ps, 'ROOT', self.root), patch.object(pr, 'ROOT', self.root)]
        for p in self.patches: p.start()
        self.server = SimpleNamespace()
        self.completion = Mock(return_value={'text': 'answer'})

    def tearDown(self):
        for runner in getattr(self.server, 'project_runners', {}).values():
            if runner.thread: runner.thread.join(5)
        for p in self.patches: p.stop()
        self.temp.cleanup()

    def create(self, graph=None):
        return self.store.save({'diagram': graph or local_graph(), 'name': 'Мой проект', 'description': '# Описание'}, create=True)

    def request(self, action, body):
        return pr.request(self.server, body, action, self.completion, kg, hf)

    def test_project_roundtrip_revision_and_secret_stripping(self):
        graph = local_graph(); graph['nodes'][0]['block']['settings']['api_key'] = 'secret-test'
        created = self.create(graph)
        self.assertEqual(self.store.get(created['project']['id']), created)
        metadata = created['project']
        with self.assertRaises(bc.ContractError) as error:
            self.store.save({'project_id': metadata['id'], 'revision': 0, 'diagram': graph})
        self.assertEqual(error.exception.status, 409)
        updated = self.store.save({'project_id': metadata['id'], 'revision': 1, 'diagram': graph, 'description': 'new'})
        self.assertEqual(updated['project']['revision'], 2)
        self.assertEqual(self.store.get(metadata['id'])['description'], 'new')
        self.assertEqual(len(self.store.listing()['projects']), 1)
        self.assertNotIn('secret-test', json.dumps(self.store.export(metadata['id'])))
        self.assertTrue((self.root / 'projects' / metadata['id'] / 'revisions' / metadata['snapshot'] / 'README.md').exists())

    def test_atomic_save_failure_retains_previous_revision(self):
        original = self.create(); real_write = self.store.write
        def failure(relative, *args, **kwargs):
            if relative.endswith('/README.md'): raise bc.ContractError('disk full', 507)
            return real_write(relative, *args, **kwargs)
        with patch.object(self.store, 'write', side_effect=failure), self.assertRaises(bc.ContractError):
            self.store.save({'project_id': original['project']['id'], 'revision': 1, 'diagram': local_graph(), 'description': 'new'})
        self.assertEqual(self.store.get(original['project']['id']), original)

    def test_concurrent_saves_detect_conflict(self):
        original = self.create(); results = []
        def save():
            try:
                results.append(self.store.save({'project_id': original['project']['id'], 'revision': 1, 'diagram': local_graph()})['project']['revision'])
            except bc.ContractError as error: results.append(error.status)
        threads = [threading.Thread(target=save) for _ in range(2)]
        for t in threads: t.start()
        for t in threads: t.join()
        self.assertEqual(sorted(results), [2, 409])

    def test_project_run_isolation_snapshot_and_history_export_import(self):
        a, b = self.create(), self.create()
        ref = {'project_id': a['project']['id'], 'revision': 1}
        run = self.request('start', dict(ref, diagram={'untrusted': 'ignored'}))
        runner = self.server.project_runners[ref['project_id']]; runner.thread.join(5)
        self.assertEqual(runner.get(run['id'])['status'], 'ready')
        self.assertEqual(runner.get(run['id'])['project']['revision'], 1)
        self.assertEqual(self.request('runs', {'project_id': b['project']['id']})['runs'], [])
        with self.assertRaises(bc.ContractError):
            self.request('run', {'project_id': b['project']['id'], 'run_id': run['id']})
        with self.assertRaises(bc.ContractError):
            self.request('start', dict(ref, revision=0))
        exported = self.store.export(ref['project_id'], True)
        imported = self.store.import_package({'package': exported})
        new_id = imported['project']['id']
        self.assertNotEqual(new_id, ref['project_id'])
        records = self.request('runs', {'project_id': new_id})['runs']
        self.assertEqual(len(records), 1)
        step = self.request('step', {'project_id': new_id, 'run_id': records[0]['id'], 'node_id': 'prompt'})
        self.assertEqual(step['outputs']['text'], 'Classify hello (test)')
        self.assertNotIn('history', self.store.export(ref['project_id']))
        self.completion.assert_not_called()

    def test_paths_and_symbolic_links_are_rejected(self):
        with self.assertRaises(bc.ContractError): self.store.get('../other')
        created = self.create(); meta = created['project']
        path = self.root / 'projects' / meta['id'] / 'project.json'
        path.unlink(); path.symlink_to(self.root / 'elsewhere')
        with self.assertRaises(bc.ContractError): self.store.get(meta['id'])

    def test_subgraph_roundtrip_bindings_and_independent_instances(self):
        packed = sg.pack({'diagram': full_graph(), 'selected': ['prompt', 'answer'], 'name': 'Text processor'})
        graph, registry = sg.normalize(packed['diagram'])
        expanded, groups = sg.expand(graph, registry)
        checked, order = pr.validate(expanded)
        self.assertEqual(len(checked['nodes']), 4)
        self.assertEqual(len(groups[packed['node_id']]), 2)
        self.assertEqual(len(order), 4)
        unpacked = sg.unpack({'diagram': graph, 'node_id': packed['node_id']})['diagram']
        self.assertEqual(len(unpacked['nodes']), 4)
        self.assertEqual(len(unpacked['edges']), 3)
        mutated = deepcopy(graph); mutated['definitions'][0]['name'] = 'tampered'
        with self.assertRaises(bc.ContractError): sg.normalize(mutated)
        created = self.create(graph)
        exported = self.store.export(created['project']['id'])
        imported = self.store.import_package({'package': exported})
        self.assertEqual(imported['diagram'], created['diagram'])
        block_file = self.root / 'projects' / created['project']['id'] / 'blocks'
        self.assertEqual(len(list(block_file.glob('*.json'))), 1)

    def test_nested_subgraphs_run_with_unique_ids_and_instance_settings(self):
        packed = sg.pack({'diagram': local_graph(), 'selected': ['prompt'], 'name': 'Inner'})
        packed = sg.pack({'diagram': packed['diagram'], 'selected': [packed['node_id']], 'name': 'Outer'})
        graph = packed['diagram']; original = next(n for n in graph['nodes'] if n['id'] == packed['node_id'])
        duplicate = deepcopy(original); duplicate['id'] = 'copy'; duplicate['name'] = 'Copy'; duplicate['x'] += 300
        duplicate['block']['settings']['s0'] = 'Changed {{text}}'
        graph['nodes'].append(duplicate)
        expanded, groups = sg.expand(*sg.normalize(graph))
        self.assertEqual(len({n['id'] for n in expanded['nodes']}), 2)
        created = self.create(graph)
        run = self.request('start', {'project_id': created['project']['id'], 'revision': 1})
        runner = self.server.project_runners[created['project']['id']]; runner.thread.join(5)
        record = runner.get(run['id']); self.assertEqual(record['status'], 'ready', record)
        answers = [runner.step(run['id'], n)['outputs']['text'] for n in record['order']]
        self.assertEqual(answers, ['Classify hello (test)', 'Changed hello'])
        self.assertEqual(len(record['source_diagram']['definitions']), 2)
        self.assertEqual(set(record['groups']), {original['id'], 'copy'})
        package = self.store.export(created['project']['id'], True)
        self.assertEqual(len(self.store.import_package({'package': package})['diagram']['definitions']), 2)

    def test_missing_dependency_recursion_and_boundary_cycle(self):
        packed = sg.pack({'diagram': local_graph(), 'selected': ['prompt'], 'name': 'Inner'})
        graph = deepcopy(packed['diagram']); graph['definitions'] = []
        with self.assertRaises(bc.ContractError): sg.normalize(graph)
        graph = deepcopy(packed['diagram']); definition = graph['definitions'][0]
        definition['graph']['nodes'][0]['block'] = {'kind': definition['kind'], 'version': 1}
        with self.assertRaises(bc.ContractError) as error: sg.normalize(graph)
        self.assertIn('Рекурсивные', str(error.exception))
        with self.assertRaises(bc.ContractError):
            sg.pack({'diagram': full_graph(), 'selected': ['dataset', 'prompt'], 'name': 'Bad boundary'})

    def test_definition_hash_survives_browser_number_roundtrip(self):
        graph = local_graph(); graph['nodes'][0]['x'] = 1.0
        packed = sg.pack({'diagram': graph, 'selected': ['prompt'], 'name': 'Numbers'})
        original = packed['diagram']['definitions'][0]['kind']
        packed['diagram']['definitions'][0]['graph']['nodes'][0]['x'] = 1
        saved, _ = sg.normalize(packed['diagram'])
        self.assertEqual(saved['definitions'][0]['kind'], original)

    def test_malformed_history_rejected_before_project_creation(self):
        a = self.create(); package = self.store.export(a['project']['id'])
        package['history'] = [{'record': {'status': 'running'}, 'steps': {}}]
        with self.assertRaises(bc.ContractError): self.store.import_package({'package': package})
        self.assertEqual(len(self.store.listing()['projects']), 1)

