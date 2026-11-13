"""Portable, immutable subgraphs. Definitions pin graph content, including source of isolated Python blocks."""
from copy import deepcopy
import hashlib
import json
import math
import re
import uuid

import block_contracts as bc



def digest(value):
    # JSON numbers such as 1.0 become 1 after a browser round trip.
    def canonical(item):
        if isinstance(item, dict): return {key: canonical(value) for key, value in item.items()}
        if isinstance(item, list): return [canonical(value) for value in item]
        if type(item) is float and math.isfinite(item) and item.is_integer(): return int(item)
        return item
    return hashlib.sha256(json.dumps(canonical(value), sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def text(value, empty=True):
    if not isinstance(value, str) or (not empty and not value.strip()):
        raise bc.ContractError('Некорректный текст в описании проекта или блока.')
    return value


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', value):
        raise bc.ContractError('Некорректный идентификатор схемы.')
    return value


class Registry:
    def __init__(self, definitions):
        if not isinstance(definitions, list):
            raise bc.ContractError('Ожидается список подсхем.')
        self.raw, self.definitions, self.contracts, self.stack = {}, {}, {}, []
        for item in definitions:
            if not isinstance(item, dict) or not re.fullmatch(r'subgraph_[a-f0-9]{64}', str(item.get('kind', ''))):
                raise bc.ContractError('Некорректное определение подсхемы.')
            if item['kind'] in self.raw:
                raise bc.ContractError('Повторяющееся определение подсхемы.')
            self.raw[item['kind']] = item
        for kind in self.raw:
            self.get(kind)

    def get(self, kind):
        if not isinstance(kind, str):
            raise bc.ContractError('Неизвестный тип блока.')
        if kind in bc.CONTRACTS:
            return bc.CONTRACTS[kind]
        if kind in self.contracts:
            return self.contracts[kind]
        if kind not in self.raw:
            raise bc.ContractError('В проекте отсутствует определение блока: ' + kind[:100])
        if kind in self.stack:
            raise bc.ContractError('Рекурсивные ссылки между подсхемами запрещены.')
        self.stack.append(kind)
        try:
            definition, contract = self.definition(self.raw[kind])
            if kind != 'subgraph_' + digest(definition):
                raise bc.ContractError('Содержимое подсхемы не соответствует её хешу. Создайте новую версию блока.')
            self.definitions[kind] = dict(definition, kind=kind)
            self.contracts[kind] = dict(contract, kind=kind)
            return self.contracts[kind]
        finally:
            self.stack.pop()

    def block(self, raw):
        if not isinstance(raw, dict):
            raise bc.ContractError('Некорректный экземпляр блока.')
        kind = raw.get('kind')
        if isinstance(kind, str) and kind in bc.CONTRACTS:
            return bc.normalize_block(raw)
        contract = self.get(kind)
        if type(raw.get('version')) is not int or raw['version'] != 1:
            raise bc.ContractError('Неизвестная версия подсхемы.')
        result = {'kind': kind, 'version': 1, 'inputs': {}, 'settings': {}}
        for section in ('inputs', 'settings'):
            supplied = raw.get(section, {})
            if not isinstance(supplied, dict):
                raise bc.ContractError('Некорректные входы или настройки подсхемы.')
            for spec in contract[section]:
                if spec['id'] in supplied:
                    result[section][spec['id']] = bc.validate_value(supplied[spec['id']], spec)
                elif 'default' in spec:
                    result[section][spec['id']] = deepcopy(spec['default'])
        return result

    def graph(self, raw, full=True):
        if not isinstance(raw, dict) or raw.get('format') != 'architect' or raw.get('version') not in (3, 4):
            raise bc.ContractError('Ожидается схема architect версии 3 или 4.')
        used = set()
        def unique(value):
            value = identifier(value)
            if value in used:
                raise bc.ContractError('Повторяющийся ID в схеме.')
            used.add(value)
            return value
        def items(key):
            value = raw.get(key)
            if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
                raise bc.ContractError('Некорректный список: ' + key)
            return value
        types = []
        for item in items('types'):
            block = self.block(item.get('block'))
            color = item.get('color')
            if not isinstance(color, str) or not re.fullmatch(r'#[a-fA-F0-9]{6}', color):
                raise bc.ContractError('Некорректный цвет блока.')
            types.append({'id': unique(item.get('id')), 'name': text(item.get('name'), False),
                          'description': text(item.get('description', '')), 'color': color,
                          'block': {'kind': block['kind'], 'version': block['version']}})
        type_ids = {item['id'] for item in types}
        nodes = []
        for item in items('nodes'):
            if item.get('typeId') not in type_ids:
                raise bc.ContractError('У блока нет определения в каталоге проекта.')
            for coord in ('x', 'y'):
                value = item.get(coord)
                if type(value) not in (int, float) or not math.isfinite(value):
                    raise bc.ContractError('Некорректные координаты блока.')
            size = {}
            for dimension, minimum in (('width', 180), ('height', 110)):
                if dimension in item:
                    value = item[dimension]
                    if type(value) not in (int, float) or not math.isfinite(value) or value < minimum:
                        raise bc.ContractError('Некорректный размер блока: ' + dimension + '.')
                    size[dimension] = value
            nodes.append({'id': unique(item.get('id')), 'typeId': item['typeId'], 'name': text(item.get('name'), False),
                          'description': text(item.get('description', '')), 'x': item['x'], 'y': item['y'],
                          'block': self.block(item.get('block')), **size})
        index, occupied, edges, connections = {n['id']: n for n in nodes}, set(), [], set()
        for item in items('edges'):
            edge = {key: item.get(key) for key in ('id', 'from', 'to', 'fromPort', 'toPort', 'kind')}
            unique(edge['id'])
            if any(not isinstance(v, str) for v in edge.values()) or edge['from'] not in index or edge['to'] not in index or edge['from'] == edge['to']:
                raise bc.ContractError('Некорректные концы связи.')
            connection = tuple(edge[key] for key in ('from', 'to', 'fromPort', 'toPort', 'kind'))
            if connection in connections:
                raise bc.ContractError('Эти порты уже соединены.')
            connections.add(connection)
            if edge['kind'] == 'annotation' and edge['fromPort'] == edge['toPort'] == 'annotation':
                edges.append(edge); continue
            output = self.port(index[edge['from']]['block'], 'outputs', edge['fromPort'])
            entry = self.port(index[edge['to']]['block'], 'inputs', edge['toPort'])
            if edge['kind'] != 'data' or output['type'] != entry['type']:
                raise bc.ContractError('Несовместимые порты связи.')
            key = (edge['to'], edge['toPort'])
            if key in occupied:
                raise bc.ContractError('У входа может быть только один источник.')
            occupied.add(key); edges.append(edge)
        return {'format': 'architect', 'version': 4 if self.raw else 3, 'name': text(raw.get('name', 'Схема'), False),
                'types': types, 'nodes': nodes, 'edges': edges}

    def port(self, block, section, port):
        spec = next((p for p in self.get(block['kind'])[section] if p['id'] == port), None)
        if spec is None:
            raise bc.ContractError('Неизвестный порт или параметр подсхемы.')
        return spec

    def definition(self, raw):
        if raw.get('version') != 1:
            raise bc.ContractError('Неизвестная версия определения подсхемы.')
        graph = self.graph(raw.get('graph'))
        # Definition graph format does not depend on unrelated definitions in the project.
        graph['version'] = 3
        index = {n['id']: n for n in graph['nodes']}
        if not index:
            raise bc.ContractError('Подсхема не может быть пустой.')
        definition = {'version': 1, 'name': text(raw.get('name'), False),
                      'description': text(raw.get('description', '')), 'graph': graph}
        contract = {'version': 1, 'label': definition['name'], 'operation': {'id': 'subgraph', 'available': True,
                    'description': 'Подсхема. Внутренние шаги доступны в истории запуска.'}}
        for section in ('inputs', 'outputs', 'settings'):
            values = raw.get(section, [])
            if not isinstance(values, list):
                raise bc.ContractError('Ожидается список портов или настроек.')
            bindings, specs, ids, targets = [], [], set(), set()
            for item in values:
                if not isinstance(item, dict) or not isinstance(item.get('target'), dict):
                    raise bc.ContractError('Некорректная привязка порта подсхемы.')
                target = item['target']
                node_id, port = target.get('node'), target.get('port')
                if not isinstance(node_id, str) or not isinstance(port, str) or node_id not in index:
                    raise bc.ContractError('Привязка ссылается на неизвестный узел.')
                port_id = identifier(item.get('id'))
                if port_id in ids or (node_id, port) in targets:
                    raise bc.ContractError('Повторяющаяся привязка подсхемы.')
                ids.add(port_id); targets.add((node_id, port))
                spec = deepcopy(self.port(index[node_id]['block'], section, port))
                if section == 'inputs' and any(e['kind'] == 'data' and e['to'] == node_id and e['toPort'] == port for e in graph['edges']):
                    raise bc.ContractError('Внешний вход уже имеет внутренний источник.')
                label = text(item.get('label', port_id), False)
                bindings.append({'id': port_id, 'label': label, 'target': {'node': node_id, 'port': port}})
                spec.pop('field', None)
                spec.update(id=port_id, label=label)
                if section != 'outputs' and port in index[node_id]['block'][section]:
                    spec['default'] = deepcopy(index[node_id]['block'][section][port])
                specs.append(spec)
            definition[section], contract[section] = bindings, specs
        return definition, contract


def normalize(diagram):
    if not isinstance(diagram, dict):
        raise bc.ContractError('Некорректная схема проекта.')
    registry = Registry(diagram.get('definitions', []))
    graph = registry.graph(diagram)
    graph['definitions'] = list(registry.definitions.values())
    # Validate expansion even when inputs are unfinished; drafts may contain cycles.
    expand(graph, registry)
    return graph, registry


def expand(graph, registry):
    """Return a plain graph plus root-to-leaf mapping; no providers or disk writes."""
    leaves, links, groups = [], [], {}
    def visit(current, path=(), names=(), root=None):
        inputs, outputs, representatives = {}, {}, {}
        for node in current['nodes']:
            block = node['block']; kind = block['kind']
            top = root or node['id']
            if kind in bc.CONTRACTS:
                node_id = node['id'] if not path else 'n_' + digest([*path, node['id']])[:32]
                leaves.append({'id': node_id, 'name': ' / '.join((*names, node['name'])), 'block': deepcopy(block)})
                groups.setdefault(top, []).append(node_id)
                representatives[node['id']] = node_id
                for section, dest in [('inputs', inputs), ('outputs', outputs)]:
                    for port in registry.get(kind)[section]:
                        dest[(node['id'], port['id'])] = (node_id, port['id'])
            else:
                definition = registry.definitions[kind]
                inner = deepcopy(definition['graph'])
                index = {n['id']: n for n in inner['nodes']}
                for section in ('inputs', 'settings'):
                    for binding in definition[section]:
                        if binding['id'] in block[section]:
                            target = binding['target']
                            index[target['node']]['block'][section][target['port']] = deepcopy(block[section][binding['id']])
                ins, outs, reps = visit(inner, (*path, node['id']), (*names, node['name']), top)
                representatives[node['id']] = next(iter(reps.values()))
                for section, inner_ports, dest in [('inputs', ins, inputs), ('outputs', outs, outputs)]:
                    for binding in definition[section]:
                        target = binding['target']
                        dest[(node['id'], binding['id'])] = inner_ports[(target['node'], target['port'])]
        for edge in current['edges']:
            if edge['kind'] == 'annotation':
                source, target = (representatives[edge['from']], 'annotation'), (representatives[edge['to']], 'annotation')
            else:
                source, target = outputs[(edge['from'], edge['fromPort'])], inputs[(edge['to'], edge['toPort'])]
            links.append({'id': 'e_' + digest([*path, edge['id']])[:32], 'from': source[0], 'fromPort': source[1],
                          'to': target[0], 'toPort': target[1], 'kind': edge['kind']})
        return inputs, outputs, representatives
    visit(graph)
    return {'format': 'architect', 'version': 3, 'name': graph['name'], 'nodes': leaves, 'edges': links}, groups


def pack(body):
    graph, registry = normalize(body.get('diagram'))
    selected = body.get('selected')
    if not isinstance(selected, list) or not selected or any(not isinstance(s, str) for s in selected):
        raise bc.ContractError('Выберите блоки для подсхемы.')
    chosen = set(selected)
    if not chosen <= {n['id'] for n in graph['nodes']}:
        raise bc.ContractError('Выбранный блок не найден.')
    inner_nodes = [n for n in graph['nodes'] if n['id'] in chosen]
    inner_edges = [e for e in graph['edges'] if e['from'] in chosen and e['to'] in chosen]
    inner_types = [t for t in graph['types'] if t['id'] in {n['typeId'] for n in inner_nodes}]
    raw = {'version': 1, 'name': text(body.get('name'), False), 'description': text(body.get('description', '')),
           'graph': {'format': 'architect', 'version': 3, 'name': body['name'], 'nodes': inner_nodes, 'edges': inner_edges, 'types': inner_types},
           'inputs': [], 'outputs': [], 'settings': []}
    maps = {'inputs': {}, 'outputs': {}}
    labels = body.get('labels', {})
    if not isinstance(labels, dict):
        raise bc.ContractError('Некорректные имена портов.')
    for node in inner_nodes:
        for section in ('inputs', 'outputs', 'settings'):
            for spec in registry.get(node['block']['kind'])[section]:
                if section == 'settings' and node['block']['kind'] == 'python_code' and spec['id'] == 'code': continue
                if section == 'inputs' and any(e['kind'] == 'data' and e['to'] == node['id'] and e['toPort'] == spec['id'] for e in inner_edges):
                    continue
                if section == 'outputs':
                    used = [e for e in graph['edges'] if e['kind'] == 'data' and e['from'] == node['id'] and e['fromPort'] == spec['id']]
                    if used and all(e['to'] in chosen for e in used):
                        continue
                port_id = section[0] + str(len(raw[section]))
                key = section + ':' + node['id'] + ':' + spec['id']
                label = labels.get(key, node['name'] + ' · ' + spec['label'])
                raw[section].append({'id': port_id, 'label': label, 'target': {'node': node['id'], 'port': spec['id']}})
                if section in maps:
                    maps[section][(node['id'], spec['id'])] = port_id
    definition, _ = registry.definition(raw)
    kind = 'subgraph_' + digest(definition)
    definition['kind'] = kind
    definitions = {d['kind']: d for d in graph['definitions']}; definitions[kind] = definition
    node_id, type_id = str(uuid.uuid4()), str(uuid.uuid4())
    type_value = {'id': type_id, 'name': raw['name'], 'description': raw['description'], 'color': '#6366f1', 'block': {'kind': kind, 'version': 1}}
    node = {'id': node_id, 'typeId': type_id, 'name': raw['name'], 'description': raw['description'],
            'x': min(n['x'] for n in inner_nodes), 'y': min(n['y'] for n in inner_nodes), 'block': {'kind': kind, 'version': 1}}
    new_edges = []
    for edge in graph['edges']:
        if edge['from'] in chosen and edge['to'] in chosen:
            continue
        edge = dict(edge)
        for side, ports, port_key in [('from', 'outputs', 'fromPort'), ('to', 'inputs', 'toPort')]:
            if edge[side] in chosen:
                edge[port_key] = 'annotation' if edge['kind'] == 'annotation' else maps[ports][(edge[side], edge[port_key])]
                edge[side] = node_id
        if edge['kind'] != 'annotation' or not any(e['kind'] == 'annotation' and e['from'] == edge['from'] and e['to'] == edge['to'] for e in new_edges):
            new_edges.append(edge)
    graph.update(nodes=[n for n in graph['nodes'] if n['id'] not in chosen] + [node], edges=new_edges,
                 types=graph['types'] + [type_value], definitions=list(definitions.values()), version=4)
    graph, registry = normalize(graph)
    # A group must not hide a path that leaves it and then re-enters it.
    degree = {n['id']: 0 for n in graph['nodes']}
    for e in graph['edges']:
        if e['kind'] == 'data': degree[e['to']] += 1
    queue = [key for key in degree if degree[key] == 0]
    for key in queue:
        for e in graph['edges']:
            if e['kind'] == 'data' and e['from'] == key:
                degree[e['to']] -= 1
                if degree[e['to']] == 0: queue.append(e['to'])
    if len(queue) != len(degree):
        raise bc.ContractError('Это выделение создаёт цикл через внешние блоки. Добавьте промежуточные блоки в выделение.')
    return {'diagram': graph, 'node_id': node_id, 'contracts': list(registry.contracts.values())}


def unpack(body):
    graph, registry = normalize(body.get('diagram'))
    node = next((n for n in graph['nodes'] if n['id'] == body.get('node_id')), None)
    if not node or node['block']['kind'] not in registry.definitions:
        raise bc.ContractError('Выберите экземпляр подсхемы.')
    definition = registry.definitions[node['block']['kind']]
    inner = deepcopy(definition['graph'])
    index = {n['id']: n for n in inner['nodes']}
    for section in ('inputs', 'settings'):
        for binding in definition[section]:
            if binding['id'] in node['block'][section]:
                target = binding['target']
                index[target['node']]['block'][section][target['port']] = deepcopy(node['block'][section][binding['id']])
    node_ids = {n['id']: str(uuid.uuid4()) for n in inner['nodes']}
    type_ids = {t['id']: str(uuid.uuid4()) for t in inner['types']}
    min_x, min_y = min(n['x'] for n in inner['nodes']), min(n['y'] for n in inner['nodes'])
    for item in inner['nodes']:
        item.update(id=node_ids[item['id']], typeId=type_ids[item['typeId']],
                    x=node['x'] + item['x'] - min_x,
                    y=node['y'] + item['y'] - min_y)
    for item in inner['types']:
        item['id'] = type_ids[item['id']]
    for edge in inner['edges']:
        edge.update(id=str(uuid.uuid4()), **{'from': node_ids[edge['from']], 'to': node_ids[edge['to']]})
    for edge in graph['edges']:
        for side, section, port_key in [('from', 'outputs', 'fromPort'), ('to', 'inputs', 'toPort')]:
            if edge[side] != node['id']:
                continue
            if edge['kind'] == 'annotation':
                edge[side] = inner['nodes'][0]['id']
            else:
                binding = next(b for b in definition[section] if b['id'] == edge[port_key])
                edge[side], edge[port_key] = node_ids[binding['target']['node']], binding['target']['port']
    graph.update(nodes=[n for n in graph['nodes'] if n['id'] != node['id']] + inner['nodes'],
                 types=graph['types'] + inner['types'], edges=graph['edges'] + inner['edges'])
    graph, registry = normalize(graph)
    return {'diagram': graph, 'contracts': list(registry.contracts.values())}


def request(body, action):
    if action == 'pack':
        return pack(body)
    if action == 'unpack':
        return unpack(body)
    if action == 'normalize':
        graph, registry = normalize(body.get('diagram'))
        return {'diagram': graph, 'contracts': list(registry.contracts.values())}
    raise bc.ContractError('Маршрут не найден.', 404)

