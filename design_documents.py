"""Private ML design documents and immutable community snapshots."""
import json
import time
import uuid

from block_contracts import ContractError

SECTIONS = ('problem', 'target', 'metric_validation', 'dataset', 'validation', 'model_training')
LABELS = ('Проблема и текущий процесс', 'Цели, таргет и антицели', 'Метрики', 'Датасет', 'Валидация', 'Решение, альтернативы и обучение')
KIND = 'design_document'
FORMAT = 'architect.design-document'


def identity(value):
    try:
        if str(uuid.UUID(value)) != value: raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise ContractError('Некорректный идентификатор документа.') from None
    return value


def normalize_sections(sections, *, previous=None):
    if not isinstance(sections, dict):
        raise ContractError('Проверьте состав разделов документа.')
    # Older documents and clients may omit sections introduced later.
    previous = previous or {}
    sections = {'dataset': previous.get('dataset', ''), 'validation': previous.get('validation', ''), **sections}
    features = sections.pop('data_features', '')
    if not isinstance(features, str):
        raise ContractError('Каждый раздел должен содержать текст.')
    if features.strip() and isinstance(sections['dataset'], str):
        addition = 'Генерация признаков (из прежнего раздела)\n' + features
        if addition not in sections['dataset']:
            sections['dataset'] = (sections['dataset'] + '\n\n' + addition).lstrip('\n')
    if set(sections) != set(SECTIONS):
        raise ContractError('Проверьте состав разделов документа.')
    if any(not isinstance(v, str) for v in sections.values()):
        raise ContractError('Каждый раздел должен содержать текст.')
    return {key: sections[key] for key in SECTIONS}


def payload(body, *, previous=None):
    title = body.get('title')
    if not isinstance(title, str) or not title.strip():
        raise ContractError('Введите название документа.')
    return title.strip(), normalize_sections(body.get('sections'), previous=previous)


def task_links(value):
    if not isinstance(value, dict) or value.keys() - {'tree_id', 'metric_tree_id', 'case_version', 'cases'}:
        raise ContractError('Некорректные связи этапов задачи.')
    result = {key: identity(value[key]) for key in ('tree_id', 'metric_tree_id') if key in value}
    if 'cases' in value or 'case_version' in value:
        cases = value.get('cases')
        version = value.get('case_version')
        if ('tree_id' not in result or type(version) is not int or version < 0
                or not isinstance(cases, list) or any(type(i) is not int or i < 1 for i in cases)):
            raise ContractError('Проверьте привязку кейсов к дереву проблем.')
        result.update(case_version=version, cases=list(dict.fromkeys(cases)))
    return result


def sources(value):
    if not isinstance(value, dict) or value.keys() - (set(SECTIONS) | {'data_features'}):
        raise ContractError('Некорректные ссылки на источники.')
    for ref in value.values():
        if not isinstance(ref, dict):
            raise ContractError('Некорректный источник.')
        if 'metric_tree' in ref:
            from metric_trees import FIELDS
            metric = ref['metric_tree']
            if (not isinstance(metric, dict) or not isinstance(metric.get('title'), str)
                    or not isinstance(metric.get('goal'), str) or type(metric.get('revision')) is not int
                    or metric['revision'] < 1 or not isinstance(metric.get('nodes'), list)):
                raise ContractError('Некорректная ссылка на иерархию метрик.')
            identity(metric.get('id'))
            for node in metric['nodes']:
                if (not isinstance(node, dict) or not isinstance(node.get('path'), list) or not node['path']
                        or not all(isinstance(name, str) for name in node['path'])
                        or not all(isinstance(node.get(k), str) for k in FIELDS)):
                    raise ContractError('Некорректная ссылка на метрику.')
            if 'tree_id' not in ref:
                continue
        identity(ref.get('tree_id'))
        if (not isinstance(ref.get('title'), str) or
            any(type(ref.get(k)) is not int for k in ('revision', 'version')) or
            not isinstance(ref.get('answers'), list) or not isinstance(ref.get('cases'), list)):
            raise ContractError('Некорректная версия источника.')
        for answer in ref['answers']:
            if not isinstance(answer, dict) or not isinstance(answer.get('path'), list) or not all(isinstance(q, str) for q in answer['path']) or not isinstance(answer.get('answer'), str):
                raise ContractError('Некорректная ссылка на ответ.')
        for case in ref['cases']:
            if not isinstance(case, dict) or type(case.get('id')) is not int or not isinstance(case.get('title'), str):
                raise ContractError('Некорректная ссылка на кейс.')
    return value


