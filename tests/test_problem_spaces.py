from contextlib import closing
import json
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import uuid
from pathlib import Path

from block_contracts import ContractError
from local_workspace import Community, LOCAL_USER
import design_documents
import problem_spaces


class Spaces(unittest.TestCase):
    def test_legacy_tree_survives_document_deletion_and_edits_are_versioned(self):
        with tempfile.TemporaryDirectory() as root:
            hub = Community(root)
            path = Path(root) / 'workspace/local/documents.sqlite3'
            path.parent.mkdir(parents=True, exist_ok=True)
            tree_id = str(uuid.uuid4())
            nodes = [{'question': 'Первый вопрос', 'answer': 'Ответ', 'children': []}]
            with closing(sqlite3.connect(path)) as db, db:
                db.execute('CREATE TABLE design_documents(id TEXT PRIMARY KEY, owner TEXT,title TEXT,sections TEXT,revision INTEGER,updated REAL,source_release TEXT,problem_tree TEXT)')
                db.execute('INSERT INTO design_documents VALUES(?,?,?,?,?,?,?,?)',
                           (tree_id, LOCAL_USER['id'], 'Тема', json.dumps({'problem': 'Задача'}), 2, 0, None, json.dumps(nodes)))
            design_documents.request(hub, LOCAL_USER, {'id': tree_id, 'revision': 2}, 'delete')
            def api(action, **body):
                return problem_spaces.request(hub, LOCAL_USER, body, action)
            space = api('get', id=tree_id)
            self.assertEqual(space['problem_tree'], nodes)
            self.assertEqual(space['problem'], 'Задача')
            space['title'] = 'Уточнённая тема'
            self.assertEqual(api('save', **space), {'revision': 2})
            self.assertEqual(api('save', **space), {'revision': 2})
            with self.assertRaises(ContractError):
                api('save', **{**space, 'title': 'Другая версия'})
            self.assertEqual(len(api('list')['trees']), 1)
            self.assertEqual(design_documents.request(hub, LOCAL_USER, {}, 'list')['documents'], [])

    def test_saving_a_stage_only_fills_a_vacant_document_link(self):
        with tempfile.TemporaryDirectory() as root:
            hub = Community(root)
            doc_id, tree_id, another = (str(uuid.uuid4()) for _ in range(3))
            doc = design_documents.request(hub, LOCAL_USER, {'id': doc_id}, 'create')['document']
            body = {'id': tree_id, 'doc': doc_id, 'revision': 0, 'title': 'Задача', 'problem_tree': []}
            def saved():
                return design_documents.request(hub, LOCAL_USER, {'id': doc_id}, 'get')['document']

            with self.assertRaises(ContractError):
                problem_spaces.request(hub, {'id': 'other'}, body, 'save')
            with self.assertRaises(ContractError):
                problem_spaces.request(hub, LOCAL_USER, {**body, 'revision': 9}, 'save')
            self.assertEqual(saved(), doc)
            problem_spaces.request(hub, LOCAL_USER, body, 'save')
            linked = saved()
            self.assertEqual(linked['task_links'], {'tree_id': tree_id})
            self.assertEqual(linked['sections'], doc['sections'])
            problem_spaces.request(hub, LOCAL_USER, body, 'save')
            problem_spaces.request(hub, LOCAL_USER, body, 'attach')
            self.assertEqual(saved(), linked)
            with self.assertRaises(ContractError) as err:
                problem_spaces.request(hub, LOCAL_USER, {**body, 'id': another}, 'save')
            self.assertEqual(err.exception.status, 412)
            self.assertEqual(saved(), linked)
            self.assertEqual([t['id'] for t in problem_spaces.request(hub, LOCAL_USER, {}, 'list')['trees']], [tree_id])

    def test_question_proposals_use_tree_context_only(self):
        with tempfile.TemporaryDirectory() as root:
            hub = Community(root)
            body = {'title': 'Тема', 'problem': 'Задача', 'request': 'Уточни', 'problem_tree': []}
            with patch('codex_chat.standalone_answer', return_value='[{"question":"Кто?","children":[]}]') as model:
                proposal = problem_spaces.request(hub, LOCAL_USER, body, 'suggest-questions')
                self.assertEqual(proposal['questions'][0]['answer'], '')
                prompt = json.loads(model.call_args.args[1])
                self.assertEqual(prompt['problem'], 'Задача')
                self.assertNotIn('sections', prompt)
                model.return_value = '[]'
                with self.assertRaises(ContractError):
                    problem_spaces.request(hub, LOCAL_USER, body, 'suggest-questions')

    def test_edit_reset_and_independent_response_contracts(self):
        import metric_trees

        with tempfile.TemporaryDirectory() as root:
            hub = Community(root)
            for module, other, action, body, model_path, answer in (
                (problem_spaces, metric_trees, 'suggest-questions',
                 {'title':'Вопросы', 'request':'Уточни', 'problem_tree':[]},
                 'codex_chat.standalone_answer', [{'question':'Почему?', 'children':[]}]),
                (metric_trees, problem_spaces, 'suggest',
                 {'title':'Показатели', 'request':'Уточни', 'goal':'Рост', 'metrics':[], 'path':[]},
                 'metric_trees.standalone_answer', [{**dict.fromkeys(metric_trees.FIELDS, ''), 'name':'Выручка', 'children':[]}]),
            ):
                with self.subTest(mode=action):
                    def setting(action='method', **body):
                        return module.request(hub, LOCAL_USER, body, action)
                    default = setting()['text']
                    self.assertNotIn('JSON', default)
                    custom = 'Начни с конкретного примера.'
                    setting('save-method', previous=default, text=custom)
                    self.assertEqual(module.request(Community(root), LOCAL_USER, {}, 'method')['text'], custom)
                    self.assertEqual(other.request(hub, LOCAL_USER, {}, 'method')['text'], other.DEFAULT_METHOD)
                    with self.assertRaises(ContractError) as conflict:
                        setting('save-method', previous=default, text='Из другой вкладки')
                    self.assertEqual(conflict.exception.status, 409)
                    with self.assertRaises(ContractError):
                        setting('save-method', previous=custom, text='  ')
                    with patch(model_path, return_value=json.dumps(answer)) as model:
                        module.request(hub, LOCAL_USER, body, action)
                        self.assertIn(custom, model.call_args.args[2])
                        self.assertTrue(model.call_args.args[2].endswith(module.RESPONSE_CONTRACT))
                        model.return_value = '"произвольный текст"'
                        with self.assertRaises(ContractError) as malformed:
                            module.request(hub, LOCAL_USER, body, action)
                        self.assertEqual(malformed.exception.status, 502)
                        setting('save-method', previous=custom, text=None)
                        model.return_value = json.dumps(answer)
                        module.request(hub, LOCAL_USER, body, action)
                        self.assertIn(default, model.call_args.args[2])
                        self.assertNotIn(custom, model.call_args.args[2])
                    with patch.object(module, 'DEFAULT_METHOD', 'Обновлённая встроенная'):
                        self.assertEqual(setting()['text'], 'Обновлённая встроенная')
