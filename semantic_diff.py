"""Identity-aware comparison and conservative three-way merge of project packages."""
from copy import deepcopy

MISSING = object()
COLLECTIONS = {'nodes': 'id', 'edges': 'id', 'types': 'id', 'definitions': 'kind'}
LABELS = {'nodes': 'Блоки', 'edges': 'Связи', 'types': 'Типы блоков', 'definitions': 'Версии подсхем',
          'settings': 'Настройки', 'inputs': 'Входы', 'name': 'Название', 'description': 'Описание',
          'x': 'Позиция X', 'y': 'Позиция Y', 'width': 'Ширина', 'height': 'Высота', 'block': 'Операция', 'kind': 'Вид блока или связи',
          'diagram': 'Схема', 'from': 'Из блока', 'to': 'В блок', 'fromPort': 'Выход', 'toPort': 'Вход',
          'template': 'Шаблон промпта', 'model': 'Модель', 'temperature': 'Температура',
          'max_tokens': 'Лимит токенов', 'typeId': 'Тип блока'}


def semantic_diff(before, after):
    changes = []
    nodes = {n['id']: n['name'] for package in (before, after) for n in package.get('diagram', {}).get('nodes', [])}

    def edge_label(edge):
        source, target = nodes.get(edge.get('from'), edge.get('from', '')), nodes.get(edge.get('to'), edge.get('to', ''))
        return source + ((' · ' + edge['fromPort']) if edge.get('fromPort') else '') + ' → ' + target + ((' · ' + edge['toPort']) if edge.get('toPort') else '')

    def display(value, path):
        if value is MISSING: return None
        if isinstance(value, dict) and 'from' in value and 'to' in value: return edge_label(value)
        if path and path[-1] in ('from', 'to') and isinstance(value, str): return nodes.get(value, value)
        return value

    def visit(a, b, path, label):
        if a == b: return
        if isinstance(a, dict) and isinstance(b, dict):
            for key in sorted(a.keys() | b.keys()):
                visit(a.get(key, MISSING), b.get(key, MISSING), path + [key], label + [LABELS.get(key, key)])
        elif isinstance(a, list) and isinstance(b, list) and path[-1] in COLLECTIONS:
            key = COLLECTIONS[path[-1]]
            aa, bb = ({item[key]: item for item in items} for items in (a, b))
            for identity in sorted(aa.keys() | bb.keys()):
                item = bb.get(identity, aa.get(identity))
                visit(aa.get(identity, MISSING), bb.get(identity, MISSING), path + [identity],
                      label + [edge_label(item) if path[-1] == 'edges' else item.get('name', identity)])
        else:
            changes.append({'path': path, 'label': ' → '.join(label),
                            'action': 'added' if a is MISSING else 'removed' if b is MISSING else 'changed',
                            'before': None if a is MISSING else a, 'after': None if b is MISSING else b,
                            'display_before': display(a, path), 'display_after': display(b, path),
                            'layout': bool(len(path) >= 3 and path[-3] == 'nodes' and path[-1] in ('x', 'y', 'width', 'height'))})
    visit(before, after, [], [])
    return changes


def merge(base, current, proposed):
    conflicts = []

    def copy(value):
        return MISSING if value is MISSING else deepcopy(value)

    def visit(a, b, c, path):
        if b == c or a == c: return copy(b)
        if a == b: return copy(c)
        # Replacing an operation or artifact is atomic; never mix parameters from two kinds.
        atomic = (path and path[-1] == 'block' and isinstance(a, dict) and
                  any(isinstance(v, dict) and v.get('kind') != a.get('kind') for v in (b, c)))
        atomic = atomic or any(isinstance(v, dict) and v.get('type') == 'artifact' for v in (a, b, c))
        if not atomic and all(isinstance(v, dict) for v in (a, b, c)):
            result = {}
            for key in sorted(a.keys() | b.keys() | c.keys()):
                value = visit(a.get(key, MISSING), b.get(key, MISSING), c.get(key, MISSING), path + [key])
                if value is not MISSING: result[key] = value
            return result
        if all(isinstance(v, list) for v in (a, b, c)) and path and path[-1] in COLLECTIONS:
            key = COLLECTIONS[path[-1]]
            aa, bb, cc = ({item[key]: item for item in items} for items in (a, b, c))
            result = []
            for identity in dict.fromkeys([item[key] for item in b + c + a]):
                value = visit(aa.get(identity, MISSING), bb.get(identity, MISSING), cc.get(identity, MISSING), path + [identity])
                if value is not MISSING: result.append(value)
            return result
        conflicts.append({'path': path, 'base': None if a is MISSING else a,
                          'current': None if b is MISSING else b, 'proposed': None if c is MISSING else c})
        return copy(b)
    result = visit(base, current, proposed, [])
    return result, conflicts

