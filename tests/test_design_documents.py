"""Private documents, optimistic saves and immutable community publication."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys
import tempfile
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import uuid
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import local_workspace as community
import design_documents as docs
from block_contracts import ContractError
from test_whiteboard import BoardServer

class Documents(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.hub=community.Community(self.temp.name)
        self.a={'id':'author'}; self.b={'id':'reader'}
        self.doc=self.call('create',{'id':str(uuid.uuid4())})['document']
    def tearDown(self):self.temp.cleanup()
    def call(self,action,body=None,user=None):return docs.request(self.hub,user or self.a,body or {},action)
    def save(self,**changes):
        body={**self.doc,'title':'Отток клиентов','sections':{k:'Текст\n'+k for k in docs.SECTIONS},**changes}
        self.doc=self.call('save',body)['document'];return body
    def publish(self):
        preview=self.call('preview',self.doc)
        return self.call('publish',{**self.doc,'digest':preview['digest']})
    def test_private_owner_auth_and_incomplete_drafts(self):
        with self.assertRaises(ContractError) as e:docs.request(self.hub,None,{},'list')
        self.assertEqual(e.exception.status,401)
        for action in ('get','save','export','delete'):
            with self.subTest(action=action),self.assertRaises(ContractError) as e:self.call(action,self.doc,self.b)
            self.assertEqual(e.exception.status,404)
        self.assertEqual(self.call('list',user=self.b)['documents'],[])
        self.save(sections={k:'Текст\n😀' if k=='problem' else '' for k in docs.SECTIONS})
        self.hub=community.Community(self.temp.name)
        self.assertEqual(self.call('get',self.doc)['document'],self.doc)
    def test_progress_uses_owned_saved_trees_and_keeps_shared_tasks_separate(self):
        from problem_spaces import request as problem_request
        tree_id = str(uuid.uuid4())
        tree = {'id': tree_id, 'title': 'Задача', 'problem': '', 'revision': 0, 'problem_tree': [
            {'question': 'Цель?', 'answer': 'Рост', 'children': [
                {'question': 'Когда?', 'answer': '  ', 'children': []}]}]}
        problem_request(self.hub, self.a, tree, 'save')
        foreign = str(uuid.uuid4())
        problem_request(self.hub, self.b, {**tree, 'id': foreign}, 'save')
        def overview():
            return self.call('list', {'include_progress': True})
        self.assertEqual([row['problem']['id'] for row in overview()['unlinked']], [tree_id])
        self.save(task_links={'tree_id': tree_id, 'metric_tree_id': str(uuid.uuid4())})
        second = self.call('create', {'id': str(uuid.uuid4()), 'task_links': {'tree_id': tree_id}})
        result = overview()
        self.assertFalse(result['unlinked'])
        self.assertEqual(len(result['documents']), 2)
        for row in result['documents']:
            self.assertEqual((row['problem']['answered'], row['problem']['questions']), (1, 2))
            self.assertEqual(row['missing_metric'], row['id'] == self.doc['id'])
        self.call('delete', second['document'])
        self.assertFalse(overview()['unlinked'])
        self.call('delete', self.doc)
        self.assertEqual([row['problem']['id'] for row in overview()['unlinked']], [tree_id])

    def test_task_keeps_saved_stages_together_and_respects_explicit_unlink(self):
        from problem_spaces import request as problem
        from metric_trees import request as metric
        task_id, tree_id, metric_id, other_id = (str(uuid.uuid4()) for _ in range(4))
        tree = {'id': tree_id, 'draft_task': task_id, 'title': 'Название', 'problem_tree': [], 'revision': 0}
        problem(self.hub, self.a, tree, 'save')
        with self.assertRaises(ContractError) as error:
            problem(self.hub, self.a, {**tree, 'id': other_id}, 'save')
        self.assertEqual(error.exception.status, 412)
        metric(self.hub, self.a, {'id': metric_id, 'draft_task': task_id, 'title': 'Цель', 'goal': '',
                                  'metrics': [], 'revision': 0}, 'save')
        rows = self.call('list', {'include_progress': True})['unlinked']
        self.assertEqual([(r['draft_id'], r['problem']['id'], r['metric']['id']) for r in rows],
                         [(task_id, tree_id, metric_id)])
        # The metric was saved in another tab; the user explicitly removed only the problem tree.
        doc = self.call('create', {'id': task_id, 'initial_task_links': {'tree_id': tree_id}, 'task_links': {}})
        self.assertEqual(doc['document']['task_links'], {'metric_tree_id': metric_id})
        rows = self.call('list', {'include_progress': True})['unlinked']
        self.assertEqual([r['problem']['id'] for r in rows], [tree_id])

    def test_validation(self):
        for changes in ({'title':''},{'sections':{}},{'sections':{k:0 for k in docs.SECTIONS}}):
            with self.subTest(changes=list(changes)),self.assertRaises(ContractError):self.call('save',{**self.doc,**changes})
        for value in ('../bad',None,23,{},[]):
            with self.subTest(value=value),self.assertRaises(ContractError):self.call('create',{'id':value})
        with self.assertRaises(ContractError):self.publish()
    def test_legacy_sections_and_saves_preserve_dataset_and_validation(self):
        old = {k: k for k in docs.SECTIONS if k not in ('dataset', 'validation')}
        with self.hub.db() as db:
            db.execute('UPDATE design_documents SET sections=? WHERE id=?',
                       (json.dumps(old), self.doc['id']))
        upgraded = self.call('get', self.doc)['document']
        self.assertEqual(upgraded['sections'], {**old, 'dataset': '', 'validation': ''})
        self.assertEqual(upgraded['revision'], self.doc['revision'])
        self.assertEqual(self.call('save', upgraded)['document']['revision'], upgraded['revision'])
        package = self.call('export', upgraded)['package']
        imported = self.call('import', {'id': str(uuid.uuid4()), 'package': {**package, 'sections': old}})['document']
        self.assertEqual(imported['sections'], upgraded['sections'])
        ref = {'tree_id': str(uuid.uuid4()), 'revision': 1, 'version': 0,
               'title': 'Источник', 'answers': [], 'cases': []}
        doc = self.call('save', {**upgraded, 'sections': {**old, 'dataset': 'Наблюдения', 'validation': 'По клиентам'},
                                 'sources': {'dataset': ref, 'validation': ref}})['document']
        updated = self.call('save', {**doc, 'sections': {**old, 'target': 'Правка старого клиента'},
                                     'sources': {}})['document']
        self.assertEqual(updated['sections']['dataset'], 'Наблюдения')
        self.assertEqual(updated['sources']['dataset'], ref)
        self.assertEqual(updated['sections']['validation'], 'По клиентам')
        self.assertEqual(updated['sources']['validation'], ref)
        package = self.call('export', updated)['package']
        imported = self.call('import', {'id': str(uuid.uuid4()), 'package': package})['document']
        self.assertEqual(imported['sections'], updated['sections'])

    def test_old_features_are_kept_in_dataset(self):
        sections = {key: '' for key in docs.SECTIONS}
        sections.update(dataset='Источники', data_features='История покупок')
        normalized = docs.normalize_sections(sections)
        self.assertNotIn('data_features', normalized)
        self.assertIn('История покупок', normalized['dataset'])
        self.assertEqual(docs.normalize_sections(normalized), normalized)
        self.assertEqual(docs.normalize_sections({**normalized, 'data_features': 'История покупок'}), normalized)

    def test_task_links_roundtrip_legacy_save_and_revision(self):
        links = {'tree_id':str(uuid.uuid4()), 'metric_tree_id':str(uuid.uuid4()), 'case_version':2, 'cases':[2]}
        self.save(task_links=links)
        original = self.doc.copy()
        legacy = {k:v for k,v in original.items() if k != 'task_links'}
        saved = self.call('save', {**legacy, 'title':'Другая формулировка'})['document']
        self.assertEqual(saved['task_links'], links)
        with self.assertRaises(ContractError):
            self.call('save', {**original, 'task_links':{}})
        package = self.call('export', saved)['package']
        imported = self.call('import', {'id':str(uuid.uuid4()), 'package':package})['document']
        self.assertEqual(imported['task_links'], links)
        with self.assertRaises(ContractError):
            self.call('save', {**saved, 'task_links':{'cases':[1], 'case_version':2}})
        cleared = self.call('save', {**saved, 'task_links':{}})['document']
        self.assertFalse(cleared['task_links'])
        self.assertEqual(cleared['sections'], saved['sections'])

    def test_large_document_roundtrip(self):
        sections = {key: 'Ж' * 40000 for key in docs.SECTIONS}
        self.save(title='Д' * 161, sections=sections)
        self.assertEqual(self.call('get', self.doc)['document']['sections'], sections)

    def test_concurrent_saves_and_retry(self):
        old=dict(self.doc);body=self.save()
        self.assertEqual(self.call('save',body)['document'],self.doc)
        self.assertEqual(self.call('create',{'id':self.doc['id']})['document'],self.doc)
        with self.assertRaises(ContractError) as e:self.call('save',{**old,'title':'Конфликт'})
        self.assertEqual(e.exception.status,409)
        base=dict(self.doc)
        def save(title):
            try:return self.call('save',{**base,'title':title})
            except ContractError as e:return e.status
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(save,['Первая вкладка','Вторая вкладка']))
        self.assertEqual(results.count(409),1)

    def test_create_saves_complete_payload_atomically_and_retries_once(self):
        body={'id':str(uuid.uuid4()),'title':'Первое сохранение','sections':{k:'Текст '+k for k in docs.SECTIONS}}
        first=self.call('create',body)['document']
        self.assertEqual(first['title'],body['title'])
        self.assertEqual(first['sections'],body['sections'])
        self.assertEqual(first['revision'],1)
        self.assertEqual(self.call('create',body)['document'],first)
        self.assertEqual(len(self.call('list')['documents']),2)
        bad={**body,'id':str(uuid.uuid4()),'title':''}
        with self.assertRaises(ContractError):self.call('create',bad)
        with self.assertRaises(ContractError) as e:self.call('get',bad)
        self.assertEqual(e.exception.status,404)

    def test_delete_checks_revision_and_does_not_resurrect_on_save(self):
        old=dict(self.doc);self.save()
        for revision in (old['revision'],None,True):
            with self.assertRaises(ContractError) as e:self.call('delete',{**self.doc,'revision':revision})
            self.assertEqual(e.exception.status,409)
        self.assertEqual(self.call('get',self.doc)['document'],self.doc)
        self.assertEqual(self.call('delete',self.doc),{'deleted':self.doc['id']})
        self.assertEqual(self.call('list')['documents'],[])
        for action in ('get','save','export','delete'):
            with self.subTest(action=action),self.assertRaises(ContractError) as e:self.call(action,self.doc)
            self.assertEqual(e.exception.status,404)

class HttpDocuments(unittest.TestCase):
    pass

if __name__=='__main__':unittest.main()

