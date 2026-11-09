"""Project folders with immutable revisions and an atomic current-revision pointer."""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import re
import threading
import uuid

import block_contracts as bc
import subgraphs
from app_config import data_root

ROOT = data_root()
LOCK = threading.RLock()
MAX_PACKAGE = 32 * 1024 * 1024


def now():
    return datetime.now(timezone.utc).isoformat()


class ProjectStore:
    def __init__(self, root=None):
        self.root = Path(root or ROOT)

    def path(self, relative):
        path = self.root / relative
        if not path.is_relative_to(self.root):
            raise bc.ContractError('Недопустимый путь проекта.')
        for part in (path, *path.parents):
            if part == self.root.parent:
                break
            if part.is_symlink():
                raise bc.ContractError('Папка проекта не должна содержать символические ссылки.', 409)
        return path

    def folder(self, project_id):
        if not isinstance(project_id, str) or not re.fullmatch(r'[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}', project_id):
            raise bc.ContractError('Некорректный ID проекта.')
        return 'projects/' + project_id

    def read(self, relative):
        path = self.path(relative)
        try:
            if path.stat().st_size > MAX_PACKAGE:
                raise bc.ContractError('Файл проекта превышает лимит 32 МиБ.', 413)
            return json.loads(path.read_text(encoding='utf-8'))
        except FileNotFoundError:
            raise bc.ContractError('Проект или его редакция не найдены.', 404) from None
        except (OSError, ValueError, UnicodeError):
            raise bc.ContractError('Не удалось прочитать файл проекта.', 500) from None

    def write(self, relative, value, plain=False):
        path = self.path(relative)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.path(relative + '.tmp')
            with temp.open('w', encoding='utf-8') as file:
                file.write(value if plain else json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
                file.flush(); os.fsync(file.fileno())
            os.replace(temp, path)
        except OSError:
            raise bc.ContractError('Не удалось сохранить проект. Проверьте свободное место и права на папку.', 507) from None

    @contextmanager
    def locked(self):
        with LOCK:
            try:
                self.path('projects').mkdir(parents=True, exist_ok=True)
                with self.path('projects/.store.lock').open('a') as lock:
                    fcntl.flock(lock, fcntl.LOCK_EX)
                    try:
                        yield
                    finally:
                        fcntl.flock(lock, fcntl.LOCK_UN)
            except OSError:
                raise bc.ContractError('Хранилище проектов недоступно.', 507) from None

    def get(self, project_id):
        folder = self.folder(project_id)
        meta = self.read(folder + '/project.json')
        if meta.get('format') != 'architect.project' or meta.get('version') != 1 or meta.get('id') != project_id or type(meta.get('revision')) is not int:
            raise bc.ContractError('Повреждён манифест проекта.', 422)
        snapshot = meta.get('snapshot')
        if not isinstance(snapshot, str) or not re.fullmatch(r'[a-f0-9]{32}', snapshot):
            raise bc.ContractError('Некорректная ссылка на редакцию проекта.', 422)
        prefix = folder + '/revisions/' + snapshot
        diagram = self.read(prefix + '/graph.json')
        kinds = diagram.pop('definition_files', [])
        if not isinstance(kinds, list) or len(kinds) > 100 or any(not isinstance(k, str) or not re.fullmatch(r'subgraph_[a-f0-9]{64}', k) for k in kinds):
            raise bc.ContractError('Некорректный каталог блоков проекта.', 422)
        diagram['definitions'] = [self.read(folder + '/blocks/' + kind + '.json') for kind in kinds]
        diagram, registry = subgraphs.normalize(diagram)
        try:
            description = self.path(prefix + '/README.md').read_text(encoding='utf-8')
        except (OSError, UnicodeError):
            raise bc.ContractError('Не удалось прочитать описание проекта.', 422) from None
        return {'project': meta, 'description': description, 'diagram': diagram, 'contracts': list(registry.contracts.values())}

    def listing(self):
        folder = self.path('projects')
        if not folder.exists():
            return {'projects': []}
        projects = []
        for item in folder.iterdir():
            try:
                prefix = self.folder(item.name)
                meta = self.read(prefix + '/project.json')
                projects.append({key: meta.get(key) for key in ('id', 'name', 'revision', 'updated_at')})
            except bc.ContractError:
                continue
        return {'projects': sorted(projects, key=lambda p: str(p.get('updated_at', '')), reverse=True)}

    def save(self, body, create=False, history=None, contract_lock=None, operation_id=None):
        graph, registry = subgraphs.normalize(body.get('diagram'))
        name = subgraphs.text(body.get('name', graph['name']), 160, False)
        description = subgraphs.text(body.get('description', ''), 32000)
        if len(json.dumps(graph, ensure_ascii=False).encode()) > 4 * 1024 * 1024:
            raise bc.ContractError('Описание схемы превышает лимит 4 МиБ.', 413)
        project_id = str(uuid.uuid4()) if create else body.get('project_id')
        folder = self.folder(project_id)
        with self.locked():
            if create:
                meta = {'format': 'architect.project', 'version': 1, 'id': project_id, 'created_at': now(), 'revision': 0}
            else:
                meta = self.get(project_id)['project']
                if type(body.get('revision')) is not int or body['revision'] != meta['revision']:
                    raise bc.ContractError('Проект изменён в другой вкладке. Откройте его заново или сохраните черновик как новый проект.', 409)
            if 'research' in body:
                from project_insights import plan
                research = plan(body['research'])
                if research['baseline'] and not create:
                    baseline = self.read(folder + '/runs/' + research['baseline'] + '/run.json') if re.fullmatch(r'[a-f0-9-]{36}', research['baseline']) else None
                    if not baseline or baseline.get('status') != 'ready': raise bc.ContractError('Базовым может быть успешный запуск этого проекта.')
                if create: research['baseline'] = ''
                meta = dict(meta, research=research)
            if contract_lock is not None:
                meta['contract_lock'] = deepcopy(contract_lock)
            if operation_id:
                meta['last_operation'] = operation_id
                meta.setdefault('applied_operations', {})[operation_id] = meta['revision'] + 1
            snapshot = uuid.uuid4().hex
            prefix = folder + '/revisions/' + snapshot
            disk_graph = deepcopy(graph)
            definitions = disk_graph.pop('definitions')
            disk_graph['definition_files'] = [d['kind'] for d in definitions]
            self.write(prefix + '/graph.json', disk_graph)
            self.write(prefix + '/README.md', description, plain=True)
            for definition in definitions:
                relative = folder + '/blocks/' + definition['kind'] + '.json'
                if self.path(relative).exists():
                    if self.read(relative) != definition:
                        raise bc.ContractError('Сохранённое определение блока изменено. Восстановите его из пакета проекта.', 409)
                else:
                    self.write(relative, definition)
            meta = dict(meta, name=name, revision=meta['revision'] + 1, updated_at=now(), snapshot=snapshot)
            if create:
                self.write(folder + '/.gitignore', 'runs/\n*.tmp\n', plain=True)
            for entry in history or []:
                record = deepcopy(entry['record'])
                record.update(id=str(uuid.uuid4()), imported=True, project={'id': project_id, 'name': name, 'revision': None})
                run_prefix = folder + '/runs/' + record['id']
                for i, key in enumerate(record['order']):
                    if key in entry['steps']:
                        self.write(run_prefix + '/steps/%04d.json' % i, entry['steps'][key])
                self.write(run_prefix + '/run.json', record)
            # Publish only after every file of the new revision is durable.
            self.write(folder + '/project.json', meta)
        return {'project': meta, 'description': description, 'diagram': graph, 'contracts': list(registry.contracts.values())}

    def export(self, project_id, include_history=False):
        current = self.get(project_id)
        package = {'format': 'architect.project-package', 'version': 1,
                   'name': current['project']['name'], 'description': current['description'], 'diagram': current['diagram']}
        if current['project'].get('research'): package['research'] = current['project']['research']
        if include_history:
            package['history'] = []
            folder = self.path(self.folder(project_id) + '/runs')
            if folder.exists():
                total = len(json.dumps(package).encode())
                for path in sorted(folder.iterdir()):
                    if not re.fullmatch(r'[a-f0-9-]{36}', path.name):
                        continue
                    prefix = self.folder(project_id) + '/runs/' + path.name
                    record = self.read(prefix + '/run.json')
                    if record.get('status') in ('waiting', 'running'):
                        raise bc.ContractError('Для экспорта истории дождитесь завершения запуска.', 409)
                    steps = {}
                    for i, node_id in enumerate(record.get('order', [])):
                        relative = prefix + '/steps/%04d.json' % i
                        if self.path(relative).exists():
                            steps[node_id] = self.read(relative)
                    entry = {'record': record, 'steps': steps}
                    total += len(json.dumps(entry, ensure_ascii=False).encode())
                    if total > MAX_PACKAGE:
                        raise bc.ContractError('История больше 32 МиБ. Экспортируйте описание без истории или скопируйте папку проекта.', 413)
                    package['history'].append(entry)
                    if len(package['history']) > 100:
                        raise bc.ContractError('В пакете допускается до 100 запусков. Для полной истории скопируйте папку проекта.', 413)
        return package

    def import_package(self, body):
        package = body.get('package')
        if not isinstance(package, dict) or package.get('format') != 'architect.project-package' or package.get('version') != 1:
            raise bc.ContractError('Неизвестный формат пакета проекта.')
        history = package.get('history', [])
        if not isinstance(history, list) or len(history) > 100:
            raise bc.ContractError('Пакет может содержать до 100 запусков.')
        # Imported history is an inert archive; never a queue of work to resume.
        archived = []
        for entry in history:
            if not isinstance(entry, dict) or not isinstance(entry.get('record'), dict) or not isinstance(entry.get('steps'), dict):
                raise bc.ContractError('Некорректная история в пакете.')
            record = entry['record']
            order, nodes = record.get('order'), record.get('nodes')
            if not isinstance(order, list) or len(order) > 500 or not isinstance(nodes, dict) or len(nodes) > 500:
                raise bc.ContractError('Некорректные шаги истории.')
            if any(not isinstance(key, str) or not isinstance(nodes.get(key), dict) for key in order) or len(set(order)) != len(order):
                raise bc.ContractError('Некорректные ID шагов истории.')
            if record.get('status') not in ('ready', 'error', 'cancelled', 'paused'):
                raise bc.ContractError('Можно импортировать только завершённую историю.')
            subgraphs.text(record.get('created_at'), 100, False)
            subgraphs.text(record.get('name', ''), 160)
            if any(not isinstance(step, dict) or step.get('status') not in ('waiting', 'running', 'ready', 'error', 'cancelled', 'skipped', 'pending') for step in nodes.values()):
                raise bc.ContractError('Некорректные состояния истории.')
            if not isinstance(record.get('events'), list) or any(not isinstance(e, dict) or not isinstance(e.get('message'), str) or not isinstance(e.get('time'), str) for e in record['events']):
                raise bc.ContractError('Некорректный журнал истории.')
            if not isinstance(record.get('diagram'), dict) or not isinstance(record['diagram'].get('nodes'), list) or not isinstance(record['diagram'].get('edges'), list):
                raise bc.ContractError('Нет снимка схемы в истории.')
            if any(key not in order or not isinstance(value, dict) for key, value in entry['steps'].items()):
                raise bc.ContractError('Некорректные результаты истории.')
            import pipeline_runner
            diagram, expected_order = pipeline_runner.validate(record['diagram'])
            if order != expected_order or set(nodes) != {n['id'] for n in diagram['nodes']}:
                raise bc.ContractError('Шаги истории не соответствуют снимку схемы.')
            record = {key: deepcopy(record[key]) for key in ('name', 'status', 'created_at', 'order', 'nodes', 'events')}
            record['diagram'] = diagram
            if 'experiment_plan' in entry['record']:
                from project_insights import plan
                record['experiment_plan'] = plan(entry['record']['experiment_plan'])
            if 'experiment' in entry['record']:
                import experiments
                record['experiment'] = experiments.notes(entry['record']['experiment'])
            for key in ('contracts', 'engine_version', 'origin_project', 'origin_run_id'):
                if key in entry['record']:
                    record[key] = deepcopy(entry['record'][key])
            record.setdefault('origin_project', {key: entry['record'].get('project', {}).get(key) for key in ('id', 'name', 'revision')}
                              if isinstance(entry['record'].get('project'), dict) else None)
            record.setdefault('origin_run_id', entry['record'].get('id'))
            for key in ('error', 'started_at', 'finished_at'):
                if key in entry['record']:
                    record[key] = subgraphs.text(entry['record'][key], 4000)
            if entry['record'].get('source_diagram'):
                source, registry = subgraphs.normalize(entry['record']['source_diagram'])
                expanded, groups = subgraphs.expand(source, registry)
                checked, _ = pipeline_runner.validate(expanded)
                if checked != diagram:
                    raise bc.ContractError('Снимок подсхемы не соответствует истории.')
                record.update(source_diagram=source, groups=groups)
            archived.append({'record': record, 'steps': deepcopy(entry['steps'])})
        return self.save(package, create=True, history=archived)


def request(body, action, root=None):
    store = ProjectStore(root)
    if action == 'list': return store.listing()
    if action == 'get': return store.get(body.get('project_id'))
    if action in ('create', 'save'): return store.save(body, create=action == 'create')
    if action == 'export': return store.export(body.get('project_id'), body.get('include_history') is True)
    if action == 'import': return store.import_package(body)
    raise bc.ContractError('Маршрут не найден.', 404)

