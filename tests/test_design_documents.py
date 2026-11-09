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
        for action in ('get','save','export'):
            with self.subTest(action=action),self.assertRaises(ContractError) as e:self.call(action,self.doc,self.b)
            self.assertEqual(e.exception.status,404)
        self.assertEqual(self.call('list',user=self.b)['documents'],[])
        self.save(sections={k:'Текст\n😀' if k=='problem' else '' for k in docs.SECTIONS})
        self.hub=community.Community(self.temp.name)
        self.assertEqual(self.call('get',self.doc)['document'],self.doc)
    def test_validation(self):
        for changes in ({'title':''},{'title':'x'*161},{'sections':{}},{'sections':{k:0 for k in docs.SECTIONS}}, {'sections':{k:'x'*20001 for k in docs.SECTIONS}}):
            with self.subTest(changes=list(changes)),self.assertRaises(ContractError):self.call('save',{**self.doc,**changes})
        for value in ('../bad',None,23,{},[]):
            with self.subTest(value=value),self.assertRaises(ContractError):self.call('create',{'id':value})
        with self.assertRaises(ContractError):self.publish()
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

class HttpDocuments(unittest.TestCase):
    pass

if __name__=='__main__':unittest.main()

