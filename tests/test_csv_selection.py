import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch

import block_contracts as bc
import kaggle_data as kg
import ml_operations as ml


class CSVSelectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.patch = patch.object(kg, 'ROOT', self.root)
        self.patch.start()
        self.ref = bc.artifact('dataset', 'kaggle', 'owner/data')

    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()

    def archive(self, names):
        path = kg.archive_path('owner/data')
        path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(path, 'w') as archive:
            for name in names:
                archive.writestr(name, 'text,label\nhello,one\n')

    def read(self, name='', ref=None):
        block = {'kind': 'csv', 'version': 1, 'inputs': {'dataset': ref or self.ref, 'file': name}}
        return bc.execute({'block': block}, Mock(), kg, Mock())

    def test_auto_selects_exact_nested_name_and_preserves_explicit_selection(self):
        self.archive(['данные/Обучение.CSV', 'README.txt'])
        result = self.read()
        self.assertEqual(result['details']['file'], 'данные/Обучение.CSV')
        self.assertEqual(result['outputs']['row'], {'text': 'hello', 'label': 'one'})
        self.archive(['train.csv', 'test.csv'])
        self.assertEqual(self.read('test.csv')['details']['file'], 'test.csv')

    def test_ambiguous_missing_and_wrong_case_report_real_names_without_guessing(self):
        self.archive(['nested/Train.csv', 'test.csv'])
        for name in ('', 'train.csv', 'nested/train.csv', '../../train.csv'):
            with self.subTest(name=name), self.assertRaises(bc.ContractError) as error:
                self.read(name)
            self.assertIn('nested/Train.csv', str(error.exception))
            self.assertIn('test.csv', str(error.exception))
        self.archive(['nested/Train.csv'])
        with self.assertRaises(bc.ContractError):
            self.read('wrong.csv')
        self.archive(['README.txt'])
        with self.assertRaisesRegex(bc.ContractError, 'нет файлов с расширением'):
            self.read()

    def test_uploaded_csv_uses_stored_name_and_rejects_wrong_explicit_name(self):
        ref = ml.save(self.root, 'dataset', {'format': 'architect.uploaded-csv',
                                           'name': 'Мой файл.csv', 'csv': 'text\nhello\n'})
        self.assertEqual(self.read(ref=ref)['details']['file'], 'Мой файл.csv')
        with self.assertRaisesRegex(bc.ContractError, 'Мой файл.csv'):
            self.read('train.csv', ref)


if __name__ == '__main__':
    unittest.main()

