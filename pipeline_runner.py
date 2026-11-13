"""Sequential, persistent DAG execution. Provider calls are never retried automatically."""

from collections import Counter, deque
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import threading
import uuid

import block_contracts as bc
import local_operations
import python_blocks
import subgraphs
import project_store
import gpu_compute
from app_config import data_root

ALLOW_ENVIRONMENT = True
ROOT = data_root()
CREATION_LOCK = threading.RLock()
ACTIVE = ('waiting', 'running')


def now():
    return datetime.now(timezone.utc).isoformat()


def uses_gpu(source, root=None):
    if not isinstance(source, dict): return False
    if source.get('definitions') or source.get('version') == 4:
        graph, registry = subgraphs.normalize(source)
        source, _ = subgraphs.expand(graph, registry)
    nodes = source.get('nodes') or []
    if not isinstance(nodes,list): raise bc.ContractError('Ожидается список блоков.')
    for node in nodes:
        block = node.get('block', {}) if isinstance(node,dict) else {}
        if not isinstance(block,dict): continue
        if block.get('kind') == 'gpu_train': return True
        ref = block.get('inputs',{}).get('model') if isinstance(block.get('inputs',{}),dict) else None
        if root and isinstance(ref,dict) and ref.get('kind') == 'trained_model':
            import ml_operations
            if ml_operations.load(root,ref,'trained_model').get('format') == gpu_compute.FORMAT: return True
    return False


def validate(diagram, external_inputs=frozenset()):
    """Return a credential-free execution snapshot and a stable topological order."""
    if not isinstance(diagram, dict) or diagram.get('format') != 'architect' or diagram.get('version') != 3:
        raise bc.ContractError('Для запуска нужна схема формата architect версии 3.')
    nodes, edges = diagram.get('nodes'), diagram.get('edges')
    if not isinstance(nodes, list) or not nodes or not isinstance(edges, list):
        raise bc.ContractError('Нужны блоки и список связей.')
    identifiers, index, snapshot = set(), {}, []
    def identifier(value):
        if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', value) or value in identifiers:
            raise bc.ContractError('Некорректный или повторяющийся ID блока/связи.')
        identifiers.add(value)
        return value
    for item in nodes:
        if not isinstance(item, dict):
            raise bc.ContractError('Некорректный блок.')
        node = {'id': identifier(item.get('id')), 'name': str(item.get('name', 'Блок'))[:100],
                'block': bc.normalize_block(item.get('block'))}
        index[node['id']] = node
        snapshot.append(node)
    incoming, links, outgoing = {}, [], {key: [] for key in index}
    degree = {key: 0 for key, node in index.items() if node['block']['kind'] != 'note'}
    for item in edges:
        if not isinstance(item, dict):
            raise bc.ContractError('Некорректная связь.')
        edge = {key: item.get(key) for key in ('id', 'from', 'to', 'fromPort', 'toPort', 'kind')}
        identifier(edge['id'])
        if not all(isinstance(edge[key], str) for key in edge) or edge['from'] not in index or edge['to'] not in index:
            raise bc.ContractError('Связь ссылается на неизвестный блок или порт.')
        if edge['kind'] == 'annotation' and edge['fromPort'] == edge['toPort'] == 'annotation':
            links.append(edge)
            continue
        if edge['kind'] != 'data' or edge['from'] == edge['to']:
            raise bc.ContractError('Некорректный тип связи или связь блока с самим собой.')
        source = bc.CONTRACTS[index[edge['from']]['block']['kind']]
        target = bc.CONTRACTS[index[edge['to']]['block']['kind']]
        output = next((p for p in source['outputs'] if p['id'] == edge['fromPort']), None)
        entry = next((p for p in target['inputs'] if p['id'] == edge['toPort']), None)
        if not output or not entry or output['type'] != entry['type']:
            raise bc.ContractError('Несовместимые типы или неизвестные порты соединения.')
        key = (edge['to'], edge['toPort'])
        if key in incoming:
            raise bc.ContractError('У входа блока может быть только один источник.')
        incoming[key] = edge
        outgoing[edge['from']].append(edge['to'])
        degree[edge['to']] += 1
        links.append(edge)
    for node in snapshot:
        block, name = node['block'], node['name']
        contract = bc.CONTRACTS[block['kind']]
        if block['kind'] == 'note':
            continue
        if not contract['operation']['available']:
            raise bc.ContractError(name + ': ' + contract['operation']['description'])
        for port in contract['inputs']:
            value = block['inputs'].get(port['id'])
            if port.get('required') and (node['id'], port['id']) not in incoming and (node['id'], port['id']) not in external_inputs and (value is None or isinstance(value, str) and not value.strip()):
                raise bc.ContractError(name + ': не задан вход «' + port['label'] + '».')
        settings = block['settings']
        if block['kind'] == 'openrouter' and not re.fullmatch(r'[a-zA-Z0-9~][a-zA-Z0-9_./:~@+-]{0,159}', settings['model']):
            raise bc.ContractError(name + ': укажите ID модели OpenRouter.')
        if block['kind'] == 'ml_prepare' and not settings['target'].strip():
            raise bc.ContractError(name + ': укажите целевую колонку.')
        if block['kind'] == 'python_code':
            python_blocks.check_settings(settings)
        if block['kind'] == 'template':
            local_operations.template_fields(settings['template'])
        if block['kind'] == 'huggingface' and not settings['files']:
            raise bc.ContractError(name + ': выберите файлы модели Hugging Face.')
    queue = deque(key for key, count in degree.items() if count == 0)
    order = []
    while queue:
        key = queue.popleft()
        order.append(key)
        for target in outgoing[key]:
            degree[target] -= 1
            if degree[target] == 0:
                queue.append(target)
    if len(order) != len(degree):
        raise bc.ContractError('В схеме есть цикл. Удалите циклические связи данных.')
    if not order:
        raise bc.ContractError('В схеме нет исполняемых блоков.')
    return {'format': 'architect', 'version': 3, 'name': str(diagram.get('name', 'Схема'))[:160],
            'nodes': snapshot, 'edges': links}, order


