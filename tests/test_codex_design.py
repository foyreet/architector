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
import codex_design
import subgraphs
from block_contracts import ContractError

class DesignChat(unittest.TestCase):
    def setUp(self):
        self.s=BoardServer().__enter__();self.user=self.s.users[0];self.root=self.s.hub.workspace(self.user).root
        sections = {key: ('Текст ' + key + '\n') * 600 for key in codex_design.SECTIONS}
        self.doc = {'title':'Прежнее вложение', 'sections':sections, 'source_type':'private',
                    'source_id':str(uuid.uuid4()), 'revision':1, 'digest':subgraphs.digest(sections)}
        store, path = chat.conversation(self.root, {})
        store.write(path, {'messages':[], 'pending':None, 'error':'', 'design_version':1, 'design_document':self.doc})
    def tearDown(self):self.s.__exit__(None,None,None)
    def call(self,action,body=None,user=None):
        user=user or self.user
        return chat.request(self.s.hub.workspace(user).root,user,body or {},action,hub=self.s.hub)
    def test_full_model_read_and_removal_from_future_context(self):
        calls=[]
        def answer(prompt,documents=None,**kw):
            value=json.loads(prompt);meta=value['design_document'];calls.append(value)
            if meta:
                text='';offset=0
                while True:
                    chunk=documents.call('document_read',{'id':meta['id'],'offset':offset});text+=chunk['text'];offset=chunk['next_offset']
                    if offset is None:break
                for key in codex_design.SECTIONS:self.assertIn(self.doc['sections'][key],text)
            return 'Проверено'
        fake=SimpleNamespace(status=lambda:{'connected':True},answer=answer)
        with patch.object(chat,'client',return_value=fake):
            for i in range(2):
                self.call('send',{'message':'Прочитай документ','include_context':False})
                deadline=time.monotonic()+5
                while self.call('history')['pending'] and time.monotonic()<deadline:time.sleep(.01)
                self.assertFalse(self.call('history')['pending'])
                if i==0:self.call('design-remove',{'design_version':1})
        self.assertTrue(calls[0]['design_document']);self.assertIsNone(calls[1]['design_document']);self.assertNotIn('attachments',calls[1])
        self.assertIn('design_document',self.call('history')['messages'][0])
    def test_read_and_remove_legacy_snapshot(self):
        self.assertEqual(self.doc, self.call('design-get')['document'])
        with self.assertRaises(ContractError):
            self.call('design-remove', {'design_version':0})
        self.assertIsNone(self.call('design-remove', {'design_version':1})['document'])
        self.assertIsNone(self.call('design-remove', {'design_version':1})['document'])
