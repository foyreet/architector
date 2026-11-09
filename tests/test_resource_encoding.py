"""Storage inventory must read UTF-8 regardless of the operating-system locale."""
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import ml_operations as ml
import project_store as ps
import resource_store as rs


class ResourceEncodingTests(unittest.TestCase):
    def test_unicode_history_and_pinned_artifact_with_windows_default_encoding(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            store = ps.ProjectStore(root)
            artifact = ml.save(root, 'python_data', {'text': 'Ёлка, история и результат'})
            store.write('workspace/runs/unicode.json', {'name': 'Ёлка: запуск', 'artifact': artifact})
            store.write('workspace/artifact-pins.json', {artifact['id']: 'Сохранённый результат'})
            original = Path.read_text

            def windows_read(path, *args, **kwargs):
                if path.is_relative_to(root) and not args and kwargs.get('encoding') is None:
                    kwargs['encoding'] = 'cp1252'
                return original(path, *args, **kwargs)

            with patch.object(Path, 'read_text', windows_read):
                result = rs.inventory(SimpleNamespace(root=root))
            item = next(a for a in result['artifacts'] if a['id'] == artifact['id'])
            self.assertTrue(item['referenced'])
            self.assertTrue(item['pinned'])
            self.assertFalse(item['removable'])
            self.assertEqual(item['label'], 'Сохранённый результат')
            self.assertEqual(item['artifact'], artifact)
