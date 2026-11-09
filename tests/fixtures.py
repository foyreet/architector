"""Synthetic fixtures for tests only; never served or created at app startup."""
import block_contracts as bc
import project_store as ps

def sample_project(root):
    kinds = ['ml_prepare', 'ml_split', 'ml_train', 'ml_evaluate', 'ml_save']
    graph = {'format': 'architect', 'version': 3, 'name': 'Первый эксперимент', 'types': [], 'nodes': [], 'edges': []}
    for i, kind in enumerate(kinds):
        label = bc.CONTRACTS[kind]['label']
        graph['types'].append({'id': 'type-' + kind, 'name': label, 'description': '', 'color': '#275fe8', 'block': {'kind': kind, 'version': 1}})
        block = bc.normalize_block({'kind': kind, 'version': 1})
        if kind == 'ml_prepare':
            block['inputs']['rows'] = [{'x': i, 'z': i % 3, 'label': 'low' if i < 20 else 'high'} for i in range(40)]
            block['settings'].update(target='label', features='x,z')
        if kind == 'ml_train': block['settings']['n_estimators'] = 10
        graph['nodes'].append({'id': kind, 'typeId': 'type-' + kind, 'name': label, 'description': '', 'x': i * 280, 'y': 80, 'block': block})
    for i, (a, ap, b, bp) in enumerate([('ml_prepare', 'table', 'ml_split', 'table'), ('ml_split', 'train', 'ml_train', 'train'),
        ('ml_split', 'test', 'ml_evaluate', 'test'), ('ml_train', 'model', 'ml_evaluate', 'model'),
        ('ml_evaluate', 'model', 'ml_save', 'model'), ('ml_evaluate', 'metrics', 'ml_save', 'metrics')]):
        graph['edges'].append({'id': 'e' + str(i), 'from': a, 'fromPort': ap, 'to': b, 'toPort': bp, 'kind': 'data'})
    payload = {'name': graph['name'], 'diagram': graph,
            'description': 'Учебные синтетические данные: 40 строк, признаки x и z, целевой класс label. Это демонстрация процесса, не оценка качества на реальной задаче. Подготовка → разделение → Random Forest → метрики → сохранение.',
            'research': {'tutorial': True, 'hypothesis': 'Random Forest распознает зависимость класса от x.', 'metric': 'ml_evaluate/accuracy', 'direction': 'max', 'baseline': ''}}

    return ps.ProjectStore(root).save(payload, create=True)

