"""Metric hierarchies and additive proposals from the configured model."""
import json

from block_contracts import ContractError
from codex_chat import standalone_answer
from problem_spaces import stored_tree

FIELDS = ('name', 'role', 'definition', 'unit', 'direction', 'measurement', 'relation', 'check')
INSTRUCTIONS = """Помоги выстроить иерархию метрик ML-системы по описанию пользователя.
Иди от конечной цели к показателям компании и продукта, затем к измеримым факторам.
Уровни ветвей могут различаться. Укажи, как считается метрика, единицу, направление улучшения,
источник данных, выборку и окно наблюдения. Различай связь по формуле, гипотезу влияния,
прокси и ограничение. Для прокси поясни, где связь может нарушиться и как её проверить.
Отличай онлайн-результат продукта от офлайн-оценки и функции потерь при обучении.
Учитывай цену ошибок, чувствительность к составу выборки, стабильность и конфликтующие показатели,
когда это существенно. Не выдумывай наблюдаемые эффекты, пороги, причинность или измеренные значения.
Предложи только новые дочерние узлы для выбранного родителя (путь из индексов с нуля, [] — бизнес-цель).
Верни только JSON-массив новых узлов. У каждого строки name, role, definition, unit, direction,
measurement, relation (связь с родителем), check (проверка связи) и массив children.
Пиши по-русски. Неизвестные детали отметь как требующие уточнения."""


def validate(nodes):
    if not isinstance(nodes, list):
        raise ContractError('Ожидается список метрик.')
    pending = list(nodes)
    while pending:
        item = pending.pop()
        if (not isinstance(item, dict) or set(item) != {*FIELDS, 'children'}
                or not all(isinstance(item[k], str) for k in FIELDS)
                or not item['name'].strip() or not isinstance(item['children'], list)):
            raise ContractError('Проверьте название, поля и дочерние узлы метрики.')
        pending.extend(item['children'])
    return nodes


def content(body):
    title, goal = body.get('title'), body.get('goal')
    if not isinstance(title, str) or not title.strip() or not isinstance(goal, str):
        raise ContractError('Введите название дерева и текст цели.')
    return {'title': title.strip(), 'goal': goal, 'metrics': validate(body.get('metrics'))}


def request(hub, user, body, action):
    if not user:
        raise ContractError('Рабочее пространство недоступно.', 401)
    if action != 'suggest':
        return stored_tree(hub, user, body, action, metrics=True)
    context = content(body)
    prompt, path = body.get('request'), body.get('path')
    if not isinstance(prompt, str) or not prompt.strip() or not isinstance(path, list):
        raise ContractError('Введите запрос и выберите ветвь.')
    nodes = context['metrics']
    for index in path:
        if type(index) is not int or not 0 <= index < len(nodes):
            raise ContractError('Выбранная ветвь отсутствует.')
        nodes = nodes[index]['children']
    reply = standalone_answer(hub.root, json.dumps({**context, 'request': prompt, 'path': path}, ensure_ascii=False), INSTRUCTIONS).strip()
    try:
        result = validate(json.loads(reply[7:-3] if reply.startswith('```json') and reply.endswith('```') else reply))
        if not result:
            raise ValueError()
    except (ContractError, ValueError, RecursionError):
        raise ContractError('Модель не вернула дерево метрик. Уточните запрос и повторите.', 502) from None
    return {'metrics': result}
