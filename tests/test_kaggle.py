import io
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import zipfile

from test_server import serve
import kaggle_data as kg


class KaggleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='.test-kaggle-')
        self.root = patch.object(kg, 'ROOT', Path(self.temp.name))
        self.root.start()
        self.jobs = patch.object(kg, 'JOBS', {})
        self.jobs.start()
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.root.stop)
        self.addCleanup(self.jobs.stop)

    def archive(self, path=None, files=None):
        path = path or kg.archive_path('owner/dataset')
        path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as archive:
            for name, content in (files or {'nested/train.csv': 'name;value\n<script>alert(1)</script>;42\n',
                                          'readme.txt': 'Пример', 'image.png': b'\x89PNG'}).items():
                archive.writestr(name, content)
        return path

    def wait_download(self, dataset='owner/dataset'):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            result = kg.request({'dataset': dataset}, 'files')
            if result['status'] != 'downloading':
                return result
            time.sleep(.01)
        self.fail('Download worker did not finish')

    def test_handles_and_reject_arbitrary_destinations(self):
        self.assertEqual(kg.dataset_handle('https://www.kaggle.com/datasets/Owner/Data/versions/2?select=a.csv'), 'owner/data/versions/2')
        for value in ('../secrets', 'owner/../name', 'https://evil.test/datasets/a/b',
                      'https://www.kaggle.com@evil.test/datasets/a/b', 'https://www.kaggle.com/competitions/test',
                      'https://www.kaggle.com:443/datasets/a/b', 'owner/%2e%2e', None, 'a/b/versions/0'):
            with self.subTest(value=value), self.assertRaises(kg.KaggleError):
                kg.dataset_handle(value)

    def test_local_files_and_full_preview(self):
        self.archive()
        data = kg.request({'dataset': 'owner/dataset'}, 'files')
        self.assertEqual(data['status'], 'ready')
        self.assertEqual(data['path'], 'workspace/datasets/owner/dataset/latest/dataset.zip')
        self.assertEqual(len(data['files']), 3)
        preview = kg.preview('owner/dataset', 'nested/train.csv')
        self.assertEqual(preview['rows'], [['name', 'value'], ['<script>alert(1)</script>', '42']])
        self.assertEqual(kg.preview('owner/dataset', 'readme.txt')['text'], 'Пример')
        self.assertEqual(kg.preview('owner/dataset', 'image.png')['kind'], 'unsupported')
        with self.assertRaises(kg.KaggleError):
            kg.preview('owner/dataset', '../../serve.py')
        self.archive(files={'large.csv': 'a,b\n' * 100, 'large.txt': 'x' * (65536 + 50)})
        self.assertEqual(len(kg.preview('owner/dataset', 'large.csv')['rows']), 100)
        self.assertFalse(kg.preview('owner/dataset', 'large.csv')['truncated'])
        self.assertEqual(len(kg.preview('owner/dataset', 'large.txt')['text']), 65536 + 50)
        self.assertFalse(kg.preview('owner/dataset', 'large.txt')['truncated'])

    def test_async_download_deduplicates_and_recovers_from_reload(self):
        entered, release = threading.Event(), threading.Event()
        def download(handle, token, destination, progress):
            self.assertEqual(token, 'private-test-token')
            entered.set()
            if not release.wait(3):
                raise RuntimeError('test wait expired')
            self.archive(destination)
            progress(100, 100)
        with patch.object(kg, 'download_archive', side_effect=download) as upstream:
            try:
                result = kg.request({'dataset': 'owner/dataset', 'token': 'private-test-token'}, 'download')
                self.assertEqual(result['status'], 'downloading')
                self.assertTrue(entered.wait(2))
                self.assertEqual(kg.request({'dataset': 'owner/dataset'}, 'download')['status'], 'downloading')
                second = kg.request({'dataset': 'owner/another', 'token': 'private-test-token'}, 'download')
                self.assertEqual(second['status'], 'downloading')
                self.assertNotIn('private-test-token', json.dumps(kg.JOBS))
            finally:
                release.set()
                ready = self.wait_download()
                self.assertEqual(self.wait_download('owner/another')['status'], 'ready')
            self.assertEqual(ready['status'], 'ready')
            kg.JOBS.clear()  # Simulates a new server process.
            self.assertEqual(kg.request({'dataset': 'owner/dataset'}, 'download')['status'], 'ready')
            self.assertEqual(upstream.call_count, 2)
            self.assertFalse(list(kg.ROOT.rglob('.download-*')))

    def test_failed_download_is_clean_and_retryable(self):
        def fail(handle, token, destination, progress):
            destination.write_bytes(b'partial')
            raise RuntimeError('secret URL and private token')
        with patch.object(kg, 'download_archive', side_effect=fail):
            kg.request({'dataset': 'owner/dataset'}, 'download')
            failed = self.wait_download()
        self.assertEqual(failed['status'], 'error')
        self.assertNotIn('secret', json.dumps(failed))
        self.assertFalse(kg.archive_path('owner/dataset').exists())
        self.assertFalse(list(kg.ROOT.rglob('.download-*')))
        with patch.object(kg, 'download_archive', side_effect=lambda h, t, p, cb: self.archive(p)):
            kg.request({'dataset': 'owner/dataset'}, 'download')
            self.assertEqual(self.wait_download()['status'], 'ready')

    def test_unsafe_and_oversized_archives(self):
        for name in ('../escape.txt', '/absolute.csv', 'folder\\escape.csv'):
            self.archive(files={name: 'bad'})
            with self.subTest(name=name), self.assertRaises(kg.KaggleError):
                kg.local_files('owner/dataset')

    def test_symlinks_cannot_leave_storage(self):
        (kg.ROOT / 'workspace').symlink_to(kg.ROOT.parent, target_is_directory=True)
        with self.assertRaises(kg.KaggleError):
            kg.request({'dataset': 'owner/dataset'}, 'download')

    def test_redirect_does_not_forward_token_and_rejects_external_hosts(self):
        redirect = kg.KaggleRedirect()
        original = Request('https://www.kaggle.com/api/v1/datasets/download/a/b', headers={'Authorization': 'Bearer secret'})
        redirected = redirect.redirect_request(original, None, 302, '', {}, 'https://storage.googleapis.com:443/bucket/file?signature=test')
        self.assertIsNone(redirected.get_header('Authorization'))
        for url in ('http://storage.googleapis.com/a', 'https://evil.test/a', 'https://storage.googleapis.com.evil.test/a', 'https://user@storage.googleapis.com/a'):
            with self.assertRaises(kg.KaggleError):
                redirect.redirect_request(original, None, 302, '', {}, url)

    def test_network_contract_limits_and_errors(self):
        destination = kg.ROOT / 'download.zip'
        for code in (401, 403, 404, 429, 500):
            error = HTTPError('https://www.kaggle.com/private', code, 'secret', {}, io.BytesIO(b'secret'))
            with patch.object(kg, 'build_opener') as builder:
                builder.return_value.open.side_effect = error
                with self.assertRaises(kg.KaggleError) as caught:
                    kg.download_archive('owner/dataset', 'secret', destination, lambda *_: None)
                self.assertNotIn('secret', str(caught.exception))
                self.assertEqual(caught.exception.status, code if code != 500 else 502)
        with patch.object(kg, 'build_opener') as builder:
            response = builder.return_value.open.return_value.__enter__.return_value
            response.headers = {}
            response.read.side_effect = [b'1234', b'']
            kg.download_archive('owner/dataset/versions/2', 'secret', destination, lambda *_: None)
            self.assertEqual(destination.read_bytes(), b'1234')
            request = builder.return_value.open.call_args.args[0]
            self.assertEqual(request.full_url, 'https://www.kaggle.com/api/v1/datasets/download/owner/dataset?datasetVersionNumber=2')
            self.assertEqual(request.get_header('Authorization'), 'Bearer secret')


class KaggleHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = serve.ThreadingHTTPServer(('127.0.0.1', 0), serve.Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f'http://127.0.0.1:{cls.server.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def test_routes_and_origin_checks(self):
        for action in ('download', 'files', 'preview'):
            body = {'dataset': 'owner/dataset'}
            with patch.object(kg, 'request', return_value={'status': 'missing'}) as handler:
                request = Request(self.url + '/api/kaggle/' + action, data=json.dumps(body).encode(),
                                  headers={'Content-Type': 'application/json', 'X-Architect-Request': '1'})
                with urlopen(request) as response:
                    self.assertEqual(json.load(response), {'status': 'missing'})
                handler.assert_called_once_with(body, action)
                request.add_header('Origin', 'https://evil.test')
                with self.assertRaises(HTTPError) as caught:
                    urlopen(request)
                self.assertEqual(caught.exception.code, 403)
                caught.exception.close()
                handler.assert_called_once()

    def test_validation_errors_are_json(self):
        request = Request(self.url + '/api/kaggle/download', data=b'{"dataset":"../bad"}',
                          headers={'Content-Type': 'application/json', 'X-Architect-Request': '1'})
        with self.assertRaises(HTTPError) as caught:
            urlopen(request)
        self.assertEqual(caught.exception.code, 400)
        with caught.exception as response:
            self.assertIn('error', json.load(response))