class PipelineRunner:
    def __init__(self, completion, kaggle, huggingface, root=None, runs_relative='workspace/runs'):
        self.root = Path(root or ROOT)
        self.completion, self.kaggle, self.huggingface = completion, kaggle, huggingface
        self.lock = threading.RLock()
        self.current = None
        self.active_runs = {}
        self.cancel_event = threading.Event()
        self.thread = None
        self.runs_relative = runs_relative
        self.path(self.runs_relative).mkdir(parents=True, exist_ok=True)
        # A crash may have happened after a paid call reached its provider. Do not repeat it.
        for folder in self.path(self.runs_relative).iterdir():
            if not self.valid_id(folder.name):
                continue
            try:
                record = self.read(folder.name)
                if record['status'] in ACTIVE:
                    record.update(status='error', finished_at=now(), error=(
                        'Сервер был остановлен во время ожидания. Запустите схему повторно.' if record['status'] == 'waiting' else
                        'Сервер был остановлен. Запрос мог быть обработан; автоматический повтор не выполнялся.'))
                    for step in record['nodes'].values():
                        if step['status'] in ACTIVE:
                            step['status'] = 'error' if step['status'] == 'running' else 'skipped'
                    self.event(record, record['error'])
                    self.save(record)
            except (bc.ContractError, KeyError, TypeError):
                continue

    @staticmethod
    def valid_id(value):
        return isinstance(value, str) and re.fullmatch(r'[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}', value)

    def path(self, relative):
        result = self.root / relative
        for part in (result, *result.parents):
            if part == self.root.parent:
                break
            if part.is_symlink():
                raise bc.ContractError('Каталог истории не должен содержать символические ссылки.', 409)
        return result

    def run_path(self, run_id, name='run.json'):
        if not self.valid_id(run_id):
            raise bc.ContractError('Некорректный ID запуска.')
        return self.path(self.runs_relative + '/' + run_id + '/' + name)

    def write(self, path, value):
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path(str(path.relative_to(self.root)) + '.tmp')
            with temporary.open('w', encoding='utf-8') as output:
                json.dump(value, output, ensure_ascii=False, allow_nan=False)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, path)
        except OSError:
            raise bc.ContractError('Не удалось сохранить историю запуска. Проверьте доступ и место на диске.', 507) from None

    def save(self, record):
        self.write(self.run_path(record['id']), record)

    def read(self, run_id, name='run.json'):
        path = self.run_path(run_id, name)
        try:
            return json.loads(path.read_text(encoding='utf-8'))
        except FileNotFoundError:
            raise bc.ContractError('Запуск или результат шага не найден.', 404) from None
        except (OSError, ValueError):
            raise bc.ContractError('Не удалось прочитать историю запуска.', 500) from None

    def get(self, run_id):
        with self.lock:
            record = deepcopy(self.current) if self.current and self.current['id'] == run_id else self.read(run_id)
            if record['status'] in ACTIVE:
                slot = gpu_compute.slot_status(self.root, run_id)
                record.update(queue_position=slot['queue_position'], queue_ahead=slot['queue_ahead'])
            return record

    def history(self):
        result = []
        with self.lock:
            for folder in self.path(self.runs_relative).iterdir():
                if not self.valid_id(folder.name):
                    continue
                try:
                    record = self.get(folder.name)
                    result.append({key: record.get(key) for key in ('id', 'name', 'status', 'created_at', 'finished_at', 'error', 'queue_position', 'queue_ahead', 'cancel_requested')})
                except bc.ContractError:
                    continue
        return {'runs': sorted(result, key=lambda item: item['created_at'], reverse=True)}

    def step(self, run_id, node_id):
        record = self.get(run_id)
        if not isinstance(node_id, str) or node_id not in record['order']:
            raise bc.ContractError('Шаг не найден.', 404)
        return self.read(run_id, 'steps/%04d.json' % record['order'].index(node_id))

    @staticmethod
    def event(record, message, node_id=None):
        record['events'].append({'time': now(), 'node_id': node_id, 'message': message})

    def prepare(self, body):
        source = body.get('diagram')
        groups = None
        if isinstance(source, dict) and (source.get('definitions') or source.get('version') == 4):
            source, registry = subgraphs.normalize(source)
            expanded, groups = subgraphs.expand(source, registry)
            diagram, order = validate(expanded)
        else:
            diagram, order = validate(source)
        return source, diagram, order, groups

    def debug_preview(self, body):
        import pipeline_debug
        _, diagram, order, groups = self.prepare(body)
        return pipeline_debug.plan(self, diagram, order, groups, body.get('debug'))[0]

    def start(self, body):
        resume = body.get('_training_resume')
        resume_request = resume['metadata'] if resume else None
        source, diagram, order, groups = self.prepare(body)
        run_id = body.get('run_id', str(uuid.uuid4()))
        with self.lock:
            if self.run_path(run_id).exists():
                existing = self.get(run_id)
                if existing['diagram'] != diagram or existing.get('project') != body.get('_project') or existing.get('debug_request') != body.get('debug') or existing.get('compute_request') != body.get('compute') or existing.get('training_resume') != resume_request:
                    raise bc.ContractError('Этот ID уже использован для другой схемы или команды.', 409)
                return existing
        debug_plan, reused = None, {}
        execution = order
        if 'debug' in body:
            import pipeline_debug
            debug_plan, reused = pipeline_debug.plan(self, diagram, order, groups, body['debug'])
            if body.get('plan_digest') != debug_plan['digest']: raise bc.ContractError('План выполнения изменился. Обновите предпросмотр и подтвердите запуск.', 409)
            if debug_plan['blocked']: raise bc.ContractError('Сначала выполните входные блоки: ' + ', '.join(dict.fromkeys(n['name'] for n in debug_plan['blocked'])))
            execution = [n['id'] for n in debug_plan['execute']]
            if not execution: raise bc.ContractError('Все шаги уже готовы. Выберите конкретный блок для повторного выполнения.')
        secrets = body.get('secrets', {})
        if not isinstance(secrets, dict) or set(secrets) - {'openrouter', 'kaggle', 'huggingface'}:
            raise bc.ContractError('Некорректные секреты запуска.')
        tokens = {}
        for key, env in [('openrouter', 'OPENROUTER_API_KEY'), ('kaggle', 'KAGGLE_API_TOKEN'), ('huggingface', 'HF_TOKEN')]:
            token = secrets.get(key, '')
            if not isinstance(token, str):
                raise bc.ContractError('Некорректный токен подключения.')
            token = token.strip() or (os.environ.get(env, '').strip() if ALLOW_ENVIRONMENT else '')
            if token and (len(token) > (512 if key == 'openrouter' else 2048) or not re.fullmatch(r'[!-~]+', token)):
                raise bc.ContractError('Некорректный формат токена подключения.')
            tokens[key] = token
        if any(n['id'] in execution and n['block']['kind'] == 'openrouter' for n in diagram['nodes']) and not tokens['openrouter']:
            raise bc.ContractError('Укажите ключ в подключении OpenRouter перед запуском.', 401)
        # Validate provider-specific literals without any network effects.
        for node in diagram['nodes']:
            if node['id'] not in execution: continue
            block = node['block']
            connected = {e['toPort'] for e in diagram['edges'] if e['to'] == node['id'] and e['kind'] == 'data'}
            if block['kind'] == 'kaggle' and 'source' not in connected:
                self.kaggle.dataset_handle(block['inputs']['source'])
            if block['kind'] == 'huggingface':
                if 'repo' not in connected:
                    self.huggingface.model_id(block['inputs']['repo'])
                self.huggingface.revision_id(block['settings']['revision'])
                for name in block['settings']['files']:
                    self.huggingface.filename(name)
        with self.lock:
            path = self.run_path(run_id)
            if path.exists():
                existing = self.get(run_id)
                if existing['diagram'] != diagram or existing.get('project') != body.get('_project') or existing.get('debug_request') != body.get('debug') or existing.get('compute_request') != body.get('compute') or existing.get('training_resume') != resume_request:
                    raise bc.ContractError('Этот ID уже использован для другой схемы.', 409)
                return existing
            record = {'id': run_id, 'name': diagram['name'], 'engine_version': 1, 'created_at': now(),
                      'status': 'waiting', 'diagram': diagram, 'order': order, 'events': [],
                      'contracts': [deepcopy(bc.CONTRACTS[k]) for k in sorted({n['block']['kind'] for n in diagram['nodes']})],
                      'nodes': {n['id']: {'name': n['name'], 'status': 'waiting' if n['id'] in order else 'skipped'} for n in diagram['nodes']}}
            # Keep the editor layout separately from the minimal execution graph.
            # Older API clients can still submit execution-only diagrams.
            if isinstance(source.get('types'), list):
                try:
                    record['editor_diagram'] = subgraphs.normalize(source)[0]
                except bc.ContractError:
                    pass
            if body.get('_project'):
                record['project'] = deepcopy(body['_project'])
                record['experiment_plan'] = deepcopy(body.get('_plan', {}))
                record['experiment'] = {'hypothesis': record['experiment_plan'].get('hypothesis', '')}
            record['compute'] = gpu_compute.resolve(self.root, uses_gpu(diagram,self.root), body.get('compute'), body.get('_gpu_executor'))
            record['compute_request'] = deepcopy(body.get('compute'))
            if record['compute']['mode'] == 'gpu': record['gpu_executor'] = {k: v for k, v in record['compute'].items() if k != 'mode'}
            if groups is not None:
                record.update(source_diagram=source, groups=groups)
            if debug_plan is not None:
                record.update(debug_request=deepcopy(body['debug']), debug_plan=debug_plan, execution_order=execution)
                for identity, step in reused.items():
                    copied = deepcopy(step); copied['reused_from'] = {'run_id': debug_plan['base_run_id'], 'node_id': identity}
                    self.write(self.run_path(run_id, 'steps/%04d.json' % order.index(identity)), copied)
                    record['nodes'][identity].update(status='ready', reused_from=debug_plan['base_run_id'])
                self.event(record, 'Пошаговый запуск. Повторно используются результаты: ' + str(len(reused)) + '. Выполняются шаги: ' + str(len(execution)) + '.')
            if resume:
                import training_resume
                record['training_resume'] = deepcopy(resume_request)
                self.write(self.run_path(run_id, 'steps/%04d.json' % order.index(resume_request['node_id'])), resume['step'])
                self.write(self.run_path(run_id, training_resume.checkpoint_path(record, resume_request['node_id'])), resume['envelope'])
                self.event(record, 'Продолжение обучения после эпохи ' + str(resume_request['epoch']) + ' из запуска ' + resume_request['run_id'] + '.', resume_request['node_id'])
            self.event(record, 'Схема проверена. Запуск поставлен в очередь.')
            gpu_compute.admit(self.root, run_id)
            try:
                self.save(record)  # Durable intent before any external action.
                self.current = record
                self.cancel_event = threading.Event()
                self.active_runs[run_id] = (record, self.cancel_event)
                self.thread = threading.Thread(target=self.run, args=(record, tokens, self.cancel_event), daemon=True)
                self.thread.start()
            except BaseException:
                self.active_runs.pop(run_id, None)
                gpu_compute.release(self.root, run_id)
                record.update(status='error', finished_at=now(), error='Не удалось поставить запуск в очередь. Повторите запуск.')
                tokens.clear()
                if path.exists():
                    self.save(record)
                raise
            return self.get(run_id)

    def cancel(self, run_id):
        with self.lock:
            record = self.get(run_id)
            active = self.active_runs.get(run_id)
            if active and active[0]['status'] in ACTIVE:
                record, cancelled = active
                cancelled.set()
                record['cancel_requested'] = True
                self.event(record, 'Запрошена остановка запуска.')
                self.save(record)
                record = deepcopy(record)
            return record

    def provenance(self, block, result):
        kind, details = block['kind'], result['details']
        if kind == 'kaggle':
            ref = result['outputs']['dataset']
            path = self.kaggle.archive_path(self.kaggle.dataset_handle(ref['id']))
            digest = hashlib.sha256()
            with path.open('rb') as source:
                for chunk in iter(lambda: source.read(1024 * 1024), b''):
                    digest.update(chunk)
            return {'artifact': ref, 'dataset_version': ref['id'].split('/versions/')[1] if '/versions/' in ref['id'] else None,
                    'archive_sha256': digest.hexdigest(), 'archive_bytes': path.stat().st_size,
                    'version_note': 'Для latest версия Kaggle неизвестна; сохранён хеш локального архива.'}
        if kind == 'huggingface':
            ref = result['outputs']['model']
            manifest = self.huggingface.read_manifest(ref['id'], ref['revision'])
            return {'artifact': ref, 'files': [f for f in manifest['files'] if f['name'] in block['settings']['files']]}
        if kind == 'openrouter':
            return {'requested_model': block['settings']['model'], 'response_model': details.get('model'),
                    'immutable_revision': None, 'version_note': 'API не сообщает неизменяемую версию весов модели.'}
        return details

    def run(self, record, tokens, cancel_event):
        acquired = False
        try:
            acquired = gpu_compute.enter_slot(self.root, record['id'], cancel_event)
            if not acquired:
                with self.lock:
                    record.update(status='cancelled', finished_at=now())
                    for node in record['nodes'].values():
                        if node['status'] in ACTIVE:
                            node['status'] = 'cancelled'
                    self.event(record, 'Запуск отменён в очереди. Вычисления не начинались.')
                    self.save(record)
                return
            def progress(value):
                node = next((key for key in record['order'] if record['nodes'][key]['status'] == 'running'), None)
                if node and value.get('loss_curve'):
                    self.write(self.run_path(record['id'], 'progress.json'), {'node_id': node, 'name': record['nodes'][node]['name'], 'values': value['loss_curve'], 'epoch': value.get('epoch'), 'epochs': value.get('epochs')})
            with gpu_compute.execution(record.get('gpu_executor'), cancel_event, record['id'], progress):
                self.run_steps(record, tokens, cancel_event)
        finally:
            with self.lock:
                self.active_runs.pop(record['id'], None)
            gpu_compute.release(self.root, record['id'])
            tokens.clear()

    def run_steps(self, record, tokens, cancel_event):
        outputs, node_id, step_data = {}, None, None
        consumers = Counter(edge['from'] for edge in record['diagram']['edges'] if edge['kind'] == 'data')
        def clean(value):
            if isinstance(value, str):
                for token in tokens.values():
                    if token:
                        value = value.replace(token, '[секрет скрыт]')
                return value
            if isinstance(value, dict):
                return {key: clean(item) for key, item in value.items()}
            if isinstance(value, list):
                return [clean(item) for item in value]
            return value
        def save_step():
            self.write(self.run_path(record['id'], 'steps/%04d.json' % record['order'].index(node_id)), clean(step_data) if any(tokens.values()) else step_data)
        try:
            with self.lock:
                record.update(status='running', started_at=now())
                self.save(record)
            for node_id in record['order']:
                if cancel_event.is_set():
                    break
                if record.get('debug_plan'):
                    if record['nodes'][node_id].get('reused_from'):
                        outputs[node_id] = self.step(record['id'], node_id)['outputs']
                        continue
                    if node_id not in record['execution_order']: continue
                node = next(n for n in record['diagram']['nodes'] if n['id'] == node_id)
                block = deepcopy(node['block'])
                step_data = {'node_id': node_id, 'block': block, 'started_at': now()}
                with self.lock:
                    record['nodes'][node_id].update(status='running', started_at=step_data['started_at'])
                    self.event(record, 'Выполнение блока: ' + node['name'], node_id)
                    self.save(record)
                for edge in record['diagram']['edges']:
                    if edge['kind'] == 'data' and edge['to'] == node_id:
                        source = edge['from']
                        block['inputs'][edge['toPort']] = outputs[source][edge['fromPort']]
                        consumers[source] -= 1
                        if not consumers[source]: del outputs[source]
                block = bc.normalize_block(block, required=True)
                step_data['block'] = block
                save_step()
                kind = block['kind']
                if kind == 'huggingface' and not block['settings']['commit']:
                    info = self.huggingface.model_info(self.huggingface.model_id(block['inputs']['repo']), block['settings']['revision'], tokens['huggingface'])
                    block['settings']['commit'] = info['commit']
                    save_step()
                secrets = {'api_key': tokens['openrouter']} if kind == 'openrouter' else {'token': tokens.get(kind, '')}
                if kind == 'gpu_train':
                    import training_resume
                    checkpoint = None
                    relative = training_resume.checkpoint_path(record, node_id)
                    if record.get('training_resume', {}).get('node_id') == node_id:
                        checkpoint = self.read(record['id'], relative)['checkpoint']
                    def save_checkpoint(value):
                        self.write(self.run_path(record['id'], relative), {'checkpoint':value,'saved_at':now(),'epochs':block['settings']['epochs']})
                    with gpu_compute.training(checkpoint, save_checkpoint):
                        result = bc.execute({'block':block,'secrets':secrets}, self.completion, self.kaggle, self.huggingface)
                else:
                    result = bc.execute({'block': block, 'secrets': secrets}, self.completion, self.kaggle, self.huggingface)
                while result['status'] == 'downloading':
                    if cancel_event.wait(1):
                        break
                    result = bc.execute({'block': block}, self.completion, self.kaggle, self.huggingface, poll=True)
                if result['status'] != 'ready':
                    if cancel_event.is_set():
                        step_data.update(status='cancelled', finished_at=now(), details=result['details'])
                        save_step()
                        break
                    raise bc.ContractError(result['details'].get('error', 'Операция не вернула результат.'))
                if consumers[node_id]: outputs[node_id] = result['outputs']
                step_data.update(status='ready', outputs=result['outputs'], details=result['details'], finished_at=now())
                save_step()  # Retain the result even if provenance inspection fails.
                step_data['versions'] = self.provenance(block, result)
                save_step()
                with self.lock:
                    record['nodes'][node_id].update(status='ready', finished_at=step_data['finished_at'])
                    self.event(record, 'Блок завершён: ' + node['name'], node_id)
                    self.save(record)
            with self.lock:
                record['status'] = 'cancelled' if cancel_event.is_set() else 'paused' if record.get('debug_plan', {}).get('remaining') else 'ready'
                self.event(record, 'Запуск остановлен.' if cancel_event.is_set() else 'Шаг завершён. Можно выполнить следующий блок или продолжить пайплайн.' if record['status'] == 'paused' else 'Пайплайн завершён.')
        except Exception as error:
            # Known provider exceptions contain safe user-facing messages, never raw HTTP bodies.
            known = (bc.ContractError, self.kaggle.KaggleError, self.huggingface.HubError)
            safe = isinstance(error, known) or type(error).__name__ == 'ApiError'
            message = clean(str(error)) if safe else 'Ошибка выполнения или сохранения результата. Автоматический повтор не выполнялся.'
            with self.lock:
                record.update(status='cancelled' if cancel_event.is_set() else 'error', error=message)
                if node_id is not None:
                    record['nodes'][node_id].update(status=record['status'], error=message, finished_at=now())
                self.event(record, message, node_id)
            if step_data:
                step_data.update(status=record['status'], error=message, finished_at=now())
                try:
                    save_step()
                except (bc.ContractError, OSError):
                    pass
        finally:
            with self.lock:
                record['finished_at'] = now()
                for step in record['nodes'].values():
                    if step['status'] in ACTIVE:
                        step['status'] = 'cancelled' if record['status'] == 'cancelled' else 'pending' if record['status'] == 'paused' else 'skipped'
                try:
                    self.save(record)
                except (bc.ContractError, OSError):
                    record.update(status='error', error='Не удалось сохранить историю на диск. Не повторяйте платный запрос, пока не проверите результат у провайдера.')
            tokens.clear()


