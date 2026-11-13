"""Read-only run projections and editable experiment notes; no execution."""
from datetime import datetime
import hashlib
import json
import math

from block_contracts import ContractError


def notes(value):
    if not isinstance(value, dict):
        raise ContractError('Некорректное описание эксперимента.')
    result = {}
    for key in ('title', 'hypothesis', 'conclusion'):
        text = value.get(key, '')
        if not isinstance(text, str):
            raise ContractError(f'Поле {key}: ожидается текст.')
        result[key] = text.strip()
    tags = value.get('tags', [])
    if not isinstance(tags, list) or any(not isinstance(t, str) or not t.strip() for t in tags):
        raise ContractError('Каждый тег должен быть непустой строкой.')
    result['tags'] = list(dict.fromkeys(t.strip() for t in tags))
    revision = value.get('revision', 0)
    if type(revision) is not int or revision < 0:
        raise ContractError('Некорректная версия описания.')
    result['revision'] = revision
    return result


def duration(start, end):
    if not start or not end:
        return None
    try:
        return max(0, (datetime.fromisoformat(end.replace('Z', '+00:00')) -
                       datetime.fromisoformat(start.replace('Z', '+00:00'))).total_seconds())
    except (ValueError, TypeError, AttributeError):
        return None


def header(record):
    return {**{k: record.get(k) for k in ('id', 'name', 'status', 'created_at', 'finished_at', 'error', 'project')},
            'duration': duration(record.get('started_at') or record.get('created_at'), record.get('finished_at')),
            'experiment': notes(record.get('experiment', {}))}


def flatten(value, prefix=''):
    """Project nested metrics onto named columns, keeping arrays as values."""
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            result.update(flatten(item, prefix + (' / ' if prefix else '') + str(key)))
        return result
    return {prefix: value}


def comparison(runner, run_id):
    record = runner.get(run_id)
    result = {**header(record), 'metrics': {}, 'parameters': {}, 'versions': {}, 'steps': [], 'warnings': []}
    for node in record['diagram']['nodes']:
        block = node['block']; kind = block['kind']; node_id = node['id']
        label = node['name'] + ' [' + node_id[:8] + ']'
        def add(group, values):
            for key, value in flatten(values).items():
                result[group][node_id + '/' + key] = {'label': label + ' · ' + key, 'value': value}
        settings = dict(block.get('settings', {}))
        if kind == 'python_code':
            settings['code_sha256'] = hashlib.sha256(settings.pop('code', '').encode()).hexdigest()
            try:
                settings['params'] = json.loads(settings.get('params', '{}'))
            except (ValueError, TypeError):
                pass
        add('parameters', {'operation': kind, 'contract_version': block.get('version'), **settings})
        state = record['nodes'].get(node_id, {})
        result['steps'].append({'id': node_id, 'name': node['name'], 'status': state.get('status'),
                                'duration': duration(state.get('started_at'), state.get('finished_at'))})
        if node_id not in record['order'] or state.get('status') != 'ready':
            continue
        try:
            step = runner.step(run_id, node_id)
        except ContractError:
            result['warnings'].append(label + ': файл результата недоступен.')
            continue
        details = step.get('details', {})
        if not isinstance(details, dict):
            result['warnings'].append(label + ': некорректный формат результата.')
            continue
        if kind == 'ml_evaluate':
            metrics = {key: details[key] for key in ('accuracy', 'macro_f1', 'test_rows') if key in details}
        elif kind == 'python_code':
            outputs = step.get('outputs', {})
            metrics = flatten(outputs.get('report', {}) if isinstance(outputs, dict) else {})
            metrics = {k: v for k, v in metrics.items() if type(v) in (int, float) and math.isfinite(v)}
        else:
            metrics = {}
        add('metrics', metrics)
        versions = step.get('versions', details)
        if not isinstance(versions, dict):
            versions = {}
        # Retain identities and runtime versions, not samples, predictions or logs.
        selected = {k: versions[k] for k in ('artifact', 'dataset_version', 'archive_sha256', 'versions',
                    'runtime', 'code_sha256', 'source_sha256', 'sha256', 'file', 'split_id', 'requested_model',
                    'response_model', 'immutable_revision', 'version_note') if k in versions}
        refs = {key: value for key, value in step.get('block', {}).get('inputs', {}).items()
                if isinstance(value, dict) and 'kind' in value and 'id' in value}
        if refs:
            selected['input_artifacts'] = refs
        if kind == 'huggingface':
            selected['commit'] = step.get('block', {}).get('settings', {}).get('commit')
        add('versions', selected)
    return result


def request(runner, body, action):
    if action == 'experiments':
        return {'runs': [header(runner.get(item['id'])) for item in runner.history()['runs']]}
    if action == 'compare':
        ids = body.get('run_ids')
        if not isinstance(ids, list) or not ids or any(not runner.valid_id(i) for i in ids) or len(set(ids)) != len(ids):
            raise ContractError('Выберите разные запуски.')
        return {'runs': [comparison(runner, run_id) for run_id in ids]}
    value = notes(body.get('experiment'))
    with runner.lock:
        record = runner.get(body.get('run_id'))
        old = notes(record.get('experiment', {}))
        if value['revision'] != old['revision']:
            raise ContractError('Описание изменено в другой вкладке. Обновите список экспериментов.', 409)
        value['revision'] += 1
        record['experiment'] = value
        runner.save(record)
        if runner.current and runner.current['id'] == record['id']:
            runner.current['experiment'] = value
        return header(record)

