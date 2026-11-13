import hashlib
import io
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from test_server import serve
import huggingface_models as hf

COMMIT = 'a' * 40
CONTENTS = {'config.json': b'{"model_type":"bert"}', 'weights/model.safetensors': b'test model weights'}


def metadata():
    return {'repo': 'owner/model', 'commit': COMMIT, 'pipeline': 'fill-mask', 'library': 'transformers', 'license': 'mit',
            'files': [{'name': name, 'size': len(content), 'digest': hashlib.sha256(content).hexdigest(), 'algorithm': 'sha256'}
                      for name, content in CONTENTS.items()]}


class HubTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='.test-huggingface-')
        self.addCleanup(self.temp.cleanup)
        root = patch.object(hf, 'ROOT', Path(self.temp.name))
        root.start(); self.addCleanup(root.stop)
        jobs = patch.object(hf, 'JOBS', {})
        jobs.start(); self.addCleanup(jobs.stop)

    def wait_download(self):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            data = hf.request({'repo': 'owner/model', 'commit': COMMIT}, 'status')
            if data['status'] != 'downloading':
                return data
            time.sleep(.01)
        self.fail('Worker did not finish')

    def start(self, names=None):
        return hf.request({'repo': 'owner/model', 'commit': COMMIT, 'files': names or list(CONTENTS), 'token': 'test-secret'}, 'download')

    def stream(self, path, token):
        name = path.split('/resolve/' + COMMIT + '/', 1)[1]
        return io.BytesIO(CONTENTS[name])

    def test_repo_revision_and_filename_validation(self):
        self.assertEqual(hf.model_id('https://huggingface.co/Owner/model.v2'), 'Owner/model.v2')
        self.assertEqual(hf.model_id('gpt2'), 'gpt2')
        self.assertEqual(hf.revision_id('refs/pr/3'), 'refs/pr/3')
        for value in ('https://evil.test/model', 'https://huggingface.co@evil.test/a/b',
                      'https://huggingface.co/a/b/resolve/main/file', '../private', 'a/b/c', 'datasets/a', 'spaces/a', 'a/..b'):
            with self.subTest(value=value), self.assertRaises(hf.HubError):
                hf.model_id(value)
        for value in ('../a', '/a', 'a//b', 'a\\b', 'a\nb', 'a:b', 'a/./b'):
            with self.subTest(value=value), self.assertRaises(hf.HubError):
                hf.filename(value)
        with self.assertRaises(hf.HubError):
            hf.revision_id('main', pinned=True)

    def test_metadata_contract_and_collisions(self):
        data = {'sha': COMMIT, 'siblings': [{'rfilename': 'config.json', 'size': 5, 'blobId': 'b' * 40},
                {'rfilename': 'weights.safetensors', 'size': 99, 'lfs': {'sha256': 'c' * 64}}],
                'pipeline_tag': 'fill-mask', 'cardData': {'license': 'mit'}}
        with patch.object(hf, 'hub_open', return_value=io.BytesIO(json.dumps(data).encode())) as upstream:
            info = hf.request({'repo': 'owner/model', 'revision': 'refs/pr/3', 'token': 'my-secret'}, 'info')
        self.assertEqual(info['commit'], COMMIT)
        self.assertEqual([f['algorithm'] for f in info['files']], ['git-sha1', 'sha256'])
        self.assertEqual(upstream.call_args.args, ('api/models/owner/model/revision/refs%2Fpr%2F3?blobs=true', 'my-secret'))
        self.assertNotIn('my-secret', json.dumps(info))
        for second in ('CONFIG.json', 'config.json/child'):
            data['siblings'][1]['rfilename'] = second
            with patch.object(hf, 'hub_open', return_value=io.BytesIO(json.dumps(data).encode())), self.assertRaises(hf.HubError):
                hf.model_info('owner/model', 'main', '')
        with patch.object(hf, 'hub_open', return_value=io.BytesIO(b'not json')), self.assertRaises(hf.HubError):
            hf.model_info('owner/model', 'main', '')

    def test_verified_download_cache_and_offline_status(self):
        with patch.object(hf, 'model_info', return_value=metadata()), patch.object(hf, 'hub_open', side_effect=self.stream) as upstream:
            self.assertEqual(self.start()['status'], 'downloading')
            ready = self.wait_download()
            self.assertEqual(ready['status'], 'ready')
            self.assertEqual(len(ready['files']), 2)
            folder = hf.model_folder('owner/model', COMMIT)
            for name, content in CONTENTS.items():
                self.assertEqual((folder / 'files' / name).read_bytes(), content)
            self.assertNotIn('test-secret', (folder / 'manifest.json').read_text())
            self.assertFalse(list(folder.glob('.download-*')))
            hf.JOBS.clear()  # Restart loses transient jobs, not the downloaded files.
            self.start()
            self.assertEqual(self.wait_download()['status'], 'ready')
            self.assertEqual(upstream.call_count, 2, 'Cached weights must not be fetched again')
        with patch.object(hf, 'hub_open') as upstream:
            self.assertEqual(hf.request({'repo': 'owner/model', 'commit': COMMIT}, 'status')['status'], 'ready')
            upstream.assert_not_called()

    def test_incomplete_download_keeps_completed_files_and_retries(self):
        def stream(path, token):
            return io.BytesIO(b'corrupt') if 'safetensors' in path else self.stream(path, token)
        with patch.object(hf, 'model_info', return_value=metadata()), patch.object(hf, 'hub_open', side_effect=stream):
            self.start()
            failed = self.wait_download()
        self.assertEqual(failed['status'], 'error')
        self.assertEqual([item['name'] for item in failed['files']], ['config.json'])
        folder = hf.model_folder('owner/model', COMMIT)
        self.assertFalse((folder / 'files/weights/model.safetensors').exists())
        self.assertFalse(list(folder.glob('.download-*')))
        with patch.object(hf, 'model_info', return_value=metadata()), patch.object(hf, 'hub_open', side_effect=self.stream) as upstream:
            self.start()
            self.assertEqual(self.wait_download()['status'], 'ready')
            upstream.assert_called_once()

    def test_size_and_digest_integrity(self):
        destination = hf.ROOT / 'file.part'
        payload = b'hello'
        item = {'name': 'config.json', 'size': 5, 'algorithm': 'git-sha1', 'digest': hashlib.sha1(b'blob 5\0hello').hexdigest()}
        with patch.object(hf, 'hub_open', return_value=io.BytesIO(payload)):
            hf.download_file('owner/model', COMMIT, item, '', destination, lambda *_: None)
        for payload in (b'world', b'hell', b'hello!'):
            with patch.object(hf, 'hub_open', return_value=io.BytesIO(payload)), self.assertRaises(hf.HubError):
                hf.download_file('owner/model', COMMIT, item, '', destination, lambda *_: None)

    def test_wrong_commit_and_unknown_files(self):
        cases = [(dict(metadata(), commit='b' * 40), None), (metadata(), ['unknown.bin'])]
        for info, names in cases:
            with patch.object(hf, 'model_info', return_value=info), patch.object(hf, 'hub_open') as upstream:
                self.start(names)
                self.assertEqual(self.wait_download()['status'], 'error')
                upstream.assert_not_called()

    def test_symlinks_and_changed_cache_are_not_used(self):
        with patch.object(hf, 'model_info', return_value=metadata()), patch.object(hf, 'hub_open', side_effect=self.stream):
            self.start()
            self.assertEqual(self.wait_download()['status'], 'ready')
        path = hf.model_folder('owner/model', COMMIT) / 'files/config.json'
        path.write_bytes(b'changed')
        self.assertEqual(len(hf.local_status('owner/model', COMMIT)['files']), 1)
        path.unlink()
        path.symlink_to(hf.ROOT / 'outside.json')
        with self.assertRaises(hf.HubError):
            hf.local_status('owner/model', COMMIT)

    def test_concurrent_downloads_do_not_overwrite_jobs(self):
        entered, release = threading.Event(), threading.Event()
        def info(*args):
            entered.set()
            assert release.wait(3)
            return metadata()
        with patch.object(hf, 'model_info', side_effect=info), patch.object(hf, 'hub_open', side_effect=self.stream):
            self.start()
            try:
                self.assertTrue(entered.wait(2))
                with self.assertRaises(hf.HubError) as caught:
                    self.start()
                self.assertEqual(caught.exception.status, 409)
                self.assertNotIn('test-secret', repr(hf.JOBS))
            finally:
                release.set()
                self.assertEqual(self.wait_download()['status'], 'ready')

    def test_redirect_credentials_and_errors(self):
        redirect = hf.HubRedirect()
        request = Request('https://huggingface.co/owner/model/resolve/main/a', headers={'Authorization': 'Bearer secret'})
        same = redirect.redirect_request(request, None, 302, '', {}, 'https://huggingface.co/api/resolve-cache/a')
        self.assertEqual(same.get_header('Authorization'), 'Bearer secret')
        storage = redirect.redirect_request(request, None, 302, '', {}, 'https://cas-bridge.xethub.hf.co/a')
        self.assertIsNone(storage.get_header('Authorization'))
        regional = redirect.redirect_request(request, None, 302, '', {}, 'https://us.aws.cdn.hf.co/a')
        self.assertIsNone(regional.get_header('Authorization'))
        for url in ('http://huggingface.co/a', 'https://huggingface.co.evil.test/a', 'https://user@huggingface.co/a',
                    'https://us.aws.cdn.hf.co.evil.test/a', 'https://evil@us.aws.cdn.hf.co/a'):
            with self.assertRaises(hf.HubError):
                redirect.redirect_request(request, None, 302, '', {}, url)
        for code in (401, 403, 404, 429, 500):
            error = HTTPError('https://huggingface.co/private', code, 'secret', {}, io.BytesIO(b'secret'))
            with patch.object(hf, 'build_opener') as builder:
                builder.return_value.open.side_effect = error
                with self.assertRaises(hf.HubError) as caught:
                    hf.hub_open('api/models/owner/model', 'secret')
                self.assertNotIn('secret', str(caught.exception))
                self.assertEqual(caught.exception.status, code if code != 500 else 502)


class HubHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = serve.ThreadingHTTPServer(('127.0.0.1', 0), serve.Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f'http://127.0.0.1:{cls.server.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.thread.join()

    def test_routes_reject_other_origins_and_do_not_expose_files(self):
        for action in ('info', 'download', 'status'):
            with patch.object(hf, 'request', return_value={'status': 'missing'}) as handler:
                request = Request(self.url + '/api/huggingface/' + action, data=b'{"repo":"owner/model"}',
                                  headers={'Content-Type': 'application/json', 'X-Architect-Request': '1'})
                with urlopen(request) as response:
                    self.assertEqual(json.load(response), {'status': 'missing'})
                handler.assert_called_once_with({'repo': 'owner/model'}, action)
                request.add_header('Origin', 'https://evil.test')
                with self.assertRaises(HTTPError) as caught:
                    urlopen(request)
                self.assertEqual(caught.exception.code, 403)
                caught.exception.close()
                handler.assert_called_once()
        for path in ('/huggingface_models.py', '/workspace/models/huggingface/model/config.json'):
            with self.assertRaises(HTTPError) as caught:
                urlopen(self.url + path)
            self.assertEqual(caught.exception.code, 404)
            caught.exception.close()

    def test_validation_error_is_json(self):
        request = Request(self.url + '/api/huggingface/info', data=b'{"repo":"../bad"}',
                          headers={'Content-Type': 'application/json', 'X-Architect-Request': '1'})
        with self.assertRaises(HTTPError) as caught:
            urlopen(request)
        with caught.exception as response:
            self.assertEqual(response.code, 400)
            self.assertIn('error', json.load(response))

