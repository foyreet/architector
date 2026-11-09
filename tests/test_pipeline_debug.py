from copy import deepcopy
import json
import unittest
import uuid
from unittest.mock import patch

import block_contracts as bc
import pipeline_runner as pr
import project_store as ps
import subgraphs as sg
import test_pipeline as fixture
import test_projects as projects


class DebugTests(unittest.TestCase):
    setUp = fixture.PipelineTests.setUp
    tearDown = fixture.PipelineTests.tearDown
    finish = fixture.PipelineTests.finish

    def body(self, node=None, base=None, graph=None):
        return {'diagram': graph or fixture.scenario(), 'debug': {'action': 'step' if node else 'continue', 'node_id': node, 'base_run_id': base}}

    def launch(self, body, secret=False):
        body = dict(body, plan_digest=self.runner.debug_preview(body)['digest'], run_id=str(uuid.uuid4()), secrets={'openrouter': 'test-key'} if secret else {})
        run = self.runner.start(body)
        return self.finish(run), body

    def test_step_inputs_continue_and_idempotency(self):
        missing = self.runner.debug_preview(self.body('prompt'))
        self.assertEqual(missing['blocked'][0]['node_id'], 'csv')
        with self.assertRaises(bc.ContractError): self.launch(self.body('prompt'))
        first, _ = self.launch(self.body('dataset'))
        self.assertEqual(first['status'], 'paused'); self.completion.assert_not_called()
        second, _ = self.launch(self.body('csv', first['id']))
        self.assertEqual(second['nodes']['dataset']['reused_from'], first['id'])
        preview = self.runner.debug_preview(self.body('prompt', second['id']))
        self.assertEqual(preview['inputs'][0]['inputs']['row']['text'], 'second')
        third, _ = self.launch(self.body('prompt', second['id']))
        self.assertEqual(third['status'], 'paused')
        complete, body = self.launch(self.body(base=third['id']), secret=True)
        self.assertEqual(complete['status'], 'ready'); self.assertEqual(self.completion.call_count, 1)
        self.assertEqual(complete['execution_order'], ['answer'])
        self.assertEqual(self.runner.start(body)['id'], complete['id']); self.assertEqual(self.completion.call_count, 1)
        self.assertEqual(self.runner.get(first['id']), first)
        self.assertEqual(self.runner.step(complete['id'], 'prompt')['outputs']['text'], 'Classify second (two)')
        restarted = pr.PipelineRunner(self.completion, self.runner.kaggle, self.runner.huggingface, self.root)
        self.assertEqual(restarted.get(first['id'])['status'], 'paused')

    def test_settings_and_edges_invalidate_descendants_and_old_plans(self):
        original, _ = self.launch(self.body(), secret=True)
        graph = fixture.scenario(); graph['nodes'][1]['block']['settings']['template'] = 'Changed {{text}}'
        body = self.body(base=original['id'], graph=graph); plan = self.runner.debug_preview(body)
        self.assertEqual([n['id'] for n in plan['reused']], ['dataset', 'csv'])
        self.assertEqual([n['id'] for n in plan['execute']], ['prompt', 'answer'])
        with self.assertRaises(bc.ContractError): self.runner.start(dict(body, plan_digest='stale'))
        selected = self.runner.debug_preview(self.body('csv', original['id']))
        self.assertEqual([n['id'] for n in selected['reused']], ['dataset'])
        self.assertEqual(selected['remaining'], ['prompt', 'answer'])
        self.runner.kaggle.archive_path('owner/data/versions/2').unlink()
        with self.assertRaises(bc.ContractError): self.runner.start(dict(body, plan_digest=plan['digest'], secrets={'openrouter':'test-key'}))
        self.assertEqual(self.completion.call_count, 1)

    def test_failure_requires_explicit_retry_and_cannot_cross_history_scope(self):
        self.completion.side_effect = bc.ContractError('Provider rejected request')
        failed, _ = self.launch(self.body(), secret=True)
        self.assertEqual(failed['status'], 'error'); self.assertEqual(self.completion.call_count, 1)
        plan = self.runner.debug_preview(self.body(base=failed['id']))
        self.assertEqual([n['id'] for n in plan['execute']], ['answer'])
        self.assertEqual(self.completion.call_count, 1)
        other = pr.PipelineRunner(self.completion, self.runner.kaggle, self.runner.huggingface, self.root, 'projects/another/runs')
        with self.assertRaises(bc.ContractError): other.debug_preview(self.body(base=failed['id']))
        archived = deepcopy(failed); archived['imported'] = True; self.runner.current = None; self.runner.save(archived)
        with self.assertRaises(bc.ContractError): self.runner.debug_preview(self.body(base=failed['id']))

    def test_subgraph_executes_its_internal_steps_and_pause_exports(self):
        packed = sg.pack({'diagram': projects.full_graph(), 'selected': ['prompt', 'answer'], 'name': 'Text processing'})
        graph = packed['diagram']
        first, _ = self.launch(self.body('dataset', graph=graph))
        second, _ = self.launch(self.body('csv', first['id'], graph))
        body = self.body(packed['node_id'], second['id'], graph)
        plan = self.runner.debug_preview(body)
        self.assertEqual([n['kind'] for n in plan['execute']], ['template', 'openrouter'])
        complete, _ = self.launch(body, secret=True)
        self.assertEqual(complete['status'], 'ready'); self.completion.assert_called_once()
        store = ps.ProjectStore(self.root)
        project = store.save({'diagram': graph}, create=True)
        runner = pr.PipelineRunner(self.completion, self.runner.kaggle, self.runner.huggingface, self.root, store.folder(project['project']['id']) + '/runs')
        body = self.body('dataset', graph=graph); body['plan_digest'] = runner.debug_preview(body)['digest']
        paused = runner.start(body); runner.thread.join(5)
        package = store.export(project['project']['id'], True)
        restored = store.import_package({'package': package})
        self.assertEqual(len(store.export(restored['project']['id'], True)['history']), 1)
        self.assertEqual(store.export(restored['project']['id'], True)['history'][0]['record']['status'], 'paused')

