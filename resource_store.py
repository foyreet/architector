"""Account-scoped storage inventory and reference-aware cleanup."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import time

import block_contracts as bc
import ml_operations as ml
import pipeline_runner as pr
import project_store as ps
import experiment_queue
import gpu_compute


def files(folder):
    if not folder.exists(): return
    if folder.is_symlink(): raise bc.ContractError('В хранилище обнаружена символическая ссылка.', 409)
    for base, directories, names in os.walk(folder, followlinks=False):
        directories[:] = [n for n in directories if not (Path(base)/n).is_symlink()]
        for name in names:
            path = Path(base)/name
            if not path.is_symlink(): yield path


def refs(value):
    if isinstance(value, dict):
        if value.get('type') == 'artifact' and value.get('provider') == 'local' and isinstance(value.get('id'), str) and re.fullmatch('[a-f0-9]{64}', value['id']): yield value['id']
        for child in value.values(): yield from refs(child)
    elif isinstance(value, list):
        for child in value: yield from refs(child)


def inventory(context):
    store = ps.ProjectStore(context.root); root = store.root; artifact_dir = ml.artifact_dir(root)
    pins_path = 'workspace/artifact-pins.json'
    pins = store.read(pins_path) if store.path(pins_path).exists() else {}
    if not isinstance(pins, dict) or any(not re.fullmatch('[a-f0-9]{64}', key) for key in pins): raise bc.ContractError('Повреждён список закреплений. Очистка остановлена.', 409)
    reached = set(pins); sources = {}; count = 0
    for category in ('projects', 'workspace/runs', 'workspace/experiment-queue', 'workspace/predictions', 'workspace/model-registry'):
        folder = store.path(category)
        for path in files(folder):
            if path.suffix != '.json': continue
            count += 1
            if count > 10000: raise bc.ContractError('Хранилище слишком большое для безопасной автоматической проверки ссылок.', 413)
            try: value = json.loads(path.read_text(encoding='utf-8'))
            except (OSError, ValueError): raise bc.ContractError('Не удалось проверить ссылки в истории. Очистка остановлена.', 409) from None
            for identity in refs(value): reached.add(identity); sources.setdefault(identity, set()).add(category)
    pending = list(reached)
    while pending:
        identity = pending.pop(); path = artifact_dir/(identity+'.json')
        if path.is_symlink(): raise bc.ContractError('Недопустимая ссылка артефакта.', 409)
        if not path.exists(): continue
        try:
            content = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError): raise bc.ContractError('Повреждён артефакт, автоматическая очистка остановлена.', 409) from None
        for ref in refs(content):
            sources.setdefault(ref, set()).add('Зависимость модели/таблицы')
            if ref not in reached: reached.add(ref); pending.append(ref)
    assets = []
    for path in files(artifact_dir):
        if not re.fullmatch(r'[a-f0-9]{64}\.json', path.name): continue
        stat = path.stat(); identity = path.stem
        reference = None
        if identity in pins:
            reference = bc.artifact(json.loads(path.read_text(encoding='utf-8'))['kind'], 'local', identity)
        assets.append({'id': identity, 'bytes': stat.st_size, 'pinned': identity in pins, 'label': pins.get(identity, ''), 'artifact': reference,
                       'referenced': identity in reached, 'sources': sorted(sources.get(identity, [])),
                       'removable': identity not in reached and time.time() - stat.st_mtime >= 60})
    sizes = {category: sum(p.stat().st_size for p in files(store.path(category))) for category in ('projects', 'workspace/runs', 'workspace/ml-artifacts', 'workspace/datasets', 'workspace/models', 'workspace/predictions')}
    disk = shutil.disk_usage(root)
    memory = {'total': None, 'available': None, 'service_limit': None, 'service_used': None}
    if Path('/proc/meminfo').exists():
        values = {line.split(':')[0]: int(line.split()[1]) * 1024 for line in Path('/proc/meminfo').read_text().splitlines() if len(line.split()) >= 2}
        memory.update(total=values.get('MemTotal'), available=values.get('MemAvailable'))
        try:
            group = next(line.split('::', 1)[1] for line in Path('/proc/self/cgroup').read_text().splitlines() if line.startswith('0::'))
            folder = Path('/sys/fs/cgroup') / group.lstrip('/')
            for name, key in [('memory.max', 'service_limit'), ('memory.current', 'service_used')]:
                raw = (folder/name).read_text().strip()
                memory[key] = int(raw) if raw.isdecimal() else None
        except (OSError, StopIteration): pass
    elif os.name == 'nt':
        import psutil
        info = psutil.virtual_memory()
        memory.update(total=info.total, available=info.available)
    else:
        try: memory['total'] = os.sysconf('SC_PHYS_PAGES') * os.sysconf('SC_PAGE_SIZE')
        except (ValueError, OSError): pass
    if os.name == 'nt':
        import psutil
        info = psutil.Process().memory_info()
        memory['process_peak'] = getattr(info, 'peak_wset', info.rss)
    else:
        import resource
        memory['process_peak'] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1 if sys.platform == 'darwin' else 1024)
    return {'memory': memory, 'disk': {'total': disk.total, 'free': disk.free}, 'sizes': sizes, 'artifacts': assets,
            'removable_bytes': sum(a['bytes'] for a in assets if a['removable']), 'load': list(os.getloadavg()) if hasattr(os, 'getloadavg') else [], 'cpu_count': os.cpu_count(),
            'note': 'RAM и диск относятся к серверу; размеры разделов и артефакты — к вашему аккаунту. Очистка затрагивает только JSON-артефакты без ссылок старше минуты. Датасеты и веса автоматически не удаляются.'}


def guard(server):
    if gpu_compute._BROKER is not None and gpu_compute._BROKER.jobs: raise bc.ContractError('GPU-задания ещё выполняются или ожидают запуска.', 409)
    if experiment_queue.active(server): raise bc.ContractError('Дождитесь завершения выполняющегося пайплайна.', 409)
    if getattr(server, 'experiment_queue', None) and server.experiment_queue.jobs: raise bc.ContractError('Дождитесь завершения очереди или отмените оставшиеся запуски.', 409)


def request(server, context, body, action):
    store = ps.ProjectStore(context.root)
    with pr.CREATION_LOCK:
        if action == 'status': return inventory(context)
        if action == 'asset':
            ref = body.get('artifact')
            if not isinstance(ref, dict) or ref.get('kind') not in ml.ARTIFACT_TYPES: raise bc.ContractError('Выберите локальный артефакт.')
            return ml.load(store.root, ref, ref['kind'])
        if action == 'pin':
            ref = body.get('artifact'); ml.load(store.root, ref, ref.get('kind') if isinstance(ref, dict) else None)
            value = store.read('workspace/artifact-pins.json') if store.path('workspace/artifact-pins.json').exists() else {}
            if body.get('pinned') is True: value[ref['id']] = str(body.get('label', 'Важный артефакт'))[:160]
            else: value.pop(ref['id'], None)
            store.write('workspace/artifact-pins.json', value); return {'pinned': ref['id'] in value}
        if action == 'unpin':
            identity = body.get('id'); value = store.read('workspace/artifact-pins.json') if store.path('workspace/artifact-pins.json').exists() else {}
            value.pop(identity, None); store.write('workspace/artifact-pins.json', value); return {'pinned': False}
        guard(server)
        if action == 'delete-prediction':
            identity = body.get('id')
            if not pr.PipelineRunner.valid_id(identity) or body.get('confirm') != identity: raise bc.ContractError('Подтвердите ID результата.')
            relative = 'workspace/predictions/' + identity + '.json'; store.read(relative); store.path(relative).unlink()
            return {'deleted': identity}
        if action in ('cleanup-preview', 'cleanup'):
            values = [a for a in inventory(context)['artifacts'] if a['removable']]
            digest = hashlib.sha256(ml.encode(values)).hexdigest()
            if action == 'cleanup-preview': return {'digest': digest, 'count': len(values), 'bytes': sum(a['bytes'] for a in values)}
            if body.get('digest') != digest: raise bc.ContractError('Список изменился. Проверьте очистку заново.', 409)
            if not ml.WORKER_LOCK.begin_cleanup(): raise bc.ContractError('Вычисления ещё выполняются.', 409)
            try:
                for a in values: (ml.artifact_dir(store.root)/(a['id']+'.json')).unlink()
            finally: ml.WORKER_LOCK.end_cleanup()
            return {'removed': len(values)}
        if action == 'delete-run':
            project = store.get(body.get('project_id')); identity = body.get('run_id')
            if not pr.PipelineRunner.valid_id(identity): raise bc.ContractError('Некорректный запуск.')
            prefix = store.folder(project['project']['id']) + '/runs/' + identity
            record = store.read(prefix + '/run.json')
            if record['status'] in pr.ACTIVE: raise bc.ContractError('Запуск ещё выполняется.', 409)
            if project['project'].get('research', {}).get('baseline') == identity: raise bc.ContractError('Сначала измените базовый запуск в плане эксперимента.')
            if body.get('confirm') != identity: raise bc.ContractError('Подтвердите ID удаляемого запуска.')
            shutil.rmtree(store.path(prefix))
            runner = getattr(context.server, 'project_runners', {}).get(project['project']['id'])
            if runner and runner.current and runner.current['id'] == identity: runner.current = None
            return {'deleted': identity}
    raise bc.ContractError('Маршрут не найден.', 404)

