"""Snapshot isolation, explicit replacement and real dispatch with a fake model."""
import json,time,uuid
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from test_whiteboard import BoardServer
import codex_chat as chat
import design_documents as docs
from block_contracts import ContractError

class DesignChat(unittest.TestCase):
    def setUp(self):
        self.s=BoardServer().__enter__();self.user=self.s.users[0];self.root=self.s.hub.workspace(self.user).root
        self.doc=docs.request(self.s.hub,self.user,{'id':str(uuid.uuid4())},'create')['document']
        self.doc=docs.request(self.s.hub,self.user,{**self.doc,'sections':{k:('Текст '+k+'\n')*600 for k in docs.SECTIONS}},'save')['document']
    def tearDown(self):self.s.__exit__(None,None,None)
    def call(self,action,body=None,user=None):
        user=user or self.user
        return chat.request(self.s.hub.workspace(user).root,user,body or {},action,hub=self.s.hub)
    def attach(self,**changes):
        return self.call('design-attach',{'source_type':'private','source_id':self.doc['id'],'source_revision':self.doc['revision'],'design_version':0,**changes})
    def test_update_remove_conflict_and_clear(self):
        old=self.attach();self.doc=docs.request(self.s.hub,self.user,{**self.doc,'title':'Новая версия'},'save')['document']
        current=self.call('design-get');self.assertTrue(current['changed']);self.assertEqual(current['document'],old['document'])
        with self.assertRaises(ContractError):self.call('design-update',{'design_version':99})
        self.assertEqual(self.call('design-get')['document'],old['document'])
        updated=self.call('design-update',{'design_version':1});self.assertEqual(updated['document']['title'],'Новая версия')
        with self.assertRaises(ContractError):self.call('design-remove',{'design_version':1})
        removed=self.call('design-remove',{'design_version':2});self.assertIsNone(removed['document'])
        self.call('clear');self.assertGreater(self.call('design-get')['version'],removed['version'])
        self.assertEqual(docs.request(self.s.hub,self.user,{'id':self.doc['id']},'get')['document']['title'],'Новая версия')
    def test_full_model_read_and_removal_from_future_context(self):
        calls=[]
        def answer(prompt,documents=None,**kw):
            value=json.loads(prompt);meta=value['design_document'];calls.append(value)
            if meta:
                text='';offset=0
                while True:
                    chunk=documents.call('document_read',{'id':meta['id'],'offset':offset});text+=chunk['text'];offset=chunk['next_offset']
                    if offset is None:break
                for key in docs.SECTIONS:self.assertIn(self.doc['sections'][key],text)
            return 'Проверено'
        fake=SimpleNamespace(status=lambda:{'connected':True},answer=answer)
        self.attach()
        with patch.object(chat,'client',return_value=fake):
            for i in range(2):
                self.call('send',{'message':'Прочитай документ','include_context':False})
                deadline=time.monotonic()+5
                while self.call('history')['pending'] and time.monotonic()<deadline:time.sleep(.01)
                self.assertFalse(self.call('history')['pending'])
                if i==0:self.call('design-remove',{'design_version':1})
        self.assertTrue(calls[0]['design_document']);self.assertIsNone(calls[1]['design_document']);self.assertNotIn('attachments',calls[1])
        self.assertIn('design_document',self.call('history')['messages'][0])
    def test_pending_blocks_mutation_but_allows_read(self):
        self.attach();key=str(self.root.resolve());chat.JOBS[key]='pending-test'
        try:
            for action in ('design-remove','design-update'):
                with self.assertRaises(ContractError) as e:self.call(action,{'design_version':1})
                self.assertEqual(e.exception.status,409)
            self.assertIsNotNone(self.call('design-get')['document'])
        finally:chat.JOBS.pop(key,None)

if __name__=='__main__':unittest.main()

