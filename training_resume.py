"""Explicit continuation of a failed GPU step using its immutable run snapshot."""
from copy import deepcopy
import hashlib
import json
import uuid

import block_contracts as bc
import gpu_worker
import ml_operations as ml
import pipeline_debug


def checkpoint_path(record, node_id):
    return 'checkpoints/%04d.json' % record['order'].index(node_id)


def summary(runner, record):
    result = []
    for node_id in record['order']:
        if next(n for n in record['diagram']['nodes'] if n['id'] == node_id)['block']['kind'] != 'gpu_train': continue
        try:
            value = runner.read(record['id'], checkpoint_path(record, node_id))
            result.append({'node_id': node_id, 'name': record['nodes'][node_id]['name'], 'epoch': value['checkpoint']['epoch'],
                           'epochs': value['epochs'], 'saved_at': value['saved_at']})
        except bc.ContractError as exc:
            if exc.status != 404: raise
    return result


def candidate(runner, record):
    if record['status'] not in ('error', 'cancelled') or record.get('imported'): return None
    pending = next((i for i in record['order'] if record['nodes'][i]['status'] != 'ready'), None)
    return next((c for c in summary(runner, record) if c['node_id'] == pending), None)


def resume(runner, body):
    base = runner.get(body.get('run_id'))
    point = candidate(runner, base)
    if not point: raise bc.ContractError('Нет сохранённой точки для продолжения. Нужен остановленный GPU-блок с готовыми предыдущими шагами.')
    node_id = point['node_id']; envelope = runner.read(base['id'], checkpoint_path(base,node_id)); checkpoint = envelope['checkpoint']
    step = runner.step(base['id'], node_id); block = step['block']
    try:
        gpu_worker.validate_checkpoint(checkpoint, {'table': ml.load(runner.root,block['inputs']['train'],'table'), 'settings': block['settings']})
    except (ValueError, KeyError, TypeError, IndexError) as exc:
        raise bc.ContractError('Сохранённая точка несовместима: ' + str(exc)) from None
    source = deepcopy(base.get('source_diagram', base['diagram']))
    _, diagram, order, groups = runner.prepare({'diagram': source})
    debug = {'action':'continue', 'base_run_id':base['id']}
    plan, reused = pipeline_debug.plan(runner,diagram,order,groups,debug)
    prefix = order[:order.index(node_id)]
    if any(i not in reused for i in prefix) or not plan['execute'] or plan['execute'][0]['id'] != node_id:
        raise bc.ContractError('Предыдущие результаты изменились или недоступны. Продолжение из этой точки невозможно; начните новый запуск.')
    identity = body.get('new_run_id', str(uuid.uuid4()))
    metadata = {'run_id':base['id'],'node_id':node_id,'epoch':checkpoint['epoch'],
                'checkpoint_sha256':hashlib.sha256(json.dumps(checkpoint,sort_keys=True,allow_nan=False).encode()).hexdigest()}
    compute = body.get('compute') or {'mode':'gpu','device_id':base['gpu_executor']['id']}
    return runner.start({'run_id':identity,'diagram':source,'debug':debug,'plan_digest':plan['digest'],
                         'compute':compute,'secrets':body.get('secrets',{}),
                         '_project':base.get('project'),'_plan':base.get('experiment_plan',{}),
                         '_training_resume':{'metadata':metadata,'envelope':envelope,'step':{'node_id':node_id,'block':deepcopy(block),'status':'waiting'}}})