def owned(db, user, doc_id):
    row = db.execute('SELECT * FROM design_documents WHERE id=? AND owner=?', (identity(doc_id), user['id'])).fetchone()
    if not row: raise ContractError('Дизайн-документ не найден на этом компьютере.', 404)
    return row


def public(row):
    return {'id': row['id'], 'title': row['title'], 'sections': normalize_sections(json.loads(row['sections'])),
            'task_links': json.loads(row['task_links']), 'sources': json.loads(row['sources']), 'revision': row['revision'], 'updated': row['updated'], 'source_release': row['source_release']}


def snapshot(row):
    return {'format': FORMAT, 'version': 1, 'task_links': json.loads(row['task_links']), 'title': row['title'], 'sections': normalize_sections(json.loads(row['sections'])), 'sources': json.loads(row['sources'])}


def tree_nodes(encoded):
    pending = json.loads(encoded)
    while pending:
        node = pending.pop()
        yield node
        pending.extend(node['children'])


def document_overview(db, owner):
    db.execute('BEGIN')
    problems = {}
    for row in db.execute("""SELECT p.id, p.title, p.updated, p.tree,
                                    coalesce(json_array_length(s.content, '$.options'), 0) AS cases
                             FROM problem_spaces p LEFT JOIN solution_spaces s ON s.tree_id=p.id
                             WHERE p.owner=?""", (owner,)):
        answered = questions = 0
        for node in tree_nodes(row['tree']):
            questions += 1
            answered += bool(node['answer'].strip())
        problems[row['id']] = dict(id=row['id'], title=row['title'], updated=row['updated'],
                                   answered=answered, questions=questions, cases=row['cases'])

    metrics = {}
    for row in db.execute('SELECT id,title,updated,tree FROM metric_trees WHERE owner=?', (owner,)):
        metrics[row['id']] = dict(id=row['id'], title=row['title'], updated=row['updated'],
                                  count=sum(1 for _ in tree_nodes(row['tree'])))

    documents, used_problems, used_metrics = [], set(), set()
    for row in db.execute("""SELECT id,title,revision,updated,sections,task_links FROM design_documents
                             WHERE owner=? ORDER BY updated DESC, id""", (owner,)):
        links = json.loads(row['task_links'])
        tree, metric = links.get('tree_id'), links.get('metric_tree_id')
        used_problems.add(tree)
        used_metrics.add(metric)
        sections = normalize_sections(json.loads(row['sections']))
        documents.append(dict(id=row['id'], title=row['title'], revision=row['revision'], updated=row['updated'],
                              problem=problems.get(tree), metric=metrics.get(metric),
                              missing_problem=bool(tree and tree not in problems),
                              missing_metric=bool(metric and metric not in metrics),
                              filled=sum(bool(value.strip()) for value in sections.values())))

    unlinked = []
    for draft in db.execute('SELECT * FROM design_task_drafts WHERE owner=?', (owner,)):
        problem = problems.get(draft['tree_id'])
        metric = metrics.get(draft['metric_tree_id'])
        members = [member for member in (problem, metric) if member]
        if members:
            unlinked.append(dict(draft_id=draft['id'], title=members[0]['title'],
                                 updated=max(member['updated'] for member in members), problem=problem, metric=metric))
            used_problems.add(draft['tree_id'])
            used_metrics.add(draft['metric_tree_id'])

    def standalone_id(kind, key):
        return str(uuid.uuid5(uuid.NAMESPACE_URL, f'architector/task/{owner}/{kind}/{key}'))

    for kind, collection, used in [('problem', problems, used_problems), ('metric', metrics, used_metrics)]:
        for key, member in collection.items():
            if key not in used:
                unlinked.append({'draft_id': standalone_id(kind, key), 'title': member['title'],
                                 'updated': member['updated'], kind: member})
    unlinked.sort(key=lambda row: row['updated'], reverse=True)
    return {'documents': documents, 'unlinked': unlinked}


