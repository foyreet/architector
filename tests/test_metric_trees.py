import json
import tempfile
import unittest
import uuid
from unittest.mock import patch

from block_contracts import ContractError
from local_workspace import Community, LOCAL_USER
import metric_trees
import problem_spaces


def metric(name, *children):
    return {**dict.fromkeys(metric_trees.FIELDS, ''), 'name': name, 'children': list(children)}


class MetricTreeTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.hub = Community(temp.name)
        self.body = {'id': str(uuid.uuid4()), 'title': 'Поиск', 'revision': 0, 'goal': 'Продажи',
                     'metrics': [metric('Маржа', metric('Покупки', metric('Конверсия', metric('CTR'))))]}

    def call(self, action, **extra):
        return metric_trees.request(self.hub, LOCAL_USER, {**self.body, **extra}, action)

    def test_deep_tree_and_independent_revisions(self):
        self.assertEqual(self.call('save'), self.call('save'))
        self.assertEqual(self.call('get')['metrics'], self.body['metrics'])
        self.assertEqual(self.call('list')['trees'][0]['id'], self.body['id'])
        self.assertFalse(problem_spaces.request(self.hub, LOCAL_USER, {}, 'list')['trees'])
        with self.assertRaises(ContractError) as conflict:
            self.call('save', goal='Другая цель')
        self.assertEqual(conflict.exception.status, 409)
        with self.assertRaises(ContractError):
            metric_trees.request(self.hub, {'id': 'other'}, self.body, 'get')

    @patch('metric_trees.standalone_answer')
    def test_branch_proposal_is_a_preview(self, model):
        model.return_value = json.dumps([metric('Прокси')])
        result = self.call('suggest', request='Уточни прокси', path=[0, 0, 0, 0])
        self.assertEqual(result['metrics'][0]['name'], 'Прокси')
        self.assertEqual(json.loads(model.call_args.args[1])['path'], [0, 0, 0, 0])
        self.assertFalse(self.call('list')['trees'])
        with self.assertRaises(ContractError):
            self.call('suggest', request='Уточни', path=[1])
        model.return_value = '[{"name":"Ошибка"}]'
        with self.assertRaises(ContractError) as error:
            self.call('suggest', request='Уточни', path=[])
        self.assertEqual(error.exception.status, 502)
