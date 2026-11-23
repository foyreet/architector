"""Private five-section ML design documents and immutable community snapshots."""
import json
import time
import uuid

from block_contracts import ContractError

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
    if not isinstance(title, str) or not title.strip():
        raise ContractError('Введите название документа.')
    if not isinstance(sections, dict) or set(sections) != set(SECTIONS):
        raise ContractError('Документ должен содержать пять разделов.')
    if any(not isinstance(v, str) for v in sections.values()):
        raise ContractError('Каждый раздел должен содержать текст.')
    normalized = {k: sections[k] for k in SECTIONS}
    return title.strip(), normalized


def problem_tree(nodes, depth=1):
    if not isinstance(nodes, list) or (nodes and depth > 3):
        raise ContractError('В пространстве проблем доступны три уровня вопросов.')
    for item in nodes:
        if (not isinstance(item, dict) or set(item) != {'question', 'answer', 'children'}
                or not isinstance(item['question'], str) or not item['question'].strip()
                or not isinstance(item['answer'], str)):
            raise ContractError('У каждого узла должны быть вопрос, текст ответа и список уточнений.')
        problem_tree(item['children'], depth + 1)
    return nodes


QUESTION_INSTRUCTIONS = """Помоги исследовать задачу ML-проекта. Предложи новые вопросы на русском языке
с учётом описания задачи, уже заданных вопросов и ответов. Первый уровень собирает общий контекст,
второй уточняет причины и детали ответов, третий раскрывает технические детали. Если указан путь
к узлу, предложи только его новые дочерние вопросы с учётом оставшейся глубины. Для пустого пути
предложи новые ветви с первого уровня. Ветви могут быть разной длины. Не повторяй вопросы и не
заполняй ответы за пользователя. Верни только JSON-массив объектов с полями question (текст)
и children (массив таких же объектов, у листа пустой). Индексы пути отсчитываются от нуля."""


def suggest_questions(root, body):
    from codex_chat import standalone_answer

    title, sections = payload(body)
    tree = problem_tree(body.get('problem_tree', []))
    request, path = body.get('request'), body.get('path', [])
    if not isinstance(request, str) or not request.strip():
        raise ContractError('Опишите задачу для модели.')
    if not isinstance(path, list) or len(path) > 2:
        raise ContractError('Выберите общий или уточняющий вопрос.')
    branch = tree
    for index in path:
        if type(index) is not int or not 0 <= index < len(branch):
            raise ContractError('Выбранный вопрос отсутствует.')
        branch = branch[index]['children']
    prompt = json.dumps({'title': title, 'sections': sections, 'problem_tree': tree,
                         'path': path, 'request': request}, ensure_ascii=False)
    reply = standalone_answer(root, prompt, QUESTION_INSTRUCTIONS)
    def parse(items, depth):
        if not isinstance(items, list) or (items and depth > 3):
            raise ValueError()
        nodes = []
        for item in items:
            if not isinstance(item, dict) or set(item) != {'question', 'children'}:
                raise ValueError()
            question = item['question']
            if not isinstance(question, str) or not question.strip():
                raise ValueError()
            nodes.append({'question': question.strip(), 'answer': '', 'children': parse(item['children'], depth + 1)})
        return nodes
    try:
        text = reply.strip()
        if text.startswith('```json') and text.endswith('```'):
            text = text[7:-3].strip()
        questions = parse(json.loads(text), len(path) + 1)
        if not questions:
            raise ValueError()
    except (ValueError, RecursionError):
        raise ContractError('Модель не вернула подходящее дерево вопросов. Уточните запрос и попробуйте снова.', 502) from None
    return {'questions': questions}


def owned(db, user, doc_id):
    row = db.execute('SELECT * FROM design_documents WHERE id=? AND owner=?', (identity(doc_id), user['id'])).fetchone()
    if not row: raise ContractError('Дизайн-документ не найден на этом компьютере.', 404)
    return row


def public(row):
    return {'id': row['id'], 'title': row['title'], 'sections': json.loads(row['sections']), 'problem_tree': json.loads(row['problem_tree']),
            'revision': row['revision'], 'updated': row['updated'], 'source_release': row['source_release']}


def snapshot(row):
    return {'format': FORMAT, 'version': 1, 'title': row['title'], 'sections': json.loads(row['sections']), 'problem_tree': json.loads(row['problem_tree'])}


def request(hub, user, body, action):
    if user is None: raise ContractError('Войдите в аккаунт Архитектора, чтобы работать с документами.', 401)
    if action == 'suggest-questions':
        return suggest_questions(hub.root, body)
    if action == 'list':
        with hub.db() as db:
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
            tree = problem_tree((package if action == 'import' else body).get('problem_tree', []))
            db.execute('INSERT INTO design_documents(id,owner,title,sections,revision,updated,source_release,problem_tree) VALUES(?,?,?,?,?,?,?,?)',
                       (doc_id, user['id'], name, json.dumps(sections, ensure_ascii=False), 1, time.time(), source, json.dumps(tree, ensure_ascii=False)))
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
            previous_tree = json.loads(row['problem_tree'])
            tree = problem_tree(body.get('problem_tree', previous_tree))
            same = tree == previous_tree and name == row['title'] and sections == json.loads(row['sections'])
            if revision == row['revision']-1 and same: return {'document': public(row)}
            if revision != row['revision']:
                raise ContractError('Документ изменён в другой вкладке. Сохраните свой вариант отдельно или загрузите сохранённую версию.', 409)
            if not same:
                db.execute('UPDATE design_documents SET title=?,sections=?,problem_tree=?,revision=revision+1,updated=? WHERE id=?',
                           (name, json.dumps(sections, ensure_ascii=False), json.dumps(tree, ensure_ascii=False), time.time(), row['id']))
            return {'document': public(owned(db, user, row['id']))}
        if action == 'export': return {'package': snapshot(row)}
        raise ContractError('Маршрут документа не найден.', 404)
