"""A single explicit, versioned design-document snapshot per private conversation."""
from copy import deepcopy
import design_documents as docs
from block_contracts import ContractError
import subgraphs

ACTIONS = {'design-get', 'design-attach', 'design-update', 'design-remove'}


def source(hub, user, kind, identity):
    if kind == 'private':
        doc = docs.request(hub, user, {'id': identity}, 'get')['document']
        package = {'title': doc['title'], 'sections': doc['sections']}; revision = doc['revision']
    else: raise ContractError('Неизвестный источник документа.')
    title, sections = docs.payload(package)
    return {'source_type': kind, 'source_id': identity, 'revision': revision,
            'title': title, 'sections': sections, 'digest': subgraphs.digest({'title': title, 'sections': sections})}


def view(hub, user, record):
    snapshot = record.get('design_document')
    result = {'document': deepcopy(snapshot), 'version': record.get('design_version', 0), 'changed': False, 'unavailable': False}
    if snapshot:
        try:
            current = source(hub, user, snapshot['source_type'], snapshot['source_id'])
            result['changed'] = current['digest'] != snapshot['digest']
        except ContractError:
            result['unavailable'] = True
    return result


def request(hub, user, store, path, record, body, action):
    if hub is None: raise ContractError('Хранилище документов недоступно.', 503)
    if action == 'design-get': return view(hub, user, record)
    version = record.get('design_version', 0)
    expected = body.get('design_version')
    if type(expected) is not int: raise ContractError('Обновите состояние вложения.', 409)
    previous = record.get('design_document')
    if action == 'design-remove': snapshot = None
    elif action == 'design-attach':
        snapshot = source(hub, user, body.get('source_type'), body.get('source_id'))
        if snapshot['revision'] != body.get('source_revision'):
            raise ContractError('Документ изменился. Откройте актуальную версию перед прикреплением.', 409)
    else:
        if not previous: raise ContractError('В чате нет дизайн-документа.', 409)
        snapshot = source(hub, user, previous['source_type'], previous['source_id'])
    if expected != version:
        # Retrying a successful operation after a lost response is safe.
        if expected == version - 1 and previous == snapshot: return view(hub, user, record)
        raise ContractError('Вложение изменилось в другой вкладке. Обновите чат и повторите действие.', 409)
    record.update(design_document=snapshot, design_version=version+1)
    store.write(path, record)
    return view(hub, user, record)


def attachment(snapshot):
    if not snapshot: return None
    text = snapshot['title'] + '\n\n' + '\n\n'.join(f'{i+1}. {label}\n{snapshot["sections"][key]}' for i, (key, label) in enumerate(zip(docs.SECTIONS, docs.LABELS)))
    return {'id': 'design-' + snapshot['digest'], 'name': snapshot['title'], 'size': len(text.encode()), 'characters': len(text), 'text': text}

