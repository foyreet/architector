"""Stateless Streamable HTTP MCP: workspace-scoped pipeline design, never execution."""
from copy import deepcopy
import json
from pathlib import Path
import re

import block_contracts as bc
import local_workspace as community
import pipeline_runner
import project_store
import subgraphs

PROTOCOLS = ('2025-06-18', '2025-03-26')
GUIDE_URI = 'architect://guide'
INSTRUCTIONS = Path(__file__).with_name('MCP_GUIDE.md').read_text(encoding='utf-8')
GUIDE_RESOURCE = {'uri': GUIDE_URI, 'name': 'architect-guide', 'title': 'Как работать с Architect',
                  'description': 'Start here: workflows for pipelines, custom Python blocks, publishing and pinned reuse.',
                  'mimeType': 'text/markdown', 'size': len(INSTRUCTIONS.encode('utf-8'))}



def obj(properties=None, required=()):
    return {'type': 'object', 'properties': properties or {}, 'required': list(required), 'additionalProperties': False}


TEXT = {'type': 'string'}
PROJECT = {'type': 'string', 'description': 'Project UUID owned by the authenticated workspace.'}
SPEC = obj({
    'name': {'type': 'string', 'minLength': 1},
    'description': {'type': 'string'},
    'source_project_id': {**PROJECT, 'description': 'Optional own project whose pinned custom block definitions should be reused.'},
    'blocks': {'type': 'array', 'minItems': 1, 'items': obj({
        'id': {'type': 'string', 'pattern': '^[A-Za-z0-9_-]+$'}, 'kind': TEXT,
        'name': {'type': 'string'}, 'description': {'type': 'string'},
        'settings': {'type': 'object'}, 'inputs': {'type': 'object'}}, ('id', 'kind'))},
    'connections': {'type': 'array', 'items': obj({
        'from': TEXT, 'to': TEXT, 'from_port': TEXT, 'to_port': TEXT}, ('from', 'to', 'from_port', 'to_port'))}
}, ('name', 'blocks', 'connections'))

BINDINGS = {'type': 'array', 'items': obj({
    'id': {'type': 'string', 'pattern': '^[A-Za-z0-9_-]+$'}, 'label': TEXT,
    'target': obj({'node': TEXT, 'port': TEXT}, ('node', 'port'))}, ('id', 'target'))}
BLOCK = obj({'pipeline': SPEC, 'inputs': BINDINGS, 'outputs': BINDINGS, 'settings': BINDINGS},
            ('pipeline', 'inputs', 'outputs', 'settings'))
REVISION = {'type': 'integer', 'minimum': 1}
PUBLICATION = {'project_id': PROJECT, 'revision': REVISION, 'block_kind': TEXT,
               'slug': {'type': 'string', 'pattern': '^[a-z0-9][a-z0-9_-]{2,79}$'}}


def tool(name, description, schema, write=False, destructive=False):
    return {'name': name, 'description': description, 'inputSchema': schema, 'annotations': {
        'readOnlyHint': not write, 'destructiveHint': destructive, 'idempotentHint': True, 'openWorldHint': False}}


TOOLS = [
    tool('architect_get_guide', 'Read the local application guide before designing a pipeline.', obj()),
    tool('architect_block_catalog', 'Discover exact input/output types and settings of built-in blocks, plus pinned custom blocks from an optional own project.', obj({'project_id': PROJECT})),
    tool('architect_list_projects', 'List the local projects and revisions.', obj()),
    tool('architect_get_project', 'Read an own project, compact editable specification, current revision and editor URL.', obj({'project_id': PROJECT}, ('project_id',))),
    tool('architect_validate_pipeline', 'Statically check ports, operation settings, required inputs and cycles; returns execution order without running anything.', obj({'pipeline': SPEC}, ('pipeline',))),
    tool('architect_create_pipeline', 'Save a new private project from a validated compact specification. Does not execute it. Reuse request_id on retries.', obj({'pipeline': SPEC, 'request_id': {'type': 'string', 'format': 'uuid'}}, ('pipeline', 'request_id')), True),
    tool('architect_update_pipeline', 'Replace an existing own project diagram using its current revision. Fetch first; preserve wanted blocks. Nothing is executed.', obj({'project_id': PROJECT, 'revision': {'type': 'integer', 'minimum': 1}, 'pipeline': SPEC}, ('project_id', 'revision', 'pipeline')), True, True),
]


