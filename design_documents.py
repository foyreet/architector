"""Private five-section ML design documents and immutable community snapshots."""
import json
import time
import uuid

from block_contracts import ContractError
import subgraphs

SECTIONS = ('problem', 'target', 'data_features', 'metric_validation', 'model_training')
LABELS = ('Проблема', 'Таргет', 'Данные и признаки', 'Метрика и проверка', 'Модель и обучение')
KIND = 'design_document'
FORMAT = 'architect.design-document'


def identity(value):
    try:
        if str(uuid.UUID(value)) != value: raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise ContractError('Некорректный идентификатор документа.') from None
    return value


def payload(body):
    title, sections = body.get('title'), body.get('sections')
    if not isinstance(title, str) or not 1 <= len(title.strip()) <= 160:
        raise ContractError('Название должно содержать от 1 до 160 символов.')
    if not isinstance(sections, dict) or set(sections) != set(SECTIONS):
        raise ContractError('Документ должен содержать пять разделов.')
    if any(not isinstance(v, str) or len(v) > 20000 for v in sections.values()):
        raise ContractError('В одном разделе может быть до 20 000 символов.')
    normalized = {k: sections[k] for k in SECTIONS}
    if len(json.dumps(normalized, ensure_ascii=False).encode('utf-8')) > 256*1024:
        raise ContractError('Документ больше 256 КиБ.', 413)
    return title.strip(), normalized


def owned(db, user, doc_id):
    row = db.execute('SELECT * FROM design_documents WHERE id=? AND owner=?', (identity(doc_id), user['id'])).fetchone()
    if not row: raise ContractError('Дизайн-документ не найден на этом компьютере.', 404)
    return row


def public(row):
    return {'id': row['id'], 'title': row['title'], 'sections': json.loads(row['sections']),
            'revision': row['revision'], 'updated': row['updated'], 'source_release': row['source_release']}


def snapshot(row):
    return {'format': FORMAT, 'version': 1, 'title': row['title'], 'sections': json.loads(row['sections'])}


def request(hub, user, body, action):
    if user is None: raise ContractError('Войдите в аккаунт Архитектора, чтобы работать с документами.', 401)
    if action == 'list':
        with hub.db() as db:
            rows = db.execute('SELECT id,title,updated,revision FROM design_documents WHERE owner=? ORDER BY updated DESC LIMIT 200', (user['id'],))
            return {'documents': [dict(row) for row in rows]}
    if action in ('create', 'import'):
        doc_id = identity(body.get('id'))
        source = None
        if action == 'import':
            package = body.get('package', {})
            if not isinstance(package, dict) or package.get('format') != FORMAT or package.get('version') != 1:
                raise ContractError('Выберите файл дизайн-документа Архитектора.')
            name, sections = payload(package)
        else:
            name, sections = payload(body if 'title' in body or 'sections' in body else
                                     {'title': 'Новый дизайн-документ', 'sections': {k: '' for k in SECTIONS}})
        with hub.db() as db:
            db.execute('BEGIN IMMEDIATE')
            previous = db.execute('SELECT * FROM design_documents WHERE id=?', (doc_id,)).fetchone()
            if previous:
                if previous['owner'] != user['id'] or previous['source_release'] != source:
                    raise ContractError('Идентификатор документа уже используется.', 409)
                return {'document': public(previous)}
            db.execute('INSERT INTO design_documents VALUES(?,?,?,?,?,?,?)',
                       (doc_id, user['id'], name, json.dumps(sections, ensure_ascii=False), 1, time.time(), source))
            return {'document': public(owned(db, user, doc_id))}
    with hub.db() as db:
        db.execute('BEGIN IMMEDIATE')
        row = owned(db, user, body.get('id'))
        if action == 'get': return {'document': public(row)}
        if action == 'delete':
            if type(body.get('revision')) is not int or body['revision'] != row['revision']:
                raise ContractError('Документ изменён в другой вкладке. Обновите список перед удалением.', 409)
            db.execute('DELETE FROM design_documents WHERE id=? AND owner=?', (row['id'], user['id']))
            return {'deleted': row['id']}
        if action == 'save':
            name, sections = payload(body)
            revision = body.get('revision')
            if type(revision) is not int: raise ContractError('Укажите версию документа.')
            # A retry after a lost response must not create another revision.
            same = name == row['title'] and sections == json.loads(row['sections'])
            if revision == row['revision']-1 and same: return {'document': public(row)}
            if revision != row['revision']:
                raise ContractError('Документ изменён в другой вкладке. Сохраните свой вариант отдельно или загрузите сохранённую версию.', 409)
            if not same:
                db.execute('UPDATE design_documents SET title=?,sections=?,revision=revision+1,updated=? WHERE id=?',
                           (name, json.dumps(sections, ensure_ascii=False), time.time(), row['id']))
            return {'document': public(owned(db, user, row['id']))}
        if action == 'export': return {'package': snapshot(row)}
        raise ContractError('Маршрут документа не найден.', 404)
