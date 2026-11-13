"""Private immutable model versions and bearer-authenticated, pinned inference APIs."""
from copy import deepcopy
import hashlib
import hmac
import math
from pathlib import Path
import secrets
import threading
import uuid

import analysis_tools as analysis
import block_contracts as bc
import gpu_compute as gpu
import ml_operations as ml
import pipeline_runner as pr
import project_store as ps
from app_config import data_root

LOCK = threading.RLock()
REGISTRY = 'workspace/model-registry/index.json'
ENDPOINTS = 'workspace/model-endpoints/index.json'


def registry(root):
    store = ps.ProjectStore(root)
    return store.read(REGISTRY) if store.path(REGISTRY).exists() else {'families': []}


def find_version(root, identity):
    if not pr.PipelineRunner.valid_id(identity): raise bc.ContractError('Некорректная версия модели.')
    for family in registry(root)['families']:
        for version in family['versions']:
            if version['id'] == identity: return family, version
    raise bc.ContractError('Версия модели не найдена.', 404)


def endpoint_store(): return ps.ProjectStore(data_root())


def endpoints():
    store = endpoint_store()
    return store.read(ENDPOINTS) if store.path(ENDPOINTS).exists() else {}


def save_endpoints(value):
    store = endpoint_store(); store.write(ENDPOINTS, value); store.path(ENDPOINTS).chmod(0o600)


def scope(root): return str(Path(root).resolve().relative_to(Path(data_root()).resolve()))


def bundle(root, version):
    value = ml.load(root, version['artifact'], 'model_bundle')
    if value.get('format') != 'architect.model-package' or value['model'].get('format') not in ('architect.random-forest', gpu.FORMAT):
        raise bc.ContractError('Этот формат модели нельзя использовать для предсказаний.')
    return value


def compare(a, b):
    keys = sorted(set(a['metrics']) | set(b['metrics']))
    return {'metrics': [{'metric': k, 'before': a['metrics'].get(k), 'after': b['metrics'].get(k),
                         'delta': b['metrics'][k] - a['metrics'][k] if type(a['metrics'].get(k)) in (int,float) and type(b['metrics'].get(k)) in (int,float) else None} for k in keys],
            'same_dataset': a['dataset_sha256'] == b['dataset_sha256'], 'same_split': a['split'] == b['split'],
            'settings': {'before': a['settings'], 'after': b['settings']},
            'features': {'before': a['features'], 'after': b['features']}}


def register(context, body):
    origin = body.get('origin')
    if not isinstance(origin, dict) or not isinstance(origin.get('port'),str): raise bc.ContractError('Выберите результат сохранения модели в истории запуска.')
    fields = {k: origin.get(k) for k in ('project_id','run_id','node_id')}
    step = context.pipeline.request(context.server, fields, 'step', context.completion, context.kaggle, context.huggingface)
    ref = step.get('outputs', {}).get(origin.get('port'))
    if step.get('status') != 'ready' or not isinstance(ref, dict) or ref.get('kind') != 'model_bundle': raise bc.ContractError('Нужен завершённый блок «Сохранение модели».')
    run = context.pipeline.request(context.server, fields, 'run', context.completion, context.kaggle, context.huggingface)
    value = bundle(context.kaggle.ROOT, {'artifact': ref}); model = value['model']
    state = registry(context.kaggle.ROOT); family_id = body.get('family_id')
    if family_id:
        family = next((f for f in state['families'] if f['id'] == family_id), None)
        if not family: raise bc.ContractError('Семейство модели не найдено.', 404)
    else:
        name = body.get('name', value.get('name','Модель'))
        if not isinstance(name,str) or not name.strip(): raise bc.ContractError('Введите название модели.')
        family = next((f for f in state['families'] if f['name'].casefold()==name.strip().casefold()),None)
        if not family:
            family = {'id': str(uuid.uuid4()), 'name': name.strip(), 'versions': [], 'best_version_id': None}
            state['families'].append(family)
    origin = {k: origin.get(k) for k in ('project_id','run_id','node_id','port')}
    existing = next((v for v in family['versions'] if v['origin'] == origin and v['artifact'] == ref), None)
    if existing: return {'family': family, 'version': existing}
    metrics = {k:v for k,v in value.get('metrics', {}).items() if type(v) in (int,float) and math.isfinite(v)}
    version = {'id': str(uuid.uuid4()), 'number': len(family['versions']) + 1, 'created_at': pr.now(), 'artifact': ref,
               'origin': origin, 'project': run.get('project', {}), 'run_created_at': run['created_at'],
               'dataset_sha256': value['source_sha256'], 'preparation': value['preparation'], 'split': value['split'],
               'features': model['features'], 'target': model['target'], 'classes': model['classes'],
               'settings': model['settings'], 'metrics': metrics, 'versions': model['versions'], 'format': model['format']}
    family['versions'].append(version); ps.ProjectStore(context.kaggle.ROOT).write(REGISTRY,state)
    return {'family': family, 'version': version}