def request(server, body, action, completion, kaggle, huggingface):
    body = dict(body)
    body.pop('_project', None)
    body.pop('_plan', None)
    body.pop('_gpu_executor', None)
    body.pop('_training_resume', None)
    project_id = body.get('project_id')
    if project_id is not None:
        project = project_store.ProjectStore().get(project_id)
        if action in ('start', 'validate', 'debug-preview') and project['project'].get('contract_lock'):
            import local_workspace as community
            community.Community.check_pins({'builtins': project['project']['contract_lock']})
        if action in ('start', 'validate', 'debug-preview'):
            if body.get('revision') != project['project']['revision']:
                raise bc.ContractError('Редакция проекта изменилась. Сохраните схему и повторите запуск.', 409)
            body['diagram'] = project['diagram']
            body['_project'] = {key: project['project'][key] for key in ('id', 'name', 'revision')}
            body['_plan'] = project['project'].get('research', {})
    if action == 'validate':
        source = body.get('diagram')
        if isinstance(source, dict) and (source.get('definitions') or source.get('version') == 4):
            graph, registry = subgraphs.normalize(source)
            source, _ = subgraphs.expand(graph, registry)
        diagram, order = validate(source)
        return {'diagram': diagram, 'order': order}
    with CREATION_LOCK:
        if not hasattr(server, 'project_runners'):
            server.project_runners = {}
        if project_id is None:
            if not hasattr(server, 'pipeline_runner'):
                server.pipeline_runner = PipelineRunner(completion, kaggle, huggingface)
            runner = server.pipeline_runner
        else:
            if project_id not in server.project_runners:
                store = project_store.ProjectStore()
                server.project_runners[project_id] = PipelineRunner(completion, kaggle, huggingface, store.root,
                                                                   store.folder(project_id) + '/runs')
            runner = server.project_runners[project_id]
        if action == 'start':
            return runner.start(body)
        if action == 'resume-training':
            import training_resume
            return training_resume.resume(runner, body)
    if action == 'runs':
        return runner.history()
    if action == 'debug-preview': return runner.debug_preview(body)
    if action in ('overview', 'assets', 'asset'):
        import project_insights
        return project_insights.request(runner, body, action, kaggle, huggingface)
    if action in ('experiments', 'compare', 'experiment'):
        import experiments
        return experiments.request(runner, body, action)
    if action == 'run':
        return runner.get(body.get('run_id'))
    if action == 'monitor':
        record = runner.get(body.get('run_id'))
        curves = []
        for node in record['order']:
            if record['nodes'][node]['status'] == 'ready':
                try:
                    step = runner.step(record['id'], node)
                    if step.get('details', {}).get('loss_curve'): curves.append({'node_id': node, 'name': record['nodes'][node]['name'], 'values': step['details']['loss_curve']})
                except bc.ContractError: pass
        live = gpu_compute.broker().monitor(runner.root, record['id']) if gpu_compute._BROKER else []
        if not any(job.get('progress', {}).get('loss_curve') for job in live):
            try:
                partial = runner.read(record['id'], 'progress.json')
                if not any(c['node_id'] == partial['node_id'] for c in curves): curves.append(partial)
            except bc.ContractError: pass
        import training_resume
        checkpoints = training_resume.summary(runner,record)
        for point in checkpoints:
            if record['nodes'][point['node_id']]['status'] == 'running' and any(j.get('progress', {}).get('loss_curve') for j in live): continue
            existing = next((c for c in curves if c['node_id'] == point['node_id']), None)
            if not existing or len(existing['values']) < point['epoch']:
                saved = runner.read(record['id'],training_resume.checkpoint_path(record,point['node_id']))['checkpoint']
                if existing: curves.remove(existing)
                curves.append({'node_id':point['node_id'],'name':point['name'],'values':saved['loss_curve']})
        return {'checkpoints':checkpoints, 'resume':training_resume.candidate(runner,record), 'run': record, 'slot': gpu_compute.slot_status(runner.root, record['id']), 'gpu': live, 'curves': curves, 'server_time': now()}
    if action == 'step':
        return runner.step(body.get('run_id'), body.get('node_id'))
    if action == 'cancel':
        return runner.cancel(body.get('run_id'))
    raise bc.ContractError('Маршрут не найден.', 404)

