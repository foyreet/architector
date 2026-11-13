"""Bounded, durable experiment batches; one scheduled run at a time per server."""
from copy import deepcopy
from itertools import product
import hashlib
import json
import threading
import time
import uuid

import block_contracts as bc
import pipeline_runner as pr
import project_store as ps
import project_insights
import ml_operations
import subgraphs
import gpu_compute

LOCK = pr.CREATION_LOCK


def prepare(context, body):
    project = ps.ProjectStore(context.root).get(body.get('project_id'))
    if body.get('revision') != project['project']['revision']: raise bc.ContractError('Редакция проекта изменилась. Обновите форму.', 409)
    from local_workspace import Community
    if project['project'].get('contract_lock'): Community.check_pins({'builtins': project['project']['contract_lock']})
    graph = project['diagram']; axes = body.get('axes')
    if not isinstance(axes, list) or not 1 <= len(axes) <= 2: raise bc.ContractError('Выберите один или два параметра.')
    seen = set()
    for axis in axes:
        if not isinstance(axis, dict) or set(axis) != {'node_id', 'setting', 'values'}: raise bc.ContractError('Некорректный параметр перебора.')
        node = next((n for n in graph['nodes'] if n['id'] == axis['node_id']), None)
        if not node: raise bc.ContractError('Блок не найден.')
        setting = next((s for s in bc.CONTRACTS.get(node['block']['kind'], {}).get('settings', []) if s['id'] == axis['setting']), None)
        if not setting or setting['type'] not in ('integer', 'number'): raise bc.ContractError('Для перебора выберите числовую настройку встроенного блока.')
        key = (axis['node_id'], axis['setting'])
        if key in seen: raise bc.ContractError('Параметр повторяется.')
        seen.add(key)
        values = axis['values']
        if not isinstance(values, list) or not 1 <= len(values) <= 10 or any(type(v) not in (int, float) for v in values): raise bc.ContractError('Введите от 1 до 10 числовых значений.')
        if len(set(values)) != len(values): raise bc.ContractError('Уберите повторяющиеся значения.')
    combinations = list(product(*(a['values'] for a in axes)))
    if len(combinations) > 20: raise bc.ContractError('Не более 20 запусков в одной серии.')
    research = project_insights.plan({**project['project'].get('research', {}), 'metric': body.get('metric', ''), 'direction': body.get('direction', 'max')})
    if not research['metric']: raise bc.ContractError('Выберите основную метрику.')
    variants = []
    for values in combinations:
        variant = deepcopy(graph); parameters = []
        for axis, value in zip(axes, values):
            node = next(n for n in variant['nodes'] if n['id'] == axis['node_id'])
            node['block']['settings'][axis['setting']] = value
            parameters.append({'node_id': node['id'], 'node': node['name'], 'setting': axis['setting'], 'value': value})
        variant, registry = subgraphs.normalize(variant)
        expanded, _ = subgraphs.expand(variant, registry); pr.validate(expanded)
        node_id, separator, metric = research['metric'].partition('/')
        metric_node = next((n for n in expanded['nodes'] if n['id'] == node_id), None)
        if not separator or not metric or not metric_node or metric_node['block']['kind'] not in ('ml_evaluate', 'python_code'): raise bc.ContractError('Укажите метрику блока оценки или числовой ключ отчёта Python: ID блока/accuracy.')
        if metric_node['block']['kind'] == 'ml_evaluate' and metric not in ('accuracy', 'macro_f1', 'test_rows'): raise bc.ContractError('Доступные метрики оценки: accuracy, macro_f1, test_rows.')
        variants.append({'diagram': variant, 'parameters': parameters})
    payload = {'project': {k: project['project'][k] for k in ('id', 'revision', 'name')}, 'research': research, 'variants': variants}
    payload['compute'] = gpu_compute.resolve(context.kaggle.ROOT, pr.uses_gpu(expanded,context.kaggle.ROOT), body.get('compute'))
    if payload['compute']['mode'] == 'gpu': payload['gpu_executor'] = {k: v for k, v in payload['compute'].items() if k != 'mode'}
    digest = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return payload, digest


def active(server):
    if getattr(server, 'lab_inference', False): return True
    contexts = [server] + [c.server for c in getattr(server, 'account_contexts', {}).values()]
    return any(getattr(r, 'active_runs', None) or r.current and r.current['status'] in pr.ACTIVE for s in contexts for r in
               list(getattr(s, 'project_runners', {}).values()) + ([s.pipeline_runner] if hasattr(s, 'pipeline_runner') else []))


