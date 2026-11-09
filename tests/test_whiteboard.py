"""Durable collaborative edits, authorization, HTTP boundaries and lost-response retries."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import local_workspace as community
import project_store
import serve
import whiteboard
from block_contracts import ContractError


def shape(**changes):
    return dict(kind='rect', x=30, y=40, w=150, h=80, color='#26324b', width=2, **changes)


class BoardServer:
    def __enter__(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.patch = patch('project_store.ROOT', self.root); self.patch.start()
        self.hub = community.Community(self.root)
        self.users = [dict(community.LOCAL_USER)]
        self.server = serve.ThreadingHTTPServer(('127.0.0.1',0),serve.Handler)
        self.origin = f'http://127.0.0.1:{self.server.server_port}'
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        return self
    def __exit__(self,*args):
        self.server.shutdown();self.server.server_close();self.thread.join();self.patch.stop();self.temp.cleanup()


class BoardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.hub = community.Community(self.temp.name)
        self.owner = {'id': str(uuid.uuid4()), 'username': 'teacher'}
        self.student = {'id': str(uuid.uuid4()), 'username': 'student'}
        self.board = self.call('create')['id']

    def tearDown(self): self.temp.cleanup()

    def call(self, action, body=None, user=None):
        return whiteboard.request(self.hub, user or self.owner, dict(board_id=self.board if hasattr(self,'board') else None, **(body or {})), action)

    def op(self, **changes):
        body = {'op_id':str(uuid.uuid4()), 'object_id':str(uuid.uuid4()), 'expected':0, 'data':shape()}
        body.update(changes); return body

    def invite(self):
        token = self.call('share')['token']; self.call('join', {'token':token}, self.student); return token



    def test_parallel_objects_merge_and_persist_across_connections(self):
        ops=[self.op() for _ in range(12)]
        with ThreadPoolExecutor(max_workers=4) as pool: list(pool.map(lambda op:self.call('apply',op),ops))
        self.hub=community.Community(self.temp.name)
        got=self.call('get');self.assertEqual(len(got['items']),12);self.assertEqual(got['board']['revision'],12)
        self.assertIsNone(self.call('get',{'since':12})['items'])

    def test_same_object_cannot_silently_overwrite(self):
        op=self.op();self.call('apply',op)
        changed=self.op(object_id=op['object_id'],expected=1,data={**shape(),'x':80})
        self.call('apply',changed)
        with self.assertRaises(ContractError) as e:self.call('apply',self.op(object_id=op['object_id'],expected=1,data=None))
        self.assertEqual(e.exception.status,409);self.assertEqual(self.call('get')['items'][0]['data']['x'],80)

    def test_response_loss_replay_is_idempotent(self):
        op=self.op();first=self.call('apply',op);self.assertEqual(self.call('apply',op),first)
        self.assertEqual(self.call('get')['board']['revision'],1)
        op['data']['x']=900
        with self.assertRaises(ContractError):self.call('apply',op)

    def test_delete_retains_tombstone_preventing_resurrection(self):
        op=self.op();self.call('apply',op)
        self.call('apply',self.op(object_id=op['object_id'],expected=1,data=None))
        with self.assertRaises(ContractError):self.call('apply',self.op(object_id=op['object_id'],expected=0))
        self.assertIsNone(self.call('get')['items'][0]['data'])
        self.call('apply',self.op(object_id=op['object_id'],expected=2))
        self.assertEqual(self.call('get')['items'][0]['version'],3)

    def test_undo_does_not_erase_another_tabs_later_edit(self):
        op=self.op();self.call('apply',op)
        self.call('apply',self.op(object_id=op['object_id'],expected=1,data={**shape(),'y':900}))
        with self.assertRaises(ContractError): self.call('apply',self.op(object_id=op['object_id'],expected=1,data=None))
        self.assertEqual(self.call('get')['items'][0]['data']['y'],900)

    def test_untrusted_values_rejected(self):
        cases=[{**shape(),'x':float('nan')},{**shape(),'x':float('inf')},{**shape(),'x':True},
               {**shape(),'color':'url(https://example.com)'},{**shape(),'w':-5},{**shape(),'html':'<script>'},
               {**shape(),'kind':'image'},{'kind':'pen','x':0,'y':0,'color':'#000000','width':2,'points':[[0,0]]*2001},
               {'kind':'text','x':0,'y':0,'color':'#000000','width':2,'text':'x'*1001}]
        for value in cases:
            with self.subTest(value=str(value)[:60]),self.assertRaises(ContractError):self.call('apply',self.op(data=value))
        self.assertEqual(self.call('get')['items'],[])

    def test_text_is_data_and_board_capacity_fails_atomically(self):
        text={'kind':'text','x':0,'y':0,'color':'#000000','width':2,'text':'Привет <script>alert(1)</script>'}
        self.call('apply',self.op(data=text));self.assertEqual(self.call('get')['items'][0]['data'],text)
        with whiteboard.database(self.hub) as db:
            db.executemany('INSERT INTO objects VALUES(?,?,?,?)',[(self.board,str(uuid.uuid4()),1,None) for _ in range(1999)])
        with self.assertRaises(ContractError) as e:self.call('apply',self.op())
        self.assertEqual(e.exception.status,413)
        self.assertEqual(self.call('get')['board']['revision'],1)


class BoardHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.server=BoardServer().__enter__()
    @classmethod
    def tearDownClass(cls):cls.server.__exit__()

    def test_external_invitation_navigation_but_no_cross_site_api(self):
        headers={'Sec-Fetch-Site':'cross-site','Sec-Fetch-Mode':'navigate','Sec-Fetch-Dest':'document'}
        with urlopen(Request(self.server.origin+'/board.html?board=example',headers=headers)) as r:
            self.assertEqual(r.status,200);self.assertIn('no-referrer',r.headers['Referrer-Policy'])
        req=Request(self.server.origin+'/api/boards/list',b'{}',dict(headers,**{'Content-Type':'application/json'}))
        with self.assertRaises(HTTPError) as e:urlopen(req)
        self.assertEqual(e.exception.code,403)


if __name__=='__main__':unittest.main()

