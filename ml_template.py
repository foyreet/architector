"""Empty structure used by the user CSV wizard; no example data."""
import block_contracts as bc

def classification_template():
    kinds = ['ml_prepare', 'ml_split', 'ml_train', 'ml_evaluate', 'ml_save']
    graph = {'format': 'architect', 'version': 3, 'name': 'Классификация', 'types': [], 'nodes': [], 'edges': []}
    for i, kind in enumerate(kinds):
        label = bc.CONTRACTS[kind]['label']
        graph['types'].append({'id': 'type-' + kind, 'name': label, 'description': '', 'color': '#275fe8', 'block': {'kind': kind, 'version': 1}})
        block = bc.normalize_block({'kind': kind, 'version': 1})
        graph['nodes'].append({'id': kind, 'typeId': 'type-' + kind, 'name': label, 'description': '', 'x': i * 280, 'y': 80, 'block': block})
    for i, (a, ap, b, bp) in enumerate([('ml_prepare', 'table', 'ml_split', 'table'), ('ml_split', 'train', 'ml_train', 'train'),
        ('ml_split', 'test', 'ml_evaluate', 'test'), ('ml_train', 'model', 'ml_evaluate', 'model'),
        ('ml_evaluate', 'model', 'ml_save', 'model'), ('ml_evaluate', 'metrics', 'ml_save', 'metrics')]):
        graph['edges'].append({'id': 'e' + str(i), 'from': a, 'fromPort': ap, 'to': b, 'toPort': bp, 'kind': 'data'})
    return {'name': graph['name'], 'diagram': graph, 'description': '', 'research': {}}

