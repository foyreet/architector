import json
import http.client
import os
import sys
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import block_contracts as bc
import codex_chat as chat
import codex_edits
import project_store as ps
import serve


class ChatTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.user = {'id': 'alice', 'username': 'alice', 'primary': True}
        self.connection = SimpleNamespace(status=lambda: {'connected': True}, answer=lambda prompt: 'Ответ Codex')
        self.factory = patch.object(chat, 'client', return_value=self.connection)
        self.factory.start()

    def tearDown(self):
        for _ in range(100):
            if not chat.JOBS: break
            time.sleep(.01)
        self.factory.stop()
        self.temp.cleanup()

    def call(self, action, body=None, root=None):
        return chat.request(root or self.root, self.user, body or {}, action)

    def finished(self):
        for _ in range(100):
            result = self.call('history')
            if not result['pending']: return result
            time.sleep(.01)
        self.fail('Chat worker did not finish')

    def test_login_required_and_no_arbitrary_rpc_or_account_fields(self):
        self.assertFalse(chat.request(self.root, None, {}, 'status')['connected'])
        for body in ({'root': '/tmp'}, {'threadId': 'someone-else'}, {'api_key': 'secret'}):
            with self.assertRaises(bc.ContractError): self.call('send', body)
        with self.assertRaises(bc.ContractError): self.call('account/login/start')

    def test_history_survives_and_is_isolated_by_account_root(self):
        self.call('send', {'message': 'Привет', 'include_context': False})
        record = self.finished()
        self.assertEqual([m['text'] for m in record['messages']], ['Привет', 'Ответ Codex'])
        other = self.root / 'other-account'
        self.assertEqual(self.call('history', root=other)['messages'], [])
        with self.assertRaises(bc.ContractError):
            self.call('history', {'project_id': '../../private'})
        with self.assertRaises(bc.ContractError):
            self.call('history', {'project_id': '00000000-0000-4000-8000-000000000000'})

    def test_context_opt_out_and_no_automatic_retry(self):
        calls = []
        def answer(prompt):
            calls.append(json.loads(prompt))
            raise OSError('do not expose a secret')
        self.connection.answer = answer
        self.call('send', {'message': 'Объясни', 'diagram': {'secret': 'not sent'}, 'include_context': False})
        record = self.finished()
        self.assertIsNone(calls[0]['context'])
        self.assertEqual(len(calls), 1)
        self.assertNotIn('secret', record['error'])
        self.assertEqual(len(record['messages']), 1)
        self.assertIsNone(record['pending'])

    def test_pending_job_blocks_duplicate_send_clear_and_logout(self):
        gate = threading.Event()
        self.connection.answer = lambda prompt: (gate.wait(3), 'Готово')[1]
        try:
            self.call('send', {'message': 'Привет', 'include_context': False})
            for action in ('send', 'clear', 'logout'):
                with self.assertRaises(bc.ContractError) as error:
                    self.call(action, {'message': 'Повтор'})
                self.assertEqual(error.exception.status, 409)
        finally: gate.set()
        self.finished()

    def test_interrupted_job_does_not_repeat(self):
        store = ps.ProjectStore(self.root)
        store.write('workspace/codex/chats/general.json', {'messages': [], 'pending': 'old', 'error': ''})
        record = self.call('history')
        self.assertIsNone(record['pending'])
        self.assertIn('остановлен', record['error'])

    def test_environment_does_not_inherit_owner_secrets(self):
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'owner', 'CODEX_HOME': '/owner',
                                    'OPENAI_ACCESS_TOKEN': 'owner', 'ARCHITECT_MCP_TOKEN': 'owner'}):
            env = chat.process_environment(self.root)
        self.assertEqual(env['CODEX_HOME'], str(self.root))
        self.assertNotIn('OPENAI_API_KEY', env)
        self.assertNotIn('OPENAI_ACCESS_TOKEN', env)
        self.assertNotIn('ARCHITECT_MCP_TOKEN', env)

    def test_no_credentials_means_no_send(self):
        self.connection.status = lambda: {'connected': False}
        with self.assertRaises(bc.ContractError) as error:
            self.call('send', {'message': 'Привет'})
        self.assertEqual(error.exception.status, 401)
        self.assertEqual(self.call('history')['messages'], [])

    def test_project_context_and_history_cannot_cross_accounts(self):
        diagram = {'format': 'architect', 'version': 4, 'name': 'Alice', 'types': [], 'nodes': [], 'edges': [], 'definitions': []}
        project = ps.ProjectStore(self.root).save({'diagram': diagram, 'name': 'Alice', 'description': 'Мой проект'}, create=True)
        identity = project['project']['id']
        prompt = chat.build_prompt(ps.ProjectStore(self.root), {'project_id': identity}, {'messages': []}, 'Объясни')
        self.assertEqual(json.loads(prompt)['context']['description'], 'Мой проект')
        with self.assertRaises(bc.ContractError): self.call('history', {'project_id': identity}, root=self.root / 'bob')

    def test_http_routes_keep_session_origin_and_account_guards(self):
        with patch.object(ps, 'ROOT', self.root), patch('local_workspace.Community.session', return_value=self.user) as session:
            server = serve.ThreadingHTTPServer(('127.0.0.1', 0), serve.Handler)
            worker = threading.Thread(target=server.serve_forever, daemon=True); worker.start()
            def request(action, body=None, **extra):
                connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=5)
                headers = {'Content-Type':'application/json', 'X-Architect-Request':'1', 'X-Architect-Account':'alice', **extra}
                connection.request('POST', '/api/codex/' + action, json.dumps(body or {}), headers)
                response = connection.getresponse()
                result = response.status, json.loads(response.read())
                connection.close()
                return result
            try:
                self.assertEqual(request('history')[0], 200)
                self.assertEqual(request('history', **{'Origin':'https://untrusted.example'})[0], 403)
                self.assertEqual(request('history', **{'X-Architect-Account':'bob'})[0], 409)
                self.assertEqual(request('history', **{'X-Architect-Request':'0'})[0], 403)
                self.assertEqual(request('send', {'message':'Привет', 'include_context':False})[0], 200)
                self.finished()
                self.assertEqual(len(request('history')[1]['messages']), 2)
            finally:
                server.shutdown(); server.server_close(); worker.join()

    def test_official_rpc_transport_login_and_response_events(self):
        # A real subprocess checks request framing, response dispatch and notifications.
        script = self.root / 'fake-codex'
        script.write_text('#!' + sys.executable + '\n' + '''import json, sys
def send(value): print(json.dumps(value), flush=True)
logged = False
tools = []
for line in sys.stdin:
    req = json.loads(line); method = req.get('method'); identity = req.get('id')
    if identity is None: continue
    if method is None:
        if identity == 'edit-request':
            assert req['result']['success'] is True
            assert req['result']['contentItems'][0]['type'] == 'inputText'
            send({'method':'item/completed','params':{'threadId':'test-thread','item':{'type':'agentMessage','text':'Правки подготовлены'}}})
            send({'method':'turn/completed','params':{'threadId':'test-thread','turn':{'status':'completed'}}})
        elif identity in ('untrusted-tool', 'wrong-thread'):
            assert req['error']['code'] == -32601
        continue
    result = {}
    if method == 'account/read': result = {'account': {'type': 'chatgpt', 'planType': 'plus'} if logged else None}
    if method == 'account/login/start':
        result = {'type':'chatgptDeviceCode','loginId':'test-login','verificationUrl':'https://auth.openai.com/codex/device','userCode':'TEST-ONLY'}
    if method == 'account/logout': logged = False
    if method == 'thread/start':
        assert req['params']['approvalPolicy'] == 'never'
        assert req['params']['environments'] == []
        assert req['params']['config']['features.shell_tool'] is False
        tools = req['params']['dynamicTools']
        assert all(t['type'] == 'function' and 'inputSchema' in t for t in tools)
        result = {'thread': {'id':'test-thread'}}
    send({'id': identity, 'result': result})
    if method == 'account/login/start':
        logged = True
        send({'method':'account/login/completed','params':{'success':True}})
    if method == 'turn/start':
        send({'id':'untrusted-tool','method':'item/tool/call','params':{'tool':'shell'}})
        if tools:
            send({'id':'wrong-thread','method':'item/tool/call','params':{'threadId':'other-thread','tool':'diagram_read','arguments':{}}})
            send({'id':'edit-request','method':'item/tool/call','params':{'threadId':'test-thread','turnId':'turn','callId':'call','tool':'diagram_add_blocks','arguments':{'blocks':[{'id':'example','kind':'note'}]}}})
            continue
        send({'method':'item/completed','params':{'threadId':'test-thread','item':{'type':'agentMessage','text':'Проверенный ответ'}}})
        send({'method':'turn/completed','params':{'threadId':'test-thread','turn':{'status':'completed'}}})
''', encoding='utf-8')
        script.chmod(0o700)
        with patch.dict(os.environ, {'ARCHITECT_CODEX_BIN': str(script)}):
            connection = chat.Client(self.root)
            try:
                self.assertFalse(connection.status()['connected'])
                connection.start_login()
                self.assertTrue(connection.status()['connected'])
                self.assertEqual(connection.answer('Привет'), 'Проверенный ответ')
                draft = codex_edits.Draft({'format': 'architect', 'version': 3, 'name': 'Тест', 'types': [], 'nodes': [], 'edges': []})
                self.assertEqual(connection.answer('Создай схему', draft=draft), 'Правки подготовлены')
                self.assertEqual(draft.graph['nodes'][0]['id'], 'example')
                connection.rpc('account/logout')
                self.assertFalse(connection.status()['connected'])
            finally: connection.close()


if __name__ == '__main__': unittest.main()