def check(value, schema, label='arguments'):
    kind = schema.get('type')
    if kind == 'object':
        if not isinstance(value, dict): raise bc.ContractError(label + ': ожидается объект.')
        required = set(schema.get('required', []))
        if required - set(value): raise bc.ContractError(label + ': отсутствуют поля ' + ', '.join(sorted(required - set(value))))
        props = schema.get('properties', {})
        if schema.get('additionalProperties') is False and set(value) - set(props): raise bc.ContractError(label + ': неизвестные поля.')
        for key, item in value.items():
            if key in props: check(item, props[key], label + '.' + key)
    elif kind == 'array':
        if not isinstance(value, list) or not schema.get('minItems', 0) <= len(value) <= schema.get('maxItems', float('inf')): raise bc.ContractError(label + ': некорректный список.')
        for item in value: check(item, schema['items'], label)
    elif kind == 'string':
        if not isinstance(value, str) or not schema.get('minLength', 0) <= len(value) <= schema.get('maxLength', float('inf')): raise bc.ContractError(label + ': некорректная строка.')
        if schema.get('pattern') and not re.fullmatch(schema['pattern'], value): raise bc.ContractError(label + ': некорректный ID.')
        if schema.get('format') == 'uuid' and not pipeline_runner.PipelineRunner.valid_id(value): raise bc.ContractError(label + ': ожидается UUID v4.')
    elif kind == 'integer':
        if type(value) is not int or value < schema.get('minimum', 0): raise bc.ContractError(label + ': некорректное целое число.')


def build(spec, store, reusable=False):
    definitions = store.get(spec['source_project_id'])['diagram']['definitions'] if spec.get('source_project_id') else []
    registry = subgraphs.Registry(definitions)
    graph = {'format': 'architect', 'version': 4, 'name': spec['name'], 'types': [], 'nodes': [], 'edges': [], 'definitions': definitions}
    kinds = {}
    for item in spec['blocks']:
        contract = registry.get(item['kind'])
        # Unknown settings must not be silently dropped by contract normalization.
        for key, collection in [('settings', contract['settings']), ('inputs', contract['inputs'])]:
            known = {p['id'] for p in collection}
            if set(item.get(key, {})) - known: raise bc.ContractError(item['id'] + ': неизвестные ' + key + '. Сначала прочитайте каталог блоков.')
        if item['kind'] not in kinds:
            type_id = '_mcp_type_' + str(len(kinds)); kinds[item['kind']] = type_id
            graph['types'].append({'id': type_id, 'name': contract['label'], 'description': '', 'color': '#5368e8',
                                   'block': {'kind': item['kind'], 'version': contract['version']}})
        graph['nodes'].append({'id': item['id'], 'typeId': kinds[item['kind']], 'name': item.get('name') or contract['label'],
                               'description': item.get('description', ''), 'x': 0, 'y': 0,
                               'block': {'kind': item['kind'], 'version': contract['version'], 'settings': item.get('settings', {}), 'inputs': item.get('inputs', {})}})
    for i, edge in enumerate(spec['connections']):
        graph['edges'].append({'id': '_mcp_edge_' + str(i), 'kind': 'data', 'from': edge['from'], 'to': edge['to'],
                               'fromPort': edge['from_port'], 'toPort': edge['to_port']})
    graph, registry = subgraphs.normalize(graph)
    expanded, groups = subgraphs.expand(graph, registry)
    checked, order = (expanded, []) if reusable else pipeline_runner.validate(expanded)
    # Layers in the top-level graph keep branches readable without requiring UI coordinates.
    pending = list(graph['nodes']); layers = {}; rows = {}
    while pending:
        progress = False
        for node in pending[:]:
            parents = [e['from'] for e in graph['edges'] if e['to'] == node['id']]
            if all(parent in layers for parent in parents):
                layer = max((layers[parent] + 1 for parent in parents), default=0)
                layers[node['id']] = layer; row = rows.get(layer, 0); rows[layer] = row + 1
                node.update(x=60 + layer * 270, y=80 + row * 210)
                pending.remove(node); progress = True
        if not progress: raise bc.ContractError('В схеме есть цикл.')
    warnings = ['Проверка статическая: данные не скачивались, код и обучение не запускались.']
    if any(n['block']['kind'] == 'python_code' for n in checked['nodes']):
        warnings.append('Python: стандартная библиотека, NumPy, pandas, scikit-learn. Блок выполняется локально.')
    return graph, {'valid': True, 'order': [{'id': key, 'name': next(n['name'] for n in checked['nodes'] if n['id'] == key)} for key in order], 'warnings': warnings}


def compact(project):
    graph = project['diagram']
    return {'name': project['project']['name'], 'description': project['description'], 'source_project_id': project['project']['id'],
            'blocks': [{'id': n['id'], 'kind': n['block']['kind'], 'name': n['name'], 'description': n['description'],
                        'inputs': n['block']['inputs'], 'settings': n['block']['settings']} for n in graph['nodes']],
            'connections': [{'from': e['from'], 'to': e['to'], 'from_port': e['fromPort'], 'to_port': e['toPort']} for e in graph['edges'] if e['kind'] == 'data']}


