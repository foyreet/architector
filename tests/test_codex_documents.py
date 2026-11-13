"""Document ingestion, private retrieval, formats and real chat dispatch without inference."""
import base64
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import block_contracts as bc
import codex_documents as docs
import project_store as ps
from tests.test_codex_chat import ChatTests


def payload(name, data):
    return {'name': name, 'data': base64.b64encode(data).decode()}


def archive(path, text):
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w') as z: z.writestr(path, text)
    return output.getvalue()


def pdf_fixture():
    from pypdf import PdfWriter
    from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
    writer = PdfWriter(); page = writer.add_blank_page(width=600, height=800)
    font = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})
    page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
    stream = DecodedStreamObject(); stream.set_data(b'BT /F1 12 Tf 30 700 Td (Design end marker) Tj ET')
    page[NameObject('/Contents')] = writer._add_object(stream)
    output = io.BytesIO(); writer.write(output); return output.getvalue()


class DocumentTests(unittest.TestCase):
    def test_formats_and_end_content(self):
        for suffix, data, wanted in [
            ('.md', ('Дизайн\n' * 100000 + 'ФИНАЛ').encode(), 'ФИНАЛ'),
            ('.pdf', pdf_fixture(), 'Design end marker'),
            ('.docx', archive('word/document.xml', '<doc><p><t>Требования</t></p><p><t>Конец</t></p></doc>'), 'Конец'),
            ('.odt', archive('content.xml', '<doc><p>Требования</p><p>Конец</p></doc>'), 'Конец'),
            ('.pptx', archive('ppt/slides/slide1.xml', '<slide><p><t>Конец</t></p></slide>'), 'Конец'),
            ('.xlsx', archive('xl/worksheets/sheet1.xml', '<sheet><row><c t="inlineStr"><is><t>Конец</t></is></c></row></sheet>'), 'Конец'),
            ('.html', b'<h1>Design</h1><script>BAD</script><p>End</p>', 'End'),
            ('.rtf', b'{\\rtf1\\ansi Design end}', 'Design end')]:
            with self.subTest(suffix=suffix):
                text = docs.parse(data, suffix)
                self.assertIn(wanted, text)
                self.assertNotIn('BAD', text)

    def test_isolation_pagination_search_and_clear(self):
        with tempfile.TemporaryDirectory() as folder:
            store = ps.ProjectStore(folder)
            text = ('Section.\n' * 100000) + 'FINAL-END'
            meta = docs.upload(store, 'chat-a', payload('design.md', text.encode()))
            self.assertNotIn('text', meta)
            reader = docs.Documents(store, 'chat-a', [meta])
            hit = reader.call('document_search', {'id': meta['id'], 'query': 'FINAL-END'})['matches'][0]
            tail = reader.call('document_read', {'id': meta['id'], 'offset': hit['offset']})
            self.assertEqual(tail['text'], 'FINAL-END'); self.assertIsNone(tail['next_offset'])
            start = reader.call('document_read', {'id': meta['id']})
            self.assertEqual(start['next_offset'], 20000)
            for other in (docs.Documents(store, 'chat-b', [meta]), docs.Documents(ps.ProjectStore(Path(folder) / 'other'), 'chat-a', [meta]), docs.Documents(store, 'chat-a', [])):
                with self.assertRaises(bc.ContractError): other.call('document_read', {'id': meta['id']})
            docs.clear(store, 'chat-b'); self.assertEqual(docs.get(store, 'chat-a', meta['id'])['text'], text)
            docs.clear(store, 'chat-a')
            with self.assertRaises(bc.ContractError): docs.get(store, 'chat-a', meta['id'])

    def test_client_dispatches_document_tools_without_diagram(self):
        import queue
        import codex_chat as chat
        from types import SimpleNamespace
        client = object.__new__(chat.Client); client.events = queue.Queue(); client.work = Path('/tmp')
        calls, replies = [], []
        def rpc(method, params, **kwargs):
            calls.append((method, params))
            if method == 'thread/start': return {'thread': {'id': 't'}}
            if method == 'turn/start':
                client.events.put({'id': 1, 'method': 'item/tool/call', 'params': {'threadId': 't', 'tool': 'document_read', 'arguments': {'id': 'file'}}})
            return {}
        def write(reply):
            replies.append(reply)
            client.events.put({'method': 'item/completed', 'params': {'threadId': 't', 'item': {'type': 'agentMessage', 'text': 'done'}}})
            client.events.put({'method': 'turn/completed', 'params': {'threadId': 't', 'turn': {'status': 'completed'}}})
        client.rpc, client.write = rpc, write
        documents = SimpleNamespace(call=lambda name, args: {'text': 'tail'})
        self.assertEqual(client.answer('read', documents=documents), 'done')
        self.assertEqual({t['name'] for t in calls[0][1]['dynamicTools']}, docs.INDEX)
        self.assertIn('tail', replies[0]['result']['contentItems'][0]['text'])
        self.assertTrue(replies[0]['result']['success'])

    def test_invalid_empty_binary_and_size(self):
        with tempfile.TemporaryDirectory() as folder:
            store = ps.ProjectStore(folder)
            for body in (payload('../secret.txt', b'abc'), payload('x.exe', b'abc'), payload('x.md', b''), payload('x.txt', b'\x00binary'), {'name': 'a.md', 'data': '?'}):
                with self.subTest(body=body):
                    with self.assertRaises(bc.ContractError): docs.upload(store, 'a', body)
            text = b'x' * (21 * 1024 * 1024)
            self.assertEqual(docs.upload(store, 'a', payload('large.txt', text))['characters'], len(text))
            with self.assertRaises(bc.ContractError): docs.parse(b'broken PDF', '.pdf')


class ChatDocumentTests(ChatTests):
    def test_attachment_tools_and_history_without_diagram(self):
        meta = self.call('upload', payload('big.md', (('Requirement\n' * 100000) + 'END-MARKER').encode()))
        prompts = []
        def answer(prompt, documents=None):
            prompts.append(json.loads(prompt))
            self.assertIsNotNone(documents)
            match = documents.call('document_search', {'id': meta['id'], 'query': 'END-MARKER'})['matches'][0]
            self.assertEqual(documents.call('document_read', {'id': meta['id'], 'offset': match['offset']})['text'], 'END-MARKER')
            return 'Прочитан конец документа'
        self.connection.answer = answer
        self.call('send', {'message': 'Прочитай дизайн', 'include_context': False, 'attachments': [meta['id']]})
        record = self.finished()
        self.assertFalse(record['error']); self.assertEqual(record['messages'][0]['attachments'], [meta])
        self.assertLess(len(json.dumps(prompts[0])), 2000)
        self.call('send', {'message': 'А что в конце?', 'include_context': False})
        self.assertFalse(self.finished()['error']); self.assertEqual(len(prompts), 2)
        with self.assertRaises(bc.ContractError): self.call('remove-attachment', {'attachment_id': meta['id']})
        self.call('clear')
        self.assertFalse(list((self.root / 'workspace/codex/documents').glob('*.json')))

    def test_unsent_can_remove_and_unsupported_fails(self):
        meta = self.call('upload', payload('file.txt', b'hello'))
        self.call('remove-attachment', {'attachment_id': meta['id']})
        with self.assertRaises(bc.ContractError): self.call('send', {'message': 'Read', 'attachments': [meta['id']]})
        self.assertEqual(self.call('history')['messages'], [])


if __name__ == '__main__': unittest.main()

