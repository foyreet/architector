"""Node dimensions survive portable projects and immutable subgraphs."""
from copy import deepcopy
import tempfile
import unittest
from pathlib import Path

import block_contracts as bc
import project_store as ps
import subgraphs as sg
from semantic_diff import semantic_diff
from test_projects import local_graph, ROOT


class NodeSizeTests(unittest.TestCase):
    def test_optional_sizes_and_validation(self):
        original, _ = sg.normalize(local_graph())
        self.assertNotIn('width', original['nodes'][0])
        self.assertNotIn('height', original['nodes'][0])
        for key, values in {'width': [179, 1601, True, None, '300', float('nan'), float('inf')],
                            'height': [109, 4097, False, -1]}.items():
            for value in values:
                with self.subTest(key=key, value=value), self.assertRaises(bc.ContractError):
                    graph = deepcopy(original); graph['nodes'][0][key] = value
                    sg.normalize(graph)
        for width, height in [(180, 110), (1600, 4096), (310.5, 220.5)]:
            graph = deepcopy(original); graph['nodes'][0].update(width=width, height=height)
            normalized, _ = sg.normalize(graph)
            self.assertEqual(normalized['nodes'][0]['width'], width)
            self.assertEqual(normalized['nodes'][0]['height'], height)

    def test_project_and_subgraph_roundtrip(self):
        graph = local_graph(); graph['nodes'][0].update(width=360, height=240)
        with tempfile.TemporaryDirectory() as folder:
            store = ps.ProjectStore(Path(folder))
            created = store.save({'diagram': graph, 'name': 'Resize'}, create=True)
            imported = store.import_package({'package': store.export(created['project']['id'])})
            self.assertEqual(imported['diagram']['nodes'], created['diagram']['nodes'])
        packed = sg.pack({'diagram': graph, 'selected': ['prompt'], 'name': 'Resizable'})
        unpacked = sg.unpack({'diagram': packed['diagram'], 'node_id': packed['node_id']})
        node = unpacked['diagram']['nodes'][0]
        self.assertEqual((node['width'], node['height']), (360, 240))
        # Existing definitions retain their content-addressed identity on normalization.
        legacy = sg.pack({'diagram': local_graph(), 'selected': ['prompt'], 'name': 'Legacy'})['diagram']
        normalized, _ = sg.normalize(legacy)
        self.assertEqual(normalized['definitions'], legacy['definitions'])
        self.assertNotIn('width', legacy['definitions'][0]['graph']['nodes'][0])

    def test_diff_marks_only_node_dimensions_as_layout(self):
        before = {'diagram': local_graph()}; after = deepcopy(before)
        after['diagram']['nodes'][0].update(width=300, height=200)
        changes = semantic_diff(before, after)
        self.assertEqual(len(changes), 2)
        self.assertTrue(all(change['layout'] for change in changes))
        after['diagram']['nodes'][0]['block']['settings']['width'] = 5
        self.assertFalse(next(change for change in semantic_diff(before, after)
                              if 'settings' in change['path'])['layout'])

