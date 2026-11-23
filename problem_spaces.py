"""Independent local problem trees and question proposals."""
import json
import time

from block_contracts import ContractError
from design_documents import identity


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


def suggest_questions(root, body, context):
    from codex_chat import standalone_answer

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
    prompt = json.dumps({**context, 'problem_tree': tree,
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


def content(body):
    title, problem = body.get('title'), body.get('problem', '')
    if not isinstance(title, str) or not title.strip() or not isinstance(problem, str):
        raise ContractError('Укажите название дерева и текст проблемы.')
    return {'title': title.strip(), 'problem': problem, 'problem_tree': problem_tree(body.get('problem_tree'))}


def request(hub, user, body, action):
    if not user:
        raise ContractError('Рабочее пространство недоступно.', 401)
    if action == 'suggest-questions':
        value = content(body)
        return suggest_questions(hub.root, body, {k: value[k] for k in ('title', 'problem')})
    with hub.db() as db:
        owner = user['id']
        if action == 'list':
            rows = db.execute('SELECT id,title FROM problem_spaces WHERE owner=? ORDER BY updated DESC', (owner,))
            return {'trees': [dict(row) for row in rows]}
        tree_id = identity(body.get('id'))
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT * FROM problem_spaces WHERE id=? AND owner=?', (tree_id, owner)).fetchone()
        if action == 'get':
            if not row:
                raise ContractError('Дерево не найдено.', 404)
            return {'id': tree_id, 'title': row['title'], 'problem': row['problem'],
                    'problem_tree': json.loads(row['tree']), 'revision': row['revision']}
        if action != 'save':
            raise ContractError('Маршрут дерева не найден.', 404)
        value = content(body)
        revision = body.get('revision')
        if type(revision) is not int or revision < 0:
            raise ContractError('Некорректная версия дерева.')
        if row and revision == row['revision'] - 1 and row['title'] == value['title'] and row['problem'] == value['problem'] and json.loads(row['tree']) == value['problem_tree']:
            return {'revision': row['revision']}
        if revision != (row['revision'] if row else 0):
            raise ContractError('Дерево изменено в другой вкладке. Сохраните свой вариант как копию.', 409)
        fields = (value['title'], value['problem'], json.dumps(value['problem_tree'], ensure_ascii=False), revision + 1, time.time())
        if row:
            db.execute('UPDATE problem_spaces SET title=?,problem=?,tree=?,revision=?,updated=? WHERE id=? AND owner=?', (*fields, tree_id, owner))
        else:
            db.execute('INSERT INTO problem_spaces(title,problem,tree,revision,updated,id,owner) VALUES(?,?,?,?,?,?,?)', (*fields, tree_id, owner))
        return {'revision': revision + 1}
