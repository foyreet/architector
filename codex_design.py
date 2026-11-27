"""A single explicit, versioned design-document snapshot per private conversation."""
from copy import deepcopy
from block_contracts import ContractError

SECTIONS = ('problem', 'target', 'metric_validation', 'dataset', 'validation', 'model_training')
LABELS = ('Проблема и текущий процесс', 'Цели, таргет и антицели', 'Метрики', 'Датасет', 'Валидация', 'Решение, альтернативы и обучение')
ACTIONS = {'design-get', 'design-remove'}


def view(record):
    snapshot = record.get('design_document')
    return {'document': deepcopy(snapshot), 'version': record.get('design_version', 0),
            'changed': False, 'unavailable': bool(snapshot)}


def request(hub, user, store, path, record, body, action):
    if action == 'design-get':
        return view(record)
    version = record.get('design_version', 0)
    expected = body.get('design_version')
    if expected != version:
        if expected == version - 1 and not record.get('design_document'):
            return view(record)
        raise ContractError('Вложение изменилось в другой вкладке. Обновите чат.', 409)
    record.update(design_document=None, design_version=version+1)
    store.write(path, record)
    return view(record)


def attachment(snapshot):
    if not snapshot: return None
    fields = [(key, label) for key, label in zip(SECTIONS, LABELS) if key in snapshot['sections']]
    if 'data_features' in snapshot['sections']:
        fields.append(('data_features', 'Признаки из прежней версии'))
    text = snapshot['title'] + '\n\n' + '\n\n'.join(f'{i+1}. {label}\n{snapshot["sections"][key]}' for i, (key, label) in enumerate(fields))
    return {'id': 'design-' + snapshot['digest'], 'name': snapshot['title'], 'size': len(text.encode()), 'characters': len(text), 'text': text}

