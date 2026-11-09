import codecs
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch

import block_contracts as bc
import data_preview
import kaggle_data as kg
import ml_operations as ml


class EncodingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.patch = patch.object(kg, 'ROOT', self.root)
        self.patch.start()
        self.ref = bc.artifact('dataset', 'kaggle', 'test/encoding')

    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()

    def archive(self, raw):
        path = kg.archive_path('test/encoding')
        path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(path, 'w') as archive:
            archive.writestr('sample.csv', raw)

    def block(self, encoding=None, ref=None):
        return {'kind': 'csv', 'version': 1, 'inputs': {'dataset': ref or self.ref},
                'settings': {} if encoding is None else {'encoding': encoding}}

    def read(self, encoding=None, ref=None):
        return bc.execute({'block': self.block(encoding, ref)}, Mock(), kg, Mock())

    def test_auto_unicode_and_old_schemes(self):
        text = 'слово,класс\nПривет,тест\n'
        for raw in [text.encode('utf-8'), text.encode('utf-8-sig'), text.encode('utf-16'),
                    text.encode('utf-32'), codecs.BOM_UTF16_BE + text.encode('utf-16-be'),
                    codecs.BOM_UTF32_BE + text.encode('utf-32-be')]:
            with self.subTest(prefix=raw[:4]):
                self.archive(raw)
                self.assertEqual(self.read()['outputs']['row'], {'слово': 'Привет', 'класс': 'тест'})

    def test_explicit_encodings_preserve_characters(self):
        for encoding, text in [('cp1251', 'Привет'), ('koi8-r', 'Привет'), ('cp1252', '£20 — café'),
                               ('latin-1', 'café'), ('utf-16-le', 'Привет'), ('utf-16-be', 'Привет')]:
            with self.subTest(encoding=encoding):
                self.archive(('text\n' + text + '\n').encode(encoding))
                self.assertEqual(self.read(encoding)['outputs']['row']['text'], text)
                self.assertEqual(self.read(encoding)['details']['encoding'], encoding)

    def test_encoding_errors_do_not_replace_bad_bytes_or_hide_csv_errors(self):
        self.archive('text\nПривет\n'.encode('cp1251'))
        with self.assertRaisesRegex(bc.ContractError, 'Выберите кодировку'):
            self.read()
        self.archive('text\nhello\n'.encode('utf-16-le'))
        with self.assertRaisesRegex(bc.ContractError, 'нулевые символы'):
            self.read()
        self.archive(b'text\n"unterminated')
        with self.assertRaisesRegex(bc.ContractError, 'разделитель и кавычки'):
            self.read()
        with self.assertRaises(bc.ContractError):
            self.read('invented-codec')

    def test_blank_headers_are_unique_and_preserve_all_columns(self):
        self.archive('v1,v2,,column_3,column_3_2,\nham,café,one,two,three,four\n'.encode('cp1252'))
        result = self.read('cp1252')
        self.assertEqual(result['details']['generated_headers'], ['column_3_3', 'column_6'])
        self.assertEqual(result['outputs']['row'], {'v1': 'ham', 'v2': 'café', 'column_3_3': 'one',
                        'column_3': 'two', 'column_3_2': 'three', 'column_6': 'four'})
        self.archive(b'x,x\n1,2\n')
        with self.assertRaisesRegex(bc.ContractError, 'повторяющиеся'):
            self.read()

    def test_uploaded_unicode_is_not_redecoded_as_legacy_encoding(self):
        ref = ml.save(self.root, 'dataset', {'format': 'architect.uploaded-csv',
            'name': 'example.csv', 'csv': 'text\nПривет\n'})
        for encoding in ('auto', 'cp1251', 'utf-16'):
            self.assertEqual(self.read(encoding, ref)['outputs']['row']['text'], 'Привет')

    def test_preview_uses_the_same_encoding_and_generated_headers(self):
        self.archive('text,\nПривет,да\n'.encode('cp1251'))
        graph = {'format': 'architect', 'version': 3, 'name': 'Test', 'edges': [],
                 'types': [{'id': 'csv_type', 'name': 'CSV', 'color': '#275fe8', 'block': {'kind': 'csv', 'version': 1}}],
                 'nodes': [{'id': 'csv', 'name': 'CSV', 'typeId': 'csv_type', 'x': 0, 'y': 0, 'block': self.block('cp1251')}]}
        result = data_preview.preview({'diagram': graph, 'node_id': 'csv'}, kg)
        self.assertEqual(result['rows'], [{'text': 'Привет', 'column_2': 'да'}])
        self.assertEqual(result['sources'][0]['encoding'], 'cp1251')


if __name__ == '__main__':
    unittest.main()

