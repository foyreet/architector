"""Independent local problem trees and question proposals."""
import json
import time

import tree_methods
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


DEFAULT_METHOD = """Помоги исследовать задачу ML-проекта. Предложи новые вопросы на русском языке
с учётом описания задачи, уже заданных вопросов и ответов. Выбирай следующий вопрос по тому,
какое решение зависит от ответа. Ищи неоднозначные понятия и предположения, требующие проверки.

Определяй этап обсуждения по запросу пользователя, формулировке проблемы и полученным ответам.
Если дана только исходная задача, начни с общих вопросов: у кого возникает проблема, как её решают
сейчас и какой результат нужен. Оставь ветви открытыми для уточнений после ответа.
Когда понятна цель, уточняй конкретный сценарий, доступные данные и критерий успеха.
Спроси об ограничении уже сейчас, если оно меняет постановку или выбор решения, например
если данные появляются слишком поздно или решение нужно принять за определённое время.
Когда описан хотя бы набросок архитектуры, переходи к подробному разбору рисков.
Привязывай вопросы к конкретному решению: при каких условиях оно даст сбой, кого затронет
ошибка, какова цена последствий и как их обнаружить или смягчить. Если пользователь прямо
просит разобрать риск раньше, следуй запросу и уточняй недостающий контекст.

Глубина узла определяет степень детализации вопроса. Этап обсуждения может быть любым
на каждом уровне. Первый уровень собирает общий контекст,
второй уточняет причины и детали ответов, третий раскрывает технические детали. Ветви могут быть разной длины. Не повторяй вопросы."""

RESPONSE_CONTRACT = """Если указан путь
к узлу, предложи только его новые дочерние вопросы с учётом оставшейся глубины. Для пустого пути
предложи новые ветви с первого уровня. Максимальная глубина дерева — три уровня. Не заполняй ответы за пользователя.
Верни только непустой JSON-массив объектов с полями question (текст)
и children (массив таких же объектов, у листа пустой). Индексы пути отсчитываются от нуля."""


def suggest_questions(hub, user, body, context):
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
    instructions = tree_methods.instructions(hub, user, 'problems', DEFAULT_METHOD, RESPONSE_CONTRACT)
    reply = standalone_answer(hub.root, prompt, instructions)
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
    if action in ('method', 'save-method'):
        return tree_methods.method_settings(hub, user, 'problems', DEFAULT_METHOD, body if action == 'save-method' else None)
    if action == 'suggest-questions':
        value = content(body)
        return suggest_questions(hub, user, body, {k: value[k] for k in ('title', 'problem')})
    return stored_tree(hub, user, body, action, metrics=False)


def stored_tree(hub, user, body, action, *, metrics):
    table = 'metric_trees' if metrics else 'problem_spaces'
    nodes_key = 'metrics' if metrics else 'problem_tree'
    goal_key = 'goal' if metrics else 'problem'
    with hub.db() as db:
        owner = user['id']
        if action == 'list':
            columns = 'id,title,revision' if metrics else 'id,title'
            rows = db.execute(f'SELECT {columns} FROM {table} WHERE owner=? ORDER BY updated DESC', (owner,))
            return {'trees': [dict(row) for row in rows]}
        tree_id = identity(body.get('id'))
        db.execute('BEGIN IMMEDIATE')
        row = db.execute(f'SELECT * FROM {table} WHERE id=? AND owner=?', (tree_id, owner)).fetchone()
        if action == 'get':
            if not row:
                raise ContractError('Дерево не найдено.', 404)
            return {'id': tree_id, 'title': row['title'], goal_key: row['problem'],
                    nodes_key: json.loads(row['tree']), 'revision': row['revision']}
        if action != 'save':
            raise ContractError('Маршрут дерева не найден.', 404)
        if metrics:
            from metric_trees import content as metric_content
            value = metric_content(body)
        else:
            value = content(body)
        revision = body.get('revision')
        if type(revision) is not int or revision < 0:
            raise ContractError('Некорректная версия дерева.')
        if row and revision == row['revision'] - 1 and row['title'] == value['title'] and row['problem'] == value[goal_key] and json.loads(row['tree']) == value[nodes_key]:
            return {'revision': row['revision']}
        if revision != (row['revision'] if row else 0):
            raise ContractError('Дерево изменено в другой вкладке. Сохраните свой вариант как копию.', 409)
        fields = (value['title'], value[goal_key], json.dumps(value[nodes_key], ensure_ascii=False), revision + 1, time.time())
        if row:
            db.execute(f'UPDATE {table} SET title=?,problem=?,tree=?,revision=?,updated=? WHERE id=? AND owner=?', (*fields, tree_id, owner))
        else:
            db.execute(f'INSERT INTO {table}(title,problem,tree,revision,updated,id,owner) VALUES(?,?,?,?,?,?,?)', (*fields, tree_id, owner))
        return {'revision': revision + 1}
