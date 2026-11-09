from copy import deepcopy
from pathlib import Path
import tempfile
import json
import time
from types import SimpleNamespace
from unittest.mock import patch
import unittest
import zipfile

import block_contracts as bc
import codex_edits
import codex_chat
import ml_operations
import kaggle_data as kg
import project_store as ps
from test_codex_edits import empty


class CSVInspectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = ps.ProjectStore(Path(self.temp.name))
        self.draft = codex_edits.Draft(empty(), self.store)
        self.draft.call('diagram_add_blocks', {'blocks': [
            {'id': 'source', 'kind': 'kaggle', 'inputs': {'source': 'test/encoding'}},
            {'id': 'csv', 'kind': 'csv'}]})
        self.draft.call('diagram_connect', {'connections': [
            {'from': 'source', 'to': 'csv', 'from_port': 'dataset', 'to_port': 'dataset'}]})
        self.path = kg.archive_path('test/encoding', root=self.store.root)
        self.path.parent.mkdir(parents=True)

    def tearDown(self):
        self.temp.cleanup()

    def archive(self, raw):
        with zipfile.ZipFile(self.path, 'w') as archive:
            archive.writestr('sample.csv', raw)

    def test_evidence_enables_proposal_without_changing_live_graph(self):
        self.archive('v1,v2,,,\nham,Claim £20 — today!,,,\n'.encode('cp1252'))
        before = deepcopy(self.draft.graph)
        value = self.draft.call('diagram_csv_inspect', {'node_id': 'csv'})
        self.assertEqual(self.draft.graph, before)
        self.assertIsNone(value['recommended_encoding'])
        windows = next(c for c in value['candidates'] if c['encoding'] == 'cp1252')
        latin = next(c for c in value['candidates'] if c['encoding'] == 'latin-1')
        self.assertEqual(windows['control_characters'], 0)
        self.assertGreater(latin['control_characters'], 0)
        self.assertIn('£20 — today', windows['sample_rows'][0][1])
        self.assertEqual(windows['generated_headers'], ['column_3', 'column_4', 'column_5'])
        self.draft.call('diagram_update_blocks', {'blocks': [{'id': 'csv', 'settings': {'encoding': 'cp1252'}}]})
        self.assertTrue(self.draft.check()['ready'])

    def test_unicode_is_unambiguous_and_samples_are_bounded(self):
        self.archive(('text\n' + 'Привет ' * 1000 + '\n').encode('utf-16'))
        value = self.draft.call('diagram_csv_inspect', {'node_id': 'csv'})
        self.assertEqual(value['recommended_encoding'], 'auto')
        self.assertEqual(len(value['candidates']), 1)
        self.assertLess(len(value['candidates'][0]['sample_rows'][0][0]), 180)

    def test_wrong_delimiter_does_not_hide_downloaded_utf8_file(self):
        self.archive('category, label;count;description\n"a,b";1;"one; two"\n"c,d";2;"three;four"\n'.encode())
        before = deepcopy(self.draft.graph)
        value = self.draft.call('diagram_csv_inspect', {'node_id': 'csv'})
        self.assertEqual(value['recommended_encoding'], 'auto')
        self.assertEqual(value['recommended_delimiter'], ';')
        self.assertEqual(len(value['candidates']), 1)
        candidate = value['candidates'][0]
        self.assertEqual(candidate['current_delimiter_error']['line'], 2)
        self.assertIsNone(candidate['parse_error'])
        self.assertEqual(candidate['headers'], ['category, label', 'count', 'description'])
        self.assertEqual(candidate['sample_rows'][0], ['a,b', '1', 'one; two'])
        self.assertEqual(self.draft.graph, before)
        self.draft.call('diagram_update_blocks', {'blocks': [{'id': 'csv', 'settings': {'delimiter': value['recommended_delimiter']}}]})
        checked = self.draft.call('diagram_csv_inspect', {'node_id': 'csv'})
        self.assertIsNone(checked['candidates'][0]['current_delimiter_error'])
        self.assertTrue(checked['candidates'][0]['sample_column_counts_match'])

    def test_malformed_quotes_and_duplicate_headers_keep_evidence(self):
        for contents in ['first,second\n1,ok\n"broken"tail,value\n', 'duplicate,duplicate\n1,2\n3,4\n']:
            with self.subTest(contents=contents):
                self.archive(contents.encode())
                value = self.draft.call('diagram_csv_inspect', {'node_id': 'csv'})
                self.assertEqual(value['recommended_encoding'], 'auto')
                self.assertTrue(value['candidates'])
                self.assertEqual(value['candidates'][0]['raw_text_preview'], contents)
                candidate = value['candidates'][0]
                self.assertTrue(candidate['parse_error'] or candidate['header_error'])
                if contents.startswith('duplicate'):
                    self.assertEqual(value['recommended_delimiter'], ',')
                    self.assertIsNotNone(candidate['header_error'])
                else:
                    self.assertIsNone(value['recommended_delimiter'])

    def test_duplicate_headers_do_not_prevent_separator_detection_or_preview(self):
        self.archive(b'category, label;count;count\n"a,b";1;2\n"c,d";3;4\n')
        value = self.draft.call('diagram_csv_inspect', {'node_id': 'csv'})
        self.assertEqual(value['recommended_delimiter'], ';')
        candidate = value['candidates'][0]
        self.assertTrue(candidate['header_error'])
        self.assertIsNone(candidate['parse_error'])
        self.assertEqual(candidate['headers'], ['category, label', 'count', 'count'])
        self.assertEqual(candidate['sample_rows'][0], ['a,b', '1', '2'])
        self.assertTrue(candidate['current_delimiter_error'])

    def test_delimiters_and_ambiguity(self):
        for delimiter in [';', '\t', '|', ',']:
            with self.subTest(delimiter=delimiter):
                self.archive(delimiter.join(['name', 'count']).encode() + b'\n' +
                             delimiter.join(['alpha', '1']).encode() + b'\n' +
                             delimiter.join(['beta', '2']).encode() + b'\n')
                value = self.draft.call('diagram_csv_inspect', {'node_id': 'csv'})
                self.assertEqual(value['recommended_delimiter'], delimiter)
        self.archive(b'a,b;c\n1,2;3\n4,5;6\n')
        value = self.draft.call('diagram_csv_inspect', {'node_id': 'csv'})
        self.assertIsNone(value['recommended_delimiter'])

    def test_encoding_candidates_and_uploaded_csv_keep_separator_evidence(self):
        text = 'имя;число\nПривет;1\nМир;2\n'
        self.archive(text.encode('cp1251'))
        value = self.draft.call('diagram_csv_inspect', {'node_id': 'csv'})
        windows = next(c for c in value['candidates'] if c['encoding'] == 'cp1251')
        self.assertEqual(windows['recommended_delimiter'], ';')
        self.assertEqual(windows['sample_rows'][0][0], 'Привет')
        graph = deepcopy(self.draft.graph); graph['edges'] = []
        csv_node = next(n for n in graph['nodes'] if n['id'] == 'csv')
        csv_node['block']['inputs']['dataset'] = ml_operations.save(self.store.root, 'dataset',
            {'format': 'architect.uploaded-csv', 'name': 'local.csv', 'csv': text})
        uploaded = codex_edits.Draft(graph, self.store).call('diagram_csv_inspect', {'node_id': 'csv'})
        self.assertEqual(uploaded['recommended_delimiter'], ';')
        self.assertEqual(uploaded['candidates'][0]['sample_rows'][0][0], 'Привет')

    def test_long_invalid_csv_is_bounded_and_not_reported_missing(self):
        self.archive(('a,b\n"broken"tail,' + 'x' * 200000).encode())
        value = self.draft.call('diagram_csv_inspect', {'node_id': 'csv'})
        self.assertTrue(value['candidates'][0]['parse_error'])
        self.assertLess(len(value['candidates'][0]['raw_text_preview']), 2100)
        self.assertLess(len(json.dumps(value, ensure_ascii=False)), 12000)
        self.assertTrue(value['sample_is_partial'])

    def test_chat_tool_can_propose_and_recheck_separator(self):
        self.archive(b'name;value\n"a,b";1\n"c,d";2\n')
        calls = []
        def answer(prompt, draft=None):
            inspected = draft.call('diagram_csv_inspect', {'node_id': 'csv'})
            calls.append(inspected['recommended_delimiter'])
            draft.call('diagram_update_blocks', {'blocks': [{'id': 'csv', 'settings': {'delimiter': inspected['recommended_delimiter']}}]})
            checked = draft.call('diagram_csv_inspect', {'node_id': 'csv'})
            self.assertIsNone(checked['candidates'][0]['current_delimiter_error'])
            return 'Файл доступен. Предлагаю разделитель «;».'
        user = {'id': 'test', 'primary': True}
        with patch.object(codex_chat, 'client', return_value=SimpleNamespace(status=lambda: {'connected': True}, answer=answer)):
            codex_chat.request(self.store.root, user, {'message': 'Посмотри скачанный CSV', 'diagram': self.draft.graph}, 'send')
            for _ in range(200):
                record = codex_chat.request(self.store.root, user, {}, 'history')
                if not record['pending']: break
                time.sleep(.01)
            self.assertFalse(record['pending'])
            self.assertFalse(record['error'])
            self.assertEqual(calls, [';'])
            self.assertIn('proposal', record['messages'][-1])
            unchanged = next(n for n in self.draft.graph['nodes'] if n['id'] == 'csv')
            self.assertEqual(unchanged['block']['settings']['delimiter'], ',')

    def test_missing_context_accounts_and_symlinks_are_rejected(self):
        self.archive(b'text\nhello\n')
        other = codex_edits.Draft(self.draft.graph, ps.ProjectStore(self.store.root / 'other'))
        for draft in (other, codex_edits.Draft(self.draft.graph)):
            with self.assertRaises(bc.ContractError):
                draft.call('diagram_csv_inspect', {'node_id': 'csv'})
        self.path.rename(self.path.with_suffix('.original'))
        self.path.symlink_to(self.path.with_suffix('.original'))
        with self.assertRaises(bc.ContractError):
            self.draft.call('diagram_csv_inspect', {'node_id': 'csv'})
        with self.assertRaises(bc.ContractError):
            self.draft.call('diagram_csv_inspect', {'node_id': 'csv', 'path': '/etc/passwd'})


if __name__ == '__main__':
    unittest.main()