def public_endpoint(entry, root):
    try:
        family, version = find_version(root, entry['version_id']); model = bundle(root, version)['model']
        ready, reason = entry['enabled'], '' if entry['enabled'] else 'API отключён.'
        if model['format'] == gpu.FORMAT and ready:
            try: gpu.broker().selected(root, entry['compute']['device_id'])
            except bc.ContractError as exc: ready, reason = False, str(exc)
        return {k:entry[k] for k in ('id','version_id','enabled','created_at','compute')} | {
            'family':family['name'],'number':version['number'],'features':model['features'], 'available':ready,'reason':reason,
            'path':'/api/inference/'+entry['id'], 'calls':entry.get('calls',0), 'last_call':entry.get('last_call')}
    except bc.ContractError:
        return {k:entry[k] for k in ('id','version_id','enabled','created_at','compute')} | {'available':False,'reason':'Файл модели недоступен.','path':'/api/inference/'+entry['id']}


def manage(context, body, action):
    root = context.kaggle.ROOT
    with LOCK:
        if action == 'list': return registry(root)
        if action == 'register': return register(context, body)
        if action == 'compare':
            a, va = find_version(root,body.get('before')); b, vb = find_version(root,body.get('after'))
            if a['id'] != b['id']: raise bc.ContractError('Для сравнения выберите версии одной модели.')
            return compare(va,vb)
        if action == 'best':
            state = registry(root)
            family = next((f for f in state['families'] if f['id'] == body.get('family_id')),None)
            if not family or not any(v['id'] == body.get('version_id') for v in family['versions']): raise bc.ContractError('Версия не найдена.',404)
            family['best_version_id'] = body['version_id']; ps.ProjectStore(root).write(REGISTRY,state)
            return {'ok':True}
        entries = endpoints(); account = scope(root)
        if action == 'endpoints': return {'endpoints':[public_endpoint(e,root) for e in entries.values() if e['scope']==account]}
        if action == 'endpoint-create':
            _, version = find_version(root,body.get('version_id')); model = bundle(root,version)['model']
            compute = gpu.resolve(root, model['format']==gpu.FORMAT, body.get('compute'), require_available=False)
            identity = str(uuid.uuid4()); token = 'arch_predict_' + secrets.token_urlsafe(32)
            entry = {'id':identity,'scope':account,'version_id':version['id'],'token_hash':hashlib.sha256(token.encode()).hexdigest(),
                     'enabled':True,'created_at':pr.now(),'compute':{'mode':compute['mode'],**({'device_id':compute['id']} if compute['mode']=='gpu' else {})}}
            entries[identity]=entry;save_endpoints(entries)
            return {**public_endpoint(entry,root),'token':token}
        entry = entries.get(body.get('id')) if isinstance(body.get('id'),str) else None
        if not entry or entry['scope'] != account: raise bc.ContractError('API-подключение не найдено.',404)
        if action == 'endpoint-revoke':
            entry['enabled']=False;save_endpoints(entries);return {'ok':True}
        if action == 'endpoint-delete':
            if entry['enabled']: raise bc.ContractError('Сначала отключите API.')
            del entries[entry['id']];save_endpoints(entries);return {'ok':True}
        raise bc.ContractError('Маршрут не найден.',404)


def authorize(identity, token):
    with LOCK:
        entry = endpoints().get(identity) if pr.PipelineRunner.valid_id(identity) else None
        if not entry or not entry['enabled'] or not isinstance(token,str) or len(token)>150 or not hmac.compare_digest(entry['token_hash'],hashlib.sha256(token.encode()).hexdigest()):
            raise bc.ContractError('Нужен действующий токен этого API модели.',401)
        root = Path(data_root()) / entry['scope']
        return deepcopy(entry), root


def infer(entry, root, body):
    _,version=find_version(root,entry['version_id']);model=bundle(root,version)['model']
    rows=body.get('rows');bc.validate_value(rows,{'type':'rows'})
    if not rows:raise bc.ContractError('Передайте непустой массив rows с числовыми признаками.')
    compute=gpu.resolve(root,model['format']==gpu.FORMAT,entry['compute'])
    with gpu.execution(compute if compute['mode']=='gpu' else None,threading.Event()):
        result=analysis.infer_rows(root,model,rows)
    identity=str(uuid.uuid4())
    with LOCK:
        state=endpoints();current=state.get(entry['id'])
        if current:
            current['calls']=current.get('calls',0)+1;current['last_call']={'at':pr.now(),'request_id':identity,'rows':len(rows)};save_endpoints(state)
    return {'request_id':identity,'version_id':version['id'],'model_version':version['number'],
            'predictions':result['predictions'],'versions':result['versions']}

