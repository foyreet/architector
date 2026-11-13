"""No-account HTTP workspace, MCP, user-owned AI, documents and queue boundaries."""
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import uuid
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ai_connection as ai
import architect_mcp as mcp
import block_contracts as bc
import codex_chat as chat
import design_documents as docs
import gpu_compute as gpu
import local_workspace as local
import project_store as ps
import serve

class LocalTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.patch=patch.object(ps,'ROOT',self.root);self.patch.start()
        self.server=ThreadingHTTPServer(('127.0.0.1',0),serve.Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.origin=f'http://127.0.0.1:{self.server.server_port}'
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join();self.patch.stop();self.temp.cleanup()
    def post(self,path,body=None,headers=None):
        req=Request(self.origin+path,json.dumps(body or {}).encode(),{'Content-Type':'application/json','X-Architect-Request':'1',**(headers or {})})
        try:
            with urlopen(req,timeout=5) as r:return r.status,json.load(r)
        except HTTPError as e:
            with e:return e.code,json.load(e)
    def test_single_workspace_no_registration_no_demo_routes(self):
        code,result=self.post('/api/community/session');self.assertEqual(code,200);self.assertFalse(result['enabled']);self.assertTrue(result['local'])
        for path in ['/api/community/register','/api/community/login','/api/projects/tutorial','/api/code/examples','/api/practice/open','/api/gpu/create']:
            self.assertEqual(self.post(path)[0],404,path)
        graph={'format':'architect','version':4,'name':'Свой проект','nodes':[],'types':[],'edges':[],'definitions':[]}
        code,saved=self.post('/api/projects/create',{'name':'Свой проект','diagram':graph});self.assertEqual(code,200)
        identity=saved['project']['id']
        self.assertEqual(self.post('/api/projects/get',{'project_id':identity})[1]['diagram']['name'],'Свой проект')
        self.assertEqual(self.post('/api/projects/list',headers={'Origin':'https://outside.invalid'})[0],403)
        self.assertEqual(self.post('/api/projects/list',headers={'Host':'outside.invalid'})[0],403)
        self.assertEqual(self.post('/api/projects/list',headers={'X-Architect-Request':'0'})[0],403)
    def test_mcp_no_token_local_only_and_no_examples(self):
        def rpc(method,params=None,**headers):
            return self.post('/mcp',{'jsonrpc':'2.0','id':1,'method':method,'params':params or {}},{'Accept':'application/json, text/event-stream',**headers})
        code,value=rpc('initialize',{'protocolVersion':'2025-06-18','capabilities':{},'clientInfo':{'name':'test','version':'1'}});self.assertEqual(code,200);self.assertIn('result',value)
        self.assertIn('result', rpc('tools/list', {'_meta': {'padding': 'x' * (5 * 1024 * 1024)}})[1])
        tools=rpc('tools/list')[1]['result']['tools'];names={t['name'] for t in tools}
        self.assertEqual(len(names),7);self.assertNotIn('architect_pipeline_examples',names)
        self.assertFalse(any('publish' in name or 'run' in name for name in names))
        self.assertEqual(rpc('tools/list',Origin='https://outside.invalid')[0],403)
        result=rpc('tools/call',{'name':'architect_list_projects','arguments':{}})[1]
        self.assertFalse(result.get('error'));self.assertFalse(result['result'].get('isError'))
    def test_documents_export_import_no_auth_and_board(self):
        identity=str(uuid.uuid4());code,r=self.post('/api/design-documents/create',{'id':identity});self.assertEqual(code,200)
        doc=r['document'];sections={k:'Мой раздел '+k for k in docs.SECTIONS}
        code,r=self.post('/api/design-documents/save',{**doc,'title':'Задача','sections':sections});self.assertEqual(code,200)
        package=self.post('/api/design-documents/export',{'id':identity})[1]['package']
        copied=self.post('/api/design-documents/import',{'id':str(uuid.uuid4()),'package':package})[1]['document']
        self.assertNotEqual(copied['id'],identity);self.assertEqual(copied['sections'],sections)
        self.assertEqual(self.post('/api/design-documents/publish',{'id':identity})[0],404)
        code,board=self.post('/api/boards/create',{'title':'Локальная доска'});self.assertEqual(code,200)
        self.assertEqual(self.post('/api/boards/get',{'board_id':board['id']})[0],200)
        self.assertEqual(self.post('/api/boards/share',{'board_id':board['id']})[0],404)
    def test_ai_disconnected_no_network_key_not_returned_and_persists(self):
        with patch.object(ai.Compatible,'http',side_effect=AssertionError('Unexpected network')):
            self.assertFalse(self.post('/api/codex/status')[1]['connected'])
            code,result=self.post('/api/codex/configure',{'provider':'compatible','base_url':'http://localhost:11434/v1','model':'local','api_key':'test-only-key'})
            self.assertEqual(code,200);self.assertNotIn('api_key',result);self.assertTrue(result['has_key'])
            self.assertTrue(self.post('/api/codex/status')[1]['connected'])
        self.assertEqual(ai.config(self.root)['api_key'],'test-only-key')
        if os.name!='nt':self.assertEqual((self.root/'workspace/ai/connection.json').stat().st_mode&0o777,0o600)
        ai.save(self.root,{'provider':'compatible','base_url':'http://localhost:11435/v1','model':'local','keep_key':True})
        self.assertFalse(ai.config(self.root)['api_key'])
        self.assertEqual(self.post('/api/codex/configure',{'provider':'compatible','base_url':'http://external.invalid','model':'local'})[0],400)

    def test_codex_readiness_does_not_launch_process_or_change_provider(self):
        ai.save(self.root, {'provider':'compatible','base_url':'http://localhost:11434/v1','model':'local','api_key':'test-only'})
        with patch.object(chat.shutil,'which',return_value=None), patch.object(chat,'client',side_effect=AssertionError('Must not start CLI')):
            code, value=self.post('/api/codex/config')
            self.assertEqual(code,200);self.assertFalse(value['codex']['available']);self.assertNotIn('api_key',value)
            self.assertEqual(self.post('/api/codex/configure',{'provider':'codex'})[0],409)
            self.assertEqual(ai.config(self.root)['provider'],'compatible')
        with patch.object(chat.shutil,'which',return_value='/test/bin/program'):
            self.assertTrue(self.post('/api/codex/config')[1]['codex']['available'])
            self.assertEqual(self.post('/api/codex/configure',{'provider':'codex'})[0],200)
        with patch.object(chat.shutil,'which',return_value=None), patch.object(chat,'client',side_effect=AssertionError('Must not start CLI')):
            self.assertEqual(self.post('/api/codex/status')[1]['reason'],'codex_missing')
            self.assertEqual(self.post('/api/codex/login')[0],409)


class ModelTests(unittest.TestCase):
    def test_real_http_compatible_api_and_no_redirect_secret_forwarding(self):
        calls=[]
        class API(BaseHTTPRequestHandler):
            def log_message(self,*a):pass
            def do_GET(self):
                calls.append(self.path)
                if self.path=='/v1/redirect':
                    self.send_response(302);self.send_header('Location','/v1/leak');self.end_headers();return
                self.send_response(200);self.end_headers();self.wfile.write(b'{"data":[{"id":"local"}]}')
            def do_POST(self):
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));calls.append(body)
                self.send_response(200);self.end_headers();self.wfile.write(json.dumps({'choices':[{'message':{'role':'assistant','content':'Готово'},'finish_reason':'stop'}]}).encode())
        server=ThreadingHTTPServer(('127.0.0.1',0),API);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        model=ai.Compatible({'base_url':f'http://localhost:{server.server_port}/v1','model':'local','api_key':'test-key'})
        try:
            self.assertEqual(model.http('models')['data'][0]['id'],'local')
            self.assertEqual(model.answer('Привет'),'Готово');self.assertEqual(calls[-1]['model'],'local')
            with self.assertRaises(bc.ContractError):model.http('redirect')
            self.assertNotIn('/v1/leak',calls)
        finally:server.shutdown();server.server_close();thread.join()
    def test_tool_results_are_sent_back_to_model(self):
        model=ai.Compatible({'base_url':'http://localhost/v1','model':'local'})
        class Draft:
            def call(self,name,args):return {'catalog':'provided'}
        import codex_edits
        name=codex_edits.TOOLS[0]['name'];responses=[{'choices':[{'message':{'tool_calls':[{'id':'t','function':{'name':name,'arguments':'{}'}}]},'finish_reason':'tool_calls'}]}, {'choices':[{'message':{'content':'Ответ'},'finish_reason':'stop'}]}]
        with patch.object(model,'http',side_effect=responses) as http:
            self.assertEqual(model.answer('Запрос',draft=Draft()),'Ответ')
            messages=http.call_args.args[1]['messages'];self.assertEqual(messages[-1]['role'],'tool');self.assertIn('provided',messages[-1]['content'])
    def test_fifo_cancel_and_local_gpu_only(self):
        with tempfile.TemporaryDirectory() as root:
            gpu.admit(root,'a');gpu.admit(root,'b')
            try:
                gpu.admit(root,'c')
                cancel=threading.Event();self.assertTrue(gpu.enter_slot(root,'a',cancel))
                self.assertTrue(gpu.enter_slot(root,'c',cancel))
                cancel.set();self.assertFalse(gpu.enter_slot(root,'b',cancel))
            finally:gpu.release(root,'c');gpu.release(root,'a');gpu.release(root,'b')
            broker=gpu.Broker(root)
            with patch.object(broker,'info',return_value=None):
                with self.assertRaises(bc.ContractError):broker.selected(root)
            with self.assertRaises(bc.ContractError):broker.manage(root,{},'register')

if __name__=='__main__':unittest.main()
