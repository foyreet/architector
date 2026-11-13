"""Explicit step execution plans. Reuse only verified, unchanged dependency chains."""
from copy import deepcopy
import hashlib
import json

import block_contracts as bc
import ml_operations as ml


def links(graph, identity):
    return sorted((e['from'], e['fromPort'], e['toPort']) for e in graph['edges'] if e['kind'] == 'data' and e['to'] == identity)


def check_outputs(runner, step, contract):
    outputs = step.get('outputs', {})
    for port in contract['outputs']:
        if port['id'] not in outputs: raise bc.ContractError('Отсутствует выход блока.')
        value = outputs[port['id']]; bc.validate_value(value, port)
        if isinstance(value, dict) and value.get('type') == 'artifact':
            kind = value['kind']
            if kind in ml.ARTIFACT_TYPES: ml.load(runner.root, value, kind)
            elif kind == 'dataset':
                expected = step.get('versions', {}).get('archive_sha256')
                if not expected: raise bc.ContractError('В истории нет хеша датасета.')
                digest = hashlib.sha256()
                with runner.kaggle.archive_path(runner.kaggle.dataset_handle(value['id'])).open('rb') as source:
                    for chunk in iter(lambda: source.read(1024 * 1024), b''): digest.update(chunk)
                if digest.hexdigest() != expected: raise bc.ContractError('Файл датасета изменился.')
            elif kind == 'model':
                saved = step.get('versions', {}).get('files')
                current = runner.huggingface.read_manifest(value['id'], value['revision'])['files']
                if not saved or any(f not in current for f in saved): raise bc.ContractError('Файлы модели изменились или недоступны.')
                folder = runner.huggingface.model_folder(value['id'], value['revision'])
                for file in saved:
                    path = runner.huggingface.checked_path(folder / file['name'])
                    stat = path.stat()
                    if stat.st_size != file['size'] or stat.st_mtime_ns != file['mtime_ns']: raise bc.ContractError('Файлы модели изменились.')


def plan(runner, diagram, order, groups, debug):
    if not isinstance(debug, dict) or set(debug) - {'action', 'node_id', 'base_run_id'} or debug.get('action') not in ('step', 'continue'):
        raise bc.ContractError('Выберите выполнение блока или продолжение схемы.')
    selected = debug.get('node_id')
    if debug['action'] == 'step':
        if not isinstance(selected, str): raise bc.ContractError('Выберите блок.')
        targets = set((groups or {}).get(selected, [selected])) & set(order)
        if not targets: raise bc.ContractError('Выбранный блок не выполняет операцию.', 400)
    else: targets = set()
    base = None; old_nodes = {}; contracts = {}
    if debug.get('base_run_id'):
        base = runner.get(debug['base_run_id'])
        if base['status'] in ('waiting', 'running'): raise bc.ContractError('Дождитесь завершения текущего шага.', 409)
        if base.get('imported'): raise bc.ContractError('Импортированную историю можно просматривать, но нельзя использовать для продолжения. Начните новый запуск.')
        old_nodes = {n['id']: n for n in base['diagram']['nodes']}
        contracts = {c['kind']: c for c in base.get('contracts', [])}
    nodes = {n['id']: n for n in diagram['nodes']}
    reuse, reasons = {}, {}
    for identity in order:
        node = nodes[identity]; old = old_nodes.get(identity); contract = bc.CONTRACTS[node['block']['kind']]
        if identity in targets: continue
        if not old or old['block'] != node['block'] or links(diagram, identity) != links(base['diagram'], identity): continue
        if base['nodes'].get(identity, {}).get('status') != 'ready': continue
        if contracts.get(node['block']['kind']) != contract: continue
        if any(source not in reuse for source, _, _ in links(diagram, identity)): continue
        try:
            step = runner.step(base['id'], identity)
            if step.get('status') != 'ready': continue
            check_outputs(runner, step, contract)
            reuse[identity] = step
        except (bc.ContractError, OSError, runner.kaggle.KaggleError, runner.huggingface.HubError) as error:
            reasons[identity] = str(error)
    execute = [i for i in order if i in targets] if debug['action'] == 'step' else [i for i in order if i not in reuse]
    blocked, inputs = [], []
    for identity in execute:
        node = nodes[identity]; block = deepcopy(node['block']); sources = []
        for source, port, target_port in links(diagram, identity):
            sources.append({'port': target_port, 'node_id': source, 'node': nodes[source]['name'], 'output': port, 'ready': source in reuse})
            if source in reuse: block['inputs'][target_port] = deepcopy(reuse[source]['outputs'][port])
            else:
                block['inputs'].pop(target_port, None)
                if source not in execute: blocked.append({'node_id': source, 'source_root': next((key for key, ids in (groups or {}).items() if source in ids), source), 'name': nodes[source]['name'], 'input': target_port, 'consumer': node['name']})
        inputs.append({'node_id': identity, 'name': node['name'], 'inputs': block['inputs'], 'settings': block['settings'], 'sources': sources})
    result = {'base_run_id': base['id'] if base else None, 'action': debug['action'], 'blocked': blocked,
              'execute': [{'id': i, 'name': nodes[i]['name'], 'kind': nodes[i]['block']['kind']} for i in execute],
              'reused': [{'id': i, 'name': nodes[i]['name']} for i in order if i in reuse],
              'remaining': [i for i in order if i not in reuse and i not in execute], 'inputs': inputs, 'invalidated': reasons}
    result['digest'] = hashlib.sha256(json.dumps({'diagram': diagram, 'debug': debug, 'plan': result}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return result, reuse