def block_validation(graph, registry, node_id):
    """Validate a reusable instance, permitting only its declared external inputs."""
    node = next(n for n in graph['nodes'] if n['id'] == node_id)
    def leaf(kind, port, path):
        definition = registry.definitions[kind]
        target = next(b['target'] for b in definition['inputs'] if b['id'] == port)
        inner = next(n for n in definition['graph']['nodes'] if n['id'] == target['node'])
        if inner['block']['kind'] in registry.definitions:
            return leaf(inner['block']['kind'], target['port'], [*path, inner['id']])
        return ('n_' + subgraphs.digest([*path, inner['id']])[:32], target['port'])
    exposed = {leaf(node['block']['kind'], p['id'], [node_id]) for p in registry.get(node['block']['kind'])['inputs']}
    expanded, _ = subgraphs.expand(graph, registry)
    checked, order = pipeline_runner.validate(expanded, external_inputs=exposed)
    return {'valid': True, 'kind': node['block']['kind'], 'contract': registry.get(node['block']['kind']),
            'steps': len(order), 'warnings': ['Проверка статическая. Внешние входы подключаются в пайплайне; код не запускался.']}


def block_graph(spec, store):
    inner, _ = build(spec['pipeline'], store, reusable=True)
    registry = subgraphs.Registry(inner['definitions'])
    raw = {'version': 1, 'name': spec['pipeline']['name'], 'description': spec['pipeline'].get('description', ''),
           'graph': inner, **{key: spec[key] for key in ('inputs', 'outputs', 'settings')}}
    # Changing source code creates a new immutable definition, never an instance setting.
    def source_setting(kind, port):
        if kind == 'python_code': return port == 'code'
        if kind not in registry.definitions: return False
        target = next(b['target'] for b in registry.definitions[kind]['settings'] if b['id'] == port)
        node = next(n for n in registry.definitions[kind]['graph']['nodes'] if n['id'] == target['node'])
        return source_setting(node['block']['kind'], target['port'])
    definition, _ = registry.definition(raw)
    for binding in definition['settings']:
        target = binding['target']; node = next(n for n in inner['nodes'] if n['id'] == target['node'])
        if source_setting(node['block']['kind'], target['port']):
            raise bc.ContractError('Код Python закрепляется внутри версии блока. Публикуйте params, а не code, как настройку.')
    kind = 'subgraph_' + subgraphs.digest(definition)
    definition['kind'] = kind
    definitions = {**registry.definitions, kind: definition}
    graph = block_instance_graph(kind, definitions)
    graph, registry = subgraphs.normalize(graph)
    return graph, block_validation(graph, registry, 'custom')


def block_instance_graph(kind, definitions):
    needed = set()
    def visit(key):
        if key in needed or key not in definitions: return
        needed.add(key)
        for node in definitions[key]['graph']['nodes'] + definitions[key]['graph']['types']:
            visit(node['block']['kind'])
    visit(kind)
    definition = definitions[kind]
    return {'format': 'architect', 'version': 4, 'name': definition['name'],
            'definitions': [definitions[key] for key in sorted(needed)], 'edges': [],
            'types': [{'id': 'custom_type', 'name': definition['name'], 'description': definition['description'],
                       'color': '#6366f1', 'block': {'kind': kind, 'version': 1}}],
            'nodes': [{'id': 'custom', 'typeId': 'custom_type', 'name': definition['name'],
                       'description': definition['description'], 'x': 60, 'y': 80, 'block': {'kind': kind, 'version': 1}}]}


def create_private(store, body, request_id, namespace):
    with project_store.LOCK:
        prefix = namespace + ':' + request_id + ':'
        operation = prefix + subgraphs.digest(body)
        for item in store.listing()['projects']:
            meta = store.read(store.folder(item['id']) + '/project.json')
            matches = [k for k in meta.get('applied_operations', {}) if k.startswith(prefix)]
            if matches:
                if operation not in matches: raise bc.ContractError('request_id уже использован для другого содержимого.', 409)
                return meta, True
        return store.save(body, create=True, operation_id=operation)['project'], False


