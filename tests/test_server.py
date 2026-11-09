import importlib.util
from pathlib import Path
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('serve', ROOT / 'serve.py')
serve = importlib.util.module_from_spec(spec)
spec.loader.exec_module(serve)


class ServerTests(unittest.TestCase):
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

    def test_editor_assets_and_no_external_connections(self):
        for path, mime in [('/', 'text/html'), ('/architecture.html', 'text/html'),
                           ('/architecture.js', 'text/javascript'), ('/architecture.css', 'text/css'),
                           ('/learning.js', 'text/javascript'), ('/learning.css', 'text/css')]:
            with self.subTest(path=path), urlopen(self.url + path) as response:
                self.assertEqual(response.status, 200)
                self.assertIn(mime, response.headers['Content-Type'])
                self.assertIn("connect-src 'self'", response.headers['Content-Security-Policy'])
                self.assertTrue(response.read())

    def test_link_from_another_site_opens_the_editor_page_only(self):
        navigation = {'Sec-Fetch-Site': 'cross-site', 'Sec-Fetch-Mode': 'navigate', 'Sec-Fetch-Dest': 'document'}
        for path in ('/', '/architecture.html?practice=first-pipeline'):
            with self.subTest(path=path), urlopen(Request(self.url + path, headers=navigation)) as response:
                self.assertEqual(response.status, 200)
                self.assertIn("frame-ancestors 'none'", response.headers['Content-Security-Policy'])
        rejected = [('/architecture.js', navigation),
                    ('/architecture.html', {'Sec-Fetch-Site': 'cross-site', 'Sec-Fetch-Mode': 'no-cors', 'Sec-Fetch-Dest': 'iframe'}),
                    ('/architecture.html', {'Sec-Fetch-Site': 'cross-site', 'Sec-Fetch-Mode': 'cors', 'Sec-Fetch-Dest': 'empty'})]
        for path, headers in rejected:
            with self.subTest(path=path, headers=headers), self.assertRaises(HTTPError) as error:
                urlopen(Request(self.url + path, headers=headers))
            self.assertEqual(error.exception.code, 403)
            error.exception.close()

    def test_old_integrations_and_private_files_are_not_served(self):
        for path in ['/api/architecture/config', '/api/architecture/run', '/api/architecture/training/models',
                     '/serve.py', '/README.md', '/logs/architect.log', '/workspace/state.json',
                     '/../serve.py', '/%2e%2e/serve.py']:
            with self.subTest(path=path), self.assertRaises(HTTPError) as error:
                urlopen(self.url + path)
            self.assertEqual(error.exception.code, 404)
            error.exception.close()


if __name__ == '__main__':
    unittest.main()

