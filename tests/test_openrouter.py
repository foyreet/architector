import io
import json
import os
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from test_server import serve


class OpenRouterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = serve.ThreadingHTTPServer(('127.0.0.1', 0), serve.Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f'http://127.0.0.1:{cls.server.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.thread.join()

    def post(self, body, path='/api/openrouter/chat', headers=None):
        request = Request(self.url + path, data=json.dumps(body).encode(), headers={
            'Content-Type': 'application/json', 'X-Architect-Request': '1', 'Origin': self.url, **(headers or {})})
        try:
            response = urlopen(request)
        except HTTPError as error:
            response = error
        with response:
            return response.code, json.load(response)

    def body(self):
        return dict(api_key='test-secret-not-real', model='provider/model', prompt='Hello', system='Be brief', max_tokens=128, temperature=0.2)

    def test_chat_contract_and_credentials(self):
        reply = {'model': 'provider/model', 'choices': [{'message': {'content': '<b>answer</b>'}, 'finish_reason': 'stop'}],
                 'usage': {'prompt_tokens': 5, 'completion_tokens': 7, 'total_tokens': 12, 'cost': 0.001, 'internal': 'hidden'}}
        with patch.object(serve, 'provider_request', return_value=reply) as upstream:
            code, data = self.post(self.body())
        self.assertEqual(code, 200)
        self.assertEqual(data['text'], '<b>answer</b>')
        self.assertNotIn('internal', data['usage'])
        self.assertNotIn('test-secret', json.dumps(data))
        path, key, payload = upstream.call_args.args
        self.assertEqual(path, 'chat/completions'); self.assertEqual(key, 'test-secret-not-real')
        self.assertEqual(payload['messages'], [{'role': 'system', 'content': 'Be brief'}, {'role': 'user', 'content': 'Hello'}])
        self.assertFalse(payload['stream']); self.assertNotIn('api_key', payload)

    def test_untrusted_origins_and_hosts_cannot_spend_key(self):
        with patch.object(serve, 'provider_request') as upstream:
            for headers in [{'Origin': 'https://untrusted.example'}, {'Host': 'untrusted.example'}, {'X-Architect-Request': ''}, {'Sec-Fetch-Site': 'cross-site'}]:
                with self.subTest(headers=headers):
                    code, _ = self.post(self.body(), headers=headers)
                    self.assertEqual(code, 403)
            upstream.assert_not_called()

    def test_missing_key_and_invalid_input_do_not_call_provider(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(serve, 'provider_request') as upstream:
            cases = [(dict(self.body(), api_key=''), 401), (dict(self.body(), prompt=' '), 400),
                     (dict(self.body(), temperature=float('nan')), 400), (dict(self.body(), max_tokens=True), 400),
                     (dict(self.body(), model='bad model'), 400), (dict(self.body(), base_url='http://example.com'), 400),
                     (dict(self.body(), api_key='bad\nkey'), 400)]
            for body, expected in cases:
                code, _ = self.post(body)
                self.assertEqual(code, expected)
            upstream.assert_not_called()

    def test_server_key_is_never_returned(self):
        with patch.dict(os.environ, {'OPENROUTER_API_KEY': 'server-test-secret'}):
            with urlopen(self.url + '/api/openrouter/status') as response:
                self.assertEqual(json.load(response), {'server_key': True})
            self.assertEqual(serve.api_key({}), 'server-test-secret')
            self.assertEqual(serve.api_key({'api_key': 'tab-secret'}), 'tab-secret')

    def test_catalog_filters_non_text_output(self):
        with patch.object(serve, 'provider_request', return_value={'data': [
            {'id': 'text/model', 'name': 'Text', 'architecture': {'output_modalities': ['text']}},
            {'id': 'image/model', 'architecture': {'output_modalities': ['image']}}]}):
            code, data = self.post({}, '/api/openrouter/models')
        self.assertEqual(code, 200)
        self.assertEqual(data, {'models': [{'id': 'text/model', 'name': 'Text'}]})

    def test_upstream_errors_are_safe_and_never_retried(self):
        for code in (401, 402, 429, 500):
            error = HTTPError('https://openrouter.ai/api/v1/chat/completions', code, 'private provider detail', {}, io.BytesIO(b'secret'))
            with patch.object(serve, 'build_opener') as builder:
                builder.return_value.open.side_effect = error
                with self.assertRaises(serve.ApiError) as caught:
                    serve.provider_request('chat/completions', 'test-secret', {})
                self.assertEqual(caught.exception.status, code if code != 500 else 502)
                self.assertNotIn('secret', str(caught.exception))
                builder.return_value.open.assert_called_once()

    def test_timeout_and_network_error(self):
        for error, status in [(TimeoutError(), 504), (URLError('private error'), 502)]:
            with patch.object(serve, 'build_opener') as builder:
                builder.return_value.open.side_effect = error
                with self.assertRaises(serve.ApiError) as caught:
                    serve.provider_request('chat/completions', 'test-secret', {})
                self.assertEqual(caught.exception.status, status)

    def test_malformed_and_embedded_error(self):
        for value in ({}, {'choices': []}, {'choices': [{'message': {'content': None}}]}, {'choices': [{'message': {'content': ''}, 'finish_reason': 'stop'}]}):
            with patch.object(serve, 'provider_request', return_value=value):
                code, data = self.post(self.body())
                self.assertEqual(code, 502)
        with patch.object(serve, 'build_opener') as builder:
            builder.return_value.open.return_value.__enter__.return_value.read.return_value = b'{"error":{"code":402,"message":"secret"}}'
            with self.assertRaises(serve.ApiError) as caught:
                serve.provider_request('chat/completions', 'test-secret', {})
            self.assertEqual(caught.exception.status, 402)
            self.assertNotIn('secret', str(caught.exception))

    def test_redirects_are_not_followed(self):
        self.assertIsNone(serve.NoRedirect().redirect_request(None, None, 307, '', {}, 'https://other.example'))

