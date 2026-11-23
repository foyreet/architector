import json
import tempfile
import unittest
import uuid
from unittest.mock import patch

from block_contracts import ContractError
import design_documents as docs
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
    def test_review_checks_quote_against_current_text(self, model):
        self.body['sections']['problem'] = 'Излишки по утрам'
        comment = {'section': 'problem', 'quote': 'Излишки', 'reason': 'Неизвестен масштаб', 'question': 'Каковы потери?'}
        model.return_value = json.dumps([comment])
        self.assertEqual(docs.request(self.hub, LOCAL_USER, self.body, 'review')['comments'], [comment])
        model.return_value = json.dumps([{**comment, 'quote': 'Дефицит'}])
        with self.assertRaises(ContractError):
            docs.request(self.hub, LOCAL_USER, self.body, 'review')
