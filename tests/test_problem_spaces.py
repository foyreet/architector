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