def request(hub, user, body, action):
    if user is None: raise ContractError('Войдите в аккаунт Архитектора, чтобы работать с документами.', 401)
    if action in ('method', 'save-method', 'compose', 'review'):
        from design_assistant import request as assist
        return assist(hub, user, body, action)
    if action == 'suggest-questions':
        from problem_spaces import suggest_questions
        title, sections = payload(body)
        return suggest_questions(hub, user, body, {'title': title, 'sections': sections})
    if action == 'list':
        with hub.db() as db:
            if body.get('include_progress') is True:
                return document_overview(db, user['id'])
            rows = db.execute('SELECT id,title,updated,revision FROM design_documents WHERE owner=? ORDER BY updated DESC', (user['id'],))
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
            from problem_spaces import problem_tree
            tree = problem_tree((package if action == 'import' else body).get('problem_tree', []))
            db.execute('INSERT INTO design_documents(id,owner,title,sections,revision,updated,source_release,problem_tree) VALUES(?,?,?,?,?,?,?,?)',
                       (doc_id, user['id'], name, json.dumps(sections, ensure_ascii=False), 1, time.time(), source, json.dumps(tree, ensure_ascii=False)))
            refs = sources((package if action == 'import' else body).get('sources', {}))
            links = task_links((package if action == 'import' else body).get('task_links', {}))
            draft = db.execute('SELECT * FROM design_task_drafts WHERE owner=? AND id=?', (user['id'], doc_id)).fetchone()
            if draft:
                initial = task_links(body.get('initial_task_links', {}))
                for key in ('tree_id', 'metric_tree_id'):
                    if draft[key] and key not in initial:
                        links.setdefault(key, draft[key])
                db.execute('DELETE FROM design_task_drafts WHERE owner=? AND id=?', (user['id'], doc_id))
            db.execute('UPDATE design_documents SET sources=?, task_links=? WHERE id=?',
                       (json.dumps(refs, ensure_ascii=False), json.dumps(links), doc_id))
            if tree:
                db.execute('INSERT INTO problem_spaces(id,owner,title,problem,tree,revision,updated) VALUES(?,?,?,?,?,?,?)',
                           (doc_id, user['id'], name, sections['problem'], json.dumps(tree, ensure_ascii=False), 1, time.time()))
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
            previous = normalize_sections(json.loads(row['sections']))
            name, sections = payload(body, previous=previous)
            revision = body.get('revision')
            if type(revision) is not int: raise ContractError('Укажите версию документа.')
            # A retry after a lost response must not create another revision.
            previous_sources = json.loads(row['sources'])
            refs = sources(body.get('sources', previous_sources))
            for key in ('dataset', 'validation'):
                if key not in body['sections'] and key in previous_sources:
                    refs = {**refs, key: previous_sources[key]}
            previous_links = json.loads(row['task_links'])
            links = task_links(body.get('task_links', previous_links))
            same = links == previous_links and refs == previous_sources and name == row['title'] and sections == previous
            if revision == row['revision']-1 and same: return {'document': public(row)}
            if revision != row['revision']:
                raise ContractError('Документ изменён в другой вкладке. Сохраните свой вариант отдельно или загрузите сохранённую версию.', 409)
            if not same:
                db.execute('UPDATE design_documents SET title=?,sections=?,sources=?,task_links=?,revision=revision+1,updated=? WHERE id=?',
                           (name, json.dumps(sections, ensure_ascii=False), json.dumps(refs, ensure_ascii=False), json.dumps(links), time.time(), row['id']))
            return {'document': public(owned(db, user, row['id']))}
        if action == 'export': return {'package': snapshot(row)}
        raise ContractError('Маршрут документа не найден.', 404)
