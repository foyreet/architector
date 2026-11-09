"""Catalog and request settings; no live inference or account access."""
import queue
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch
import codex_chat as chat
import block_contracts as bc
from tests.test_codex_chat import ChatTests


class ModelRequestTests(ChatTests):
    def test_selected_settings_and_validation(self):
        self.connection.models = lambda: [{'id': 'model-a', 'default': True, 'efforts': ['low', 'high']}]
        calls = []
        self.connection.answer = lambda prompt, **options: (calls.append(options), 'Ответ')[1]
        for options in ({'model': 'missing'}, {'model': 'model-a', 'effort': 'ultra'}, {'effort': 3}):
            with self.assertRaises(bc.ContractError): self.call('send', {'message': 'test', **options})
        self.assertEqual(self.call('history')['messages'], [])
        self.call('send', {'message': 'test', 'include_context': False, 'effort': 'high'})
        self.finished()
        self.assertEqual(calls, [{'model': 'model-a', 'effort': 'high'}])
        self.assertEqual(self.call('models')['models'][0]['id'], 'model-a')


class ModelProtocolTests(TestCase):
    def test_catalog_pagination_filtering_and_cache_copy(self):
        client = object.__new__(chat.Client)
        pages = [{'data': [{'model': 'a', 'displayName': 'A', 'isDefault': True, 'defaultReasoningEffort': 'high', 'supportedReasoningEfforts': [{'reasoningEffort': 'high'}]}, {'model': 'secret', 'hidden': True}], 'nextCursor': 'next'}, {'data': [{'model': 'a'}, {'model': 'b', 'inputModalities': ['image']}]}]
        with patch.object(client, 'rpc', side_effect=pages) as rpc:
            result = client.models()
            self.assertEqual([m['id'] for m in result], ['a'])
            self.assertEqual(result[0]['efforts'], ['high'])
            result[0]['id'] = 'changed'
            self.assertEqual(client.models()[0]['id'], 'a')
            self.assertEqual(rpc.call_count, 2)
            self.assertEqual(rpc.call_args.args[1]['cursor'], 'next')

    def test_protocol_forwards_model_and_effort(self):
        client = object.__new__(chat.Client); client.events = queue.Queue(); client.work = Path('/tmp')
        calls = []
        def rpc(method, params, **kwargs):
            calls.append((method, params))
            if method == 'thread/start': return {'thread': {'id': 't'}}
            if method == 'turn/start':
                client.events.put({'method': 'item/completed', 'params': {'threadId': 't', 'item': {'type': 'agentMessage', 'text': 'ok'}}})
                client.events.put({'method': 'turn/completed', 'params': {'threadId': 't', 'turn': {'status': 'completed'}}})
            return {}
        client.rpc = rpc
        self.assertEqual(client.answer('hello', model='a', effort='high'), 'ok')
        self.assertEqual(calls[0][1]['model'], 'a')
        self.assertEqual(calls[1][1]['model'], 'a')
        self.assertEqual(calls[1][1]['effort'], 'high')

