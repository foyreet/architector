"""Read-only summaries and results resolved through an account's project runner."""
import json
import math
import hashlib

import block_contracts as bc
import data_preview
import experiments
import ml_operations as ml



def plan(value):
    if not isinstance(value, dict): raise bc.ContractError('Некорректный план эксперимента.')
    result = {}
    for key in ('hypothesis', 'metric', 'baseline'):
        text = value.get(key, '')
        if not isinstance(text, str): raise bc.ContractError('Некорректное поле плана: ' + key)
        result[key] = text.strip()
    result['direction'] = value.get('direction', 'max')
    if result['direction'] not in ('min', 'max'): raise bc.ContractError('Выберите направление сравнения метрики.')
    result['tutorial'] = value.get('tutorial') is True
    return result


def metrics(kind, step):
    details = step.get('details', {})
    if kind == 'ml_evaluate': values = {k: details[k] for k in ('accuracy', 'macro_f1', 'test_rows') if k in details}
    elif kind == 'python_code': values = experiments.flatten(step.get('outputs', {}).get('report', {}))
    else: return {}
    return {k: v for k, v in values.items() if type(v) in (int, float) and math.isfinite(v)}


def summary(runner):
    history = runner.history()['runs']
    runs, warnings = [], []
    for item in history:
        record = runner.get(item['id']); row = {**experiments.header(record), 'metrics': {}, 'plan': record.get('experiment_plan', {})}
        for node in record['diagram']['nodes']:
            if node['block']['kind'] not in ('ml_evaluate', 'python_code') or record['nodes'].get(node['id'], {}).get('status') != 'ready': continue
            try:
                for key, value in metrics(node['block']['kind'], runner.step(record['id'], node['id'])).items():
                    row['metrics'][node['id'] + '/' + key] = {'label': node['name'] + ' · ' + key, 'value': value}
            except bc.ContractError:
                warnings.append('Результат шага недоступен: ' + node['name'])
        runs.append(row)
    return {'runs': runs, 'listed_runs': len(history), 'warnings': warnings}


def kind_of(value):
    if isinstance(value, dict) and value.get('type') == 'artifact':
        return bc.validate_artifact(value, value.get('kind'))['kind']
    if isinstance(value, list) and all(isinstance(row, dict) for row in value): return 'rows'
    return 'text' if isinstance(value, str) else 'json'


def assets(runner, run_id):
    record = runner.get(run_id); result, warnings = [], []
    for node_id in record['order']:
        if record['nodes'].get(node_id, {}).get('status') != 'ready': continue
        try:
            step = runner.step(run_id, node_id)
            labels = {p['id']: p['label'] for p in bc.CONTRACTS.get(step.get('block', {}).get('kind'), {}).get('outputs', [])}
            for port, value in step.get('outputs', {}).items():
                kind = kind_of(value)
                block_kind = step.get('block', {}).get('kind')
                result.append({'node_id': node_id, 'node_name': record['nodes'][node_id]['name'], 'port': port,
                               'label': labels.get(port, port), 'kind': kind, 'reference': value if isinstance(value, dict) and value.get('type') == 'artifact' else None,
                               'block_kind': block_kind,
                               'metric_summary': metrics(block_kind, step) if kind == 'metrics' or block_kind == 'python_code' and port == 'report' else {},
                               'rows': len(value) if kind == 'rows' else None,
                               'versions': {k: v for k, v in step.get('versions', {}).items() if k in ('dataset_version', 'archive_sha256', 'version_note', 'code_sha256')}})
        except bc.ContractError as exc: warnings.append(str(exc))
    return {'run': experiments.header(record), 'assets': result, 'warnings': warnings}


def asset(runner, body, kaggle, huggingface):
    step = runner.step(body.get('run_id'), body.get('node_id'))
    port = body.get('port')
    if step.get('status') != 'ready' or not isinstance(port, str) or port not in step.get('outputs', {}):
        raise bc.ContractError('Результат шага ещё не готов или не найден.', 404)
    value = step['outputs'][port]; kind = kind_of(value)
    if kind in ml.ARTIFACT_TYPES: value = ml.load(runner.root, value, kind)
    elif kind == 'dataset':
        local = kaggle.request({'dataset': value['id']}, 'files')
        if local.get('status') != 'ready': raise bc.ContractError('Файлы датасета больше не доступны локально. История запуска сохранена.', 404)
        if body.get('file') is not None:
            expected = step.get('versions', {}).get('archive_sha256')
            if expected:
                digest = hashlib.sha256()
                with kaggle.archive_path(kaggle.dataset_handle(value['id'])).open('rb') as source:
                    for chunk in iter(lambda: source.read(1024 * 1024), b''): digest.update(chunk)
                if digest.hexdigest() != expected: raise bc.ContractError('Локальный датасет изменился после запуска. Его содержимое не соответствует сохранённому результату.', 409)
            return {'format': 'file', 'content': kaggle.request({'dataset': value['id'], 'file': body['file']}, 'preview')}
        return {'format': 'files', 'content': local, 'preview_files': True}
    elif kind == 'model':
        return {'format': 'files', 'content': huggingface.read_manifest(value['id'], value['revision']), 'preview_files': False}
    if body.get('download') is True: return {'content': value, 'kind': kind}
    if kind == 'table':
        value = [dict(zip(value['features'], row), **{value['target']: label}) for row, label in zip(value['X'], value['y'])]
    if kind in ('rows', 'table'):
        page = body.get('page', 0)
        if type(page) is not int or page < 0: raise bc.ContractError('Некорректная страница.')
        bc.validate_value(value, {'type': 'rows'})
        return {'format': 'table', 'profile': data_preview.profile(value), 'rows': value[page*50:(page+1)*50], 'page': page, 'page_size': 50}
    encoded = json.dumps(value, ensure_ascii=False, indent=2)
    result = {'format': 'text', 'text': encoded, 'truncated': False, 'kind': kind}
    block_kind = step.get('block', {}).get('kind')
    if kind == 'metrics' or block_kind == 'python_code' and port == 'report':
        result['metric_summary'] = metrics(block_kind, step)
        result['block_kind'] = block_kind
        if kind == 'metrics' and isinstance(value, dict):
            classes = value.get('classes', [])
            if isinstance(classes, list):
                result['classification'] = {key: value[key] for key in ('classes', 'confusion_matrix', 'report') if key in value}
    return result


def request(runner, body, action, kaggle, huggingface):
    if action == 'overview': return summary(runner)
    if action == 'assets': return assets(runner, body.get('run_id'))
    return asset(runner, body, kaggle, huggingface)

