"""Read-only, account/project-scoped diagnostics for the chat's draft tools."""
import re

import block_contracts as bc
from pipeline_runner import PipelineRunner


def text(value, limit=2000):
    # Provider credentials are already removed when runs are saved. Also mask
    # common credential assignments in user-produced Python logs before sharing.
    value = str(value or '')
    value = re.sub(r'(?i)(bearer\s+)\S+', r'\1[скрыто]', value)
    value = re.sub(r'''(?ix)((?:api[_-]?key|access[_-]?token|token|password|secret)\s*["']?\s*[:=]\s*)["']?[^\s,"'}]+''',
                   r'\1[скрыто]', value)
    return value[:limit] + ('… [обрезано]' if len(value) > limit else '')


class Diagnostics:
    def __init__(self, store, project_id=None):
        self.store = store
        self.project_id = project_id
        self.relative = store.folder(project_id) + '/runs' if project_id else 'workspace/runs'

    def authorize(self):
        if self.project_id:
            self.store.get(self.project_id)

    def read(self, run_id):
        self.authorize()
        if not PipelineRunner.valid_id(run_id):
            raise bc.ContractError('Некорректный ID запуска.')
        return self.store.read(self.relative + '/' + run_id + '/run.json')

    @staticmethod
    def summary(record):
        return {key: text(record.get(key)) for key in
                ('id', 'name', 'status', 'created_at', 'finished_at', 'error')}

    def runs(self):
        self.authorize()
        folder = self.store.path(self.relative)
        records = []
        if folder.exists():
            for entry in folder.iterdir():
                if not PipelineRunner.valid_id(entry.name):
                    continue
                try:
                    records.append(self.summary(self.read(entry.name)))
                except bc.ContractError:
                    continue
        records.sort(key=lambda record: record['created_at'], reverse=True)
        return {'runs': records[:10], 'truncated': len(records) > 10,
                'note': 'Последние сохранённые запуски текущего проекта.' if self.project_id
                        else 'Последние сохранённые запуски без проекта в текущем аккаунте.'}

    def logs(self, run_id, node_id=None):
        record = self.read(run_id)
        result = self.summary(record)
        events = record.get('events', [])
        if node_id is not None:
            if node_id not in record.get('order', []):
                raise bc.ContractError('Шаг не найден в этом запуске.', 404)
            events = [event for event in events if event.get('node_id') == node_id]
        result['events'] = [{key: text(event.get(key)) for key in ('time', 'node_id', 'message')}
                            for event in events[-30:]]
        result['events_truncated'] = len(events) > 30
        nodes = record.get('nodes', {})
        selected = [(node_id, nodes.get(node_id, {}))] if node_id is not None else list(nodes.items())[:50]
        result['nodes'] = [{'id': text(identity), **{key: text(node.get(key), 1000)
                            for key in ('name', 'status', 'error')}} for identity, node in selected]
        result['nodes_truncated'] = node_id is None and len(nodes) > 50
        if node_id is not None:
            relative = self.relative + '/' + run_id + '/steps/%04d.json' % record['order'].index(node_id)
            if self.store.path(relative).exists():
                step = self.store.read(relative)
                result['step'] = {key: text(step.get(key), 12000 if key == 'error' else 2000)
                                  for key in ('node_id', 'status', 'started_at', 'finished_at', 'error')}
                result['step']['logs'] = text(step.get('details', {}).get('logs'), 12000)
            else:
                result['note'] = 'Результат шага ещё не сохранён. Доступны события запуска.'
        # Do not include block inputs, dataset rows, outputs or arbitrary files.
        return result