def call(hub, user, name, args, origin):
    definition = next((t for t in TOOLS if t['name'] == name), None)
    if not definition: raise bc.ContractError('Неизвестный инструмент.')
    check(args, definition['inputSchema'])
    if user is None: raise bc.ContractError('Для MCP нужен аккаунт.', 401)
    store = hub.workspace(user)
    if name == 'architect_get_guide':
        return {'uri': GUIDE_URI, 'mimeType': 'text/markdown', 'text': INSTRUCTIONS}
    if name == 'architect_block_catalog':
        result = deepcopy(bc.CATALOG)
        if args.get('project_id'):
            result['blocks'] += store.get(args['project_id'])['contracts']
            result['blocks'] = list({b['kind']: b for b in result['blocks']}.values())
        return result
    if name == 'architect_list_projects': return store.listing()
    if name == 'architect_get_project':
        project = store.get(args['project_id'])
        return {'project': project['project'], 'pipeline': compact(project), 'diagram': project['diagram'],
                'editor_url': origin + '/architecture.html?project=' + project['project']['id']}
    spec = args['pipeline']
    if name == 'architect_update_pipeline' and not spec.get('source_project_id'):
        spec = dict(spec, source_project_id=args['project_id'])
    graph, validation = build(spec, store)
    if name == 'architect_validate_pipeline': return validation
    body = {'diagram': graph, 'name': args['pipeline']['name'], 'description': args['pipeline'].get('description', '')}
    with project_store.LOCK:
        if name == 'architect_create_pipeline':
            meta, reused = create_private(store, body, args['request_id'], 'mcp')
            return {'project': meta, 'reused': reused, 'editor_url': origin + '/architecture.html?project=' + meta['id'], **validation}
        else:
            existing = store.get(args['project_id'])
            if 'description' not in args['pipeline']:
                body['description'] = existing['description']
            if existing['project'].get('contract_lock'):
                hub.check_pins({'builtins': existing['project']['contract_lock']})
            # Compact editing preserves annotations and layout for surviving nodes.
            old = {n['id']: n for n in existing['diagram']['nodes']}
            for node in graph['nodes']:
                if node['id'] in old:
                    for key in ('x','y','width','height'):
                        if key in old[node['id']]: node[key] = old[node['id']][key]
            node_ids = {n['id'] for n in graph['nodes']}
            graph['edges'] += [e for e in existing['diagram']['edges'] if e['kind'] == 'annotation' and e['from'] in node_ids and e['to'] in node_ids]
            project = store.save({**body, 'project_id': args['project_id'], 'revision': args['revision']})
    return {'project': project['project'], 'editor_url': origin + '/architecture.html?project=' + project['project']['id'], **validation}


def rpc(hub, user, message, origin):
    identity = message.get('id') if isinstance(message, dict) else None
    def error(code, text): return {'jsonrpc': '2.0', 'id': identity, 'error': {'code': code, 'message': text}}
    if not isinstance(message, dict) or message.get('jsonrpc') != '2.0' or not isinstance(message.get('method'), str):
        return error(-32600, 'Invalid JSON-RPC request')
    if 'id' not in message:
        return None  # Notifications never invoke tools.
    if type(identity) not in (str, int):
        identity = None
        return error(-32600, 'Invalid request id')
    method = message['method']; params = message.get('params', {})
    if not isinstance(params, dict): return error(-32602, 'Invalid params')
    if method == 'initialize':
        version = params.get('protocolVersion')
        result = {'protocolVersion': version if version in PROTOCOLS else PROTOCOLS[0],
                  'capabilities': {'tools': {'listChanged': False}, 'resources': {'subscribe': False, 'listChanged': False}}, 'serverInfo': {'name': 'architect', 'version': '1.1.0'}, 'instructions': INSTRUCTIONS}
    elif method == 'ping': result = {}
    elif method == 'resources/list': result = {'resources': [GUIDE_RESOURCE]}
    elif method == 'resources/templates/list': result = {'resourceTemplates': []}
    elif method == 'resources/read':
        if not isinstance(params.get('uri'), str): return error(-32602, 'Expected resource URI')
        if params['uri'] != GUIDE_URI: return error(-32002, 'Resource not found')
        result = {'contents': [{'uri': GUIDE_URI, 'mimeType': 'text/markdown', 'text': INSTRUCTIONS}]}
    elif method == 'tools/list': result = {'tools': TOOLS}
    elif method == 'tools/call':
        if not isinstance(params.get('name'), str) or params['name'] not in {t['name'] for t in TOOLS}: return error(-32602, 'Unknown tool')
        try:
            value = call(hub, user, params['name'], params.get('arguments', {}), origin)
            result = {'content': [{'type': 'text', 'text': json.dumps(value, ensure_ascii=False)}], 'structuredContent': value, 'isError': False}
        except bc.ContractError as exc:
            result = {'content': [{'type': 'text', 'text': str(exc)}], 'isError': True}
    else: return error(-32601, 'Method not found')
    return {'jsonrpc': '2.0', 'id': identity, 'result': result}