class Queue:
    def __init__(self, server):
        self.server = server; self.jobs = []; self.thread = None

    def store(self, context): return ps.ProjectStore(context.root)
    def path(self, identity):
        if not pr.PipelineRunner.valid_id(identity): raise bc.ContractError('Некорректная серия.')
        return 'workspace/experiment-queue/' + identity + '.json'
    def write(self, context, record): self.store(context).write(self.path(record['id']), record)
    def read(self, context, identity): return self.store(context).read(self.path(identity))
    def current(self, context, identity): return any(str(c.kaggle.ROOT) == str(context.kaggle.ROOT) and i == identity for c, i, _ in self.jobs)

    def get(self, context, identity):
        with LOCK:
            record = self.read(context, identity)
            if record['status'] in ('queued', 'running', 'cancelling') and not self.current(context, identity):
                record['status'] = 'cancelled' if record['status'] == 'cancelling' else 'interrupted'
                for item in record['items']:
                    if item['status'] == 'running':
                        item.update(status='error', error='Сервер был перезапущен. Проверьте историю; автоматический повтор не выполнен.')
                self.write(context, record)
            return record

    def listing(self, context, project_id):
        self.store(context).get(project_id)
        folder = self.store(context).path('workspace/experiment-queue')
        records = []
        if folder.exists():
            for path in folder.glob('*.json'):
                record = self.get(context, path.stem)
                if record['project']['id'] == project_id: records.append(record)
        return sorted(records, key=lambda r: r['created_at'], reverse=True)[:50]

    def submit(self, context, body):
        self.validate_secrets(body.get('secrets', {}))
        identity = body.get('request_id'); relative = self.path(identity)
        signature = hashlib.sha256(json.dumps({k: body.get(k) for k in ('project_id', 'revision', 'axes', 'metric', 'direction', 'digest', 'compute')}, sort_keys=True).encode()).hexdigest()
        with LOCK:
            if self.store(context).path(relative).exists():
                existing = self.get(context, identity)
                if existing.get('request_signature') != signature: raise bc.ContractError('ID уже использован другой серией.', 409)
                return existing
        payload, digest = prepare(context, body)
        if digest != body.get('digest'): raise bc.ContractError('План изменился. Проверьте его заново.', 409)
        with LOCK:
            if self.store(context).path(relative).exists():
                existing = self.get(context, identity)
                if existing.get('request_signature') != signature: raise bc.ContractError('ID уже использован другой серией.', 409)
                return existing
            if len(self.jobs) >= 10: raise bc.ContractError('Очередь сервера заполнена. Дождитесь завершения серий.', 409)
            record = {'id': identity, 'created_at': pr.now(), 'status': 'queued', 'digest': digest, 'request_signature': signature, 'project': payload['project'], 'research': payload['research'],
                      'items': [{'run_id': str(uuid.uuid4()), 'status': 'queued', **v} for v in payload['variants']]}
            if payload.get('gpu_executor'): record['gpu_executor'] = payload['gpu_executor']
            record['compute'] = {'mode': payload['compute']['mode'], **({'device_id': payload['compute']['id']} if payload['compute']['mode'] == 'gpu' else {})}
            self.write(context, record)
            self.enqueue(context, identity, body.get('secrets', {}))
            return record

    @staticmethod
    def validate_secrets(secrets):
        if not isinstance(secrets, dict) or set(secrets) - {'openrouter', 'kaggle', 'huggingface'} or any(not isinstance(v, str) or len(v) > 2048 for v in secrets.values()): raise bc.ContractError('Некорректные ключи подключений.')

    def enqueue(self, context, identity, secrets):
        self.validate_secrets(secrets)
        self.jobs.append((context, identity, dict(secrets)))
        if not self.thread or not self.thread.is_alive():
            self.thread = threading.Thread(target=self.safe_work, daemon=True); self.thread.start()

    def safe_work(self):
        try: self.work()
        except Exception:
            with LOCK:
                for context, identity, secrets in self.jobs:
                    secrets.clear()
                    try:
                        record = self.read(context, identity); record['status'] = 'interrupted'
                        for item in record['items']:
                            if item['status'] == 'running': item.update(status='error', error='Очередь остановлена. Проверьте историю запуска перед повтором.')
                        self.write(context, record)
                    except (bc.ContractError, OSError): pass
                self.jobs.clear()

    def cancel(self, context, identity):
        with LOCK:
            record = self.get(context, identity)
            if record['status'] in ('cancelled', 'finished'): return record
            for item in record['items']:
                if item['status'] == 'queued': item['status'] = 'cancelled'
            record['status'] = 'cancelling' if any(i['status'] == 'running' for i in record['items']) else 'cancelled'
            self.write(context, record); return record

    def resume(self, context, body):
        with LOCK:
            record = self.get(context, body.get('id'))
            if record['status'] != 'interrupted' or not any(i['status'] == 'queued' for i in record['items']): raise bc.ContractError('Нет ожидающих запусков для продолжения.')
            if len(self.jobs) >= 10: raise bc.ContractError('Очередь сервера заполнена.', 409)
            self.enqueue(context, record['id'], body.get('secrets', {})); record['status'] = 'queued'; self.write(context, record); return record

    def work(self):
        while True:
            with LOCK:
                if not self.jobs: return
                context, identity, secrets = self.jobs[0]
                record = self.read(context, identity)
                item = next((i for i in record['items'] if i['status'] == 'queued'), None)
                if not item:
                    if record['status'] not in ('cancelled', 'cancelling'): record['status'] = 'finished'
                    else: record['status'] = 'cancelled'
                    self.write(context, record); self.jobs.pop(0); secrets.clear(); continue
                if active(self.server) or ml_operations.WORKER_LOCK.locked(): runner = None
                else:
                    item['status'] = 'running'; record['status'] = 'running'; self.write(context, record)
                    try:
                        context.pipeline.request(context.server, {'project_id': record['project']['id']}, 'runs', context.completion, context.kaggle, context.huggingface)
                        runner = context.server.project_runners[record['project']['id']]
                        run = runner.start({'diagram': item['diagram'], 'run_id': item['run_id'], '_project': record['project'], '_plan': record['research'], 'secrets': secrets,
                                            '_gpu_executor': record.get('gpu_executor', {}).get('id'), 'compute': record.get('compute')})
                    except Exception as exc:
                        item.update(status='error', error=str(exc) if isinstance(exc, bc.ContractError) else 'Не удалось запустить вариант. Проверьте сервер.'); self.write(context, record); continue
            if runner is None:
                time.sleep(.25); continue
            runner.thread.join()
            with LOCK:
                latest = self.read(context, identity)
                item = next(i for i in latest['items'] if i['run_id'] == run['id'])
                result = runner.get(run['id']); item['status'] = result['status']; item['error'] = result.get('error')
                metric_key = latest['research']['metric']
                try:
                    node_id, metric = metric_key.split('/', 1)
                    step = runner.step(run['id'], node_id)
                    item['metric'] = project_insights.metrics(step['block']['kind'], step).get(metric)
                except (bc.ContractError, ValueError): item['metric'] = None
                if item['status'] == 'ready' and item.get('metric') is None: item['error'] = 'Основная метрика отсутствует в результате. Вариант не участвует в выборе лучшего.'
                self.write(context, latest)


def public(record):
    record = deepcopy(record)
    for item in record['items']: item.pop('diagram', None)
    successful = [i for i in record['items'] if i['status'] == 'ready' and type(i.get('metric')) in (int, float)]
    record['best_run_id'] = (min if record['research']['direction'] == 'min' else max)(successful, key=lambda i: i['metric'])['run_id'] if successful else None
    return record


def request(server, context, body, action):
    with LOCK:
        if not hasattr(server, 'experiment_queue'): server.experiment_queue = Queue(server)
        queue = server.experiment_queue
    if action == 'preview':
        payload, digest = prepare(context, body)
        return {'digest': digest, 'count': len(payload['variants']), 'variants': [v['parameters'] for v in payload['variants']], 'research': payload['research']}
    if action == 'start': return public(queue.submit(context, body))
    if action == 'list': return {'series': [public(r) for r in queue.listing(context, body.get('project_id'))]}
    if action == 'get': return public(queue.get(context, body.get('id')))
    if action == 'cancel': return public(queue.cancel(context, body.get('id')))
    if action == 'resume': return public(queue.resume(context, body))
    raise bc.ContractError('Маршрут не найден.', 404)

