import json
import tempfile
import unittest
import uuid
from unittest.mock import patch

from block_contracts import ContractError
import design_documents as docs
import metric_trees
import problem_spaces
import solution_spaces
from local_workspace import Community, LOCAL_USER


class DesignAssistantTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.hub = Community(temp.name)
        self.tree = str(uuid.uuid4())
        problem_spaces.request(self.hub, LOCAL_USER, {
            'id': self.tree, 'revision': 0, 'title': 'Спрос', 'problem': 'Излишки',
            'problem_tree': [{'question': 'Когда?', 'answer': 'Утром', 'children': []}]}, 'save')
        options = [{**dict.fromkeys(solution_spaces.FIELDS, 'данные'), 'title': name, 'evidence': [1]}
                   for name in ('Прогноз спроса', 'Заказ товаров')]
        solution_spaces.request(self.hub, LOCAL_USER, {
            'id': self.tree, 'source_revision': 1, 'version': 0, 'options': options}, 'save')
        self.body = {'tree_id': self.tree, 'cases': [2], 'version': 1, 'revision': 1,
                     'title': 'Черновик', 'sections': dict.fromkeys(docs.SECTIONS, '')}

    @patch('design_assistant.standalone_answer')
    def test_preview_uses_selected_case_and_persists_refs_only_on_save(self, model):
        model.return_value = json.dumps({'problem': {'text': 'Много излишков', 'answers': [1], 'cases': [2]}})
        preview = docs.request(self.hub, LOCAL_USER, self.body, 'compose')['proposals']['problem']
        context = json.loads(model.call_args.args[1])
        self.assertEqual([c['title'] for c in context['cases']], ['Заказ товаров'])
        self.assertFalse(docs.request(self.hub, LOCAL_USER, {}, 'list')['documents'])
        self.assertEqual(preview['source']['answers'][0]['path'], ['Когда?'])
        doc = docs.request(self.hub, LOCAL_USER, {**self.body, 'id': str(uuid.uuid4()),
            'sources': {'problem': preview['source']}}, 'create')['document']
        self.assertEqual(docs.request(self.hub, LOCAL_USER, doc, 'export')['package']['sources'], doc['sources'])
        with self.assertRaises(ContractError):
            docs.request(self.hub, LOCAL_USER, {**self.body, 'cases': []}, 'compose')
        model.assert_called()
        model.reset_mock()
        for body, user in (({**self.body, 'version': 0}, LOCAL_USER), (self.body, {'id': 'other'})):
            with self.assertRaises(ContractError):
                docs.request(self.hub, user, body, 'compose')
        model.assert_not_called()

    @patch('design_assistant.standalone_answer')
    def test_metrics_only_and_combined_sources(self, model):
        leaf = {**dict.fromkeys(metric_trees.FIELDS, ''), 'name': 'CTR', 'relation': 'Прокси',
                'measurement': 'За неделю', 'check': 'Сверить с покупками', 'children': []}
        tree = {'id': str(uuid.uuid4()), 'title': 'Поиск', 'goal': 'Рост продаж', 'revision': 0,
                'metrics': [{**leaf, 'name': 'Покупки', 'children': [leaf]}]}
        metric_trees.request(self.hub, LOCAL_USER, tree, 'save')
        body = {**self.body, 'metric_tree_id': tree['id'], 'metric_revision': 1}
        entry = {'text': 'Проверить CTR', 'answers': [], 'cases': [], 'metrics': [0, 2]}
        model.return_value = json.dumps({'metric_validation': entry})
        for selected in (False, True):
            selection = body if selected else {**body, 'tree_id': '', 'cases': []}
            proposal = docs.request(self.hub, LOCAL_USER, selection, 'compose')['proposals']['metric_validation']
            context = json.loads(model.call_args.args[1])
            metrics = context['metric_tree']['metrics']
            self.assertEqual((metrics[1]['parent'], metrics[1]['check']), (metrics[0]['id'], leaf['check']))
            self.assertEqual(bool(context['cases']), selected)
            ref = proposal['source']
            self.assertEqual('tree_id' in ref, selected)
            snapshot = ref['metric_tree']
            self.assertEqual(snapshot['nodes'][0]['path'], ['Покупки', 'CTR'])
            self.assertEqual(snapshot['revision'], 1)
            sources = {'metric_validation': ref}
            doc = docs.request(self.hub, LOCAL_USER, {**self.body, 'id': str(uuid.uuid4()),
                               'sources': sources}, 'create')['document']
            self.assertEqual(docs.request(self.hub, LOCAL_USER, doc, 'export')['package']['sources'], sources)
        model.return_value = '[]'
        doc['sections']['metric_validation'] = entry['text']
        docs.request(self.hub, LOCAL_USER, doc, 'review')
        self.assertEqual(json.loads(model.call_args.args[1])['metric_sources']['metric_validation'], snapshot)
        model.return_value = json.dumps({'metric_validation': {**entry, 'metrics': [3]}})
        with self.assertRaises(ContractError) as invalid:
            docs.request(self.hub, LOCAL_USER, body, 'compose')
        self.assertEqual(invalid.exception.status, 502)
        model.reset_mock()
        for change, user, status in (({'metric_revision': 0}, LOCAL_USER, 409), ({}, {'id': 'other'}, 404)):
            with self.assertRaises(ContractError) as err:
                docs.request(self.hub, user, {**body, **change}, 'compose')
            self.assertEqual(err.exception.status, status)
        model.assert_not_called()

    @patch('design_assistant.standalone_answer')
    def test_validation_proposal_and_review(self, model):
        self.body['sections']['dataset'] = 'Заказы одного клиента за несколько недель'
        text = 'Сравниваем модели на новых клиентах'
        model.return_value = json.dumps({'validation': {'text': text, 'answers': [1], 'cases': [2]}})
        proposal = docs.request(self.hub, LOCAL_USER, self.body, 'compose')['proposals']['validation']
        context = json.loads(model.call_args.args[1])
        self.assertEqual(context['document']['sections']['dataset'], self.body['sections']['dataset'])
        self.assertEqual(proposal['source']['cases'][0]['id'], 2)
        self.body['sections']['validation'] = proposal['text']
        comment = {'section': 'validation', 'quote': text, 'reason': 'Возможное пересечение клиентов',
                   'question': 'Каким ключом закрепляем клиента за выборкой?'}
        model.return_value = json.dumps([comment])
        self.assertEqual(docs.request(self.hub, LOCAL_USER, self.body, 'review')['comments'], [comment])

    @patch('design_assistant.standalone_answer')
    def test_review_checks_quote_against_current_text(self, model):
        self.body['sections']['problem'] = 'Излишки по утрам'
        comment = {'section': 'problem', 'quote': 'Излишки', 'reason': 'Неизвестен масштаб', 'question': 'Каковы потери?'}
        model.return_value = json.dumps([comment])
        self.assertEqual(docs.request(self.hub, LOCAL_USER, self.body, 'review')['comments'], [comment])
        model.return_value = json.dumps([{**comment, 'quote': 'Дефицит'}])
        with self.assertRaises(ContractError):
            docs.request(self.hub, LOCAL_USER, self.body, 'review')
