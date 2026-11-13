"""Small tabular classification pipeline with account-scoped, hashed JSON artifacts."""
from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading

from app_config import data_root

KINDS = ('ml_prepare', 'ml_split', 'ml_train', 'gpu_train', 'ml_evaluate', 'ml_save')
ARTIFACT_TYPES = ('table', 'trained_model', 'metrics', 'model_bundle', 'python_data')
WORKER_LOCK = threading.Lock()


def error(message, status=400):
    from block_contracts import ContractError
    raise ContractError(message, status)


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def artifact_dir(root):
    root = Path(root)
    folder = root / 'workspace' / 'ml-artifacts'
    for path in (root, root / 'workspace', folder):
        if path.is_symlink(): error('Каталог артефактов не должен быть символической ссылкой.')
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    return folder


def save(root, kind, content):
    from block_contracts import artifact
    raw = encode({'kind': kind, 'content': content})
    digest = hashlib.sha256(raw).hexdigest()
    folder = artifact_dir(root); target = folder / (digest + '.json')
    with tempfile.NamedTemporaryFile(dir=folder, delete=False) as stream:
        name = stream.name
        try:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        except BaseException:
            Path(name).unlink(missing_ok=True)
            raise
    try: os.replace(name, target)
    finally: Path(name).unlink(missing_ok=True)
    return artifact(kind, 'local', digest)


def load(root, ref, kind):
    from block_contracts import validate_artifact
    validate_artifact(ref, kind)
    path = artifact_dir(root) / (ref['id'] + '.json')
    if path.is_symlink() or not path.is_file(): error('Артефакт недоступен в этом аккаунте. Запустите предыдущие блоки.', 404)
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != ref['id']: error('Артефакт повреждён: контрольная сумма не совпала.')
    value = json.loads(raw)
    if value['kind'] != kind: error('Тип артефакта не совпадает.')
    return value['content']


def worker(task, _root=None, **kwargs):
    import gpu_compute
    if task == 'gpu_train' or kwargs.get('model', {}).get('format') == gpu_compute.FORMAT:
        return gpu_compute.broker().execute(_root or data_root(), 'train' if task == 'gpu_train' else task, kwargs)
    if not WORKER_LOCK.acquire(blocking=False): error('Обучение или оценка уже выполняется. Повторите запуск после завершения.', 409)
    try:
        local_python = Path(__file__).parent / '.venv/bin/python'
        executable = os.environ.get('ARCHITECT_ML_PYTHON') or (str(local_python) if local_python.exists() else sys.executable)
        env = {**os.environ, 'OMP_NUM_THREADS': '1', 'OPENBLAS_NUM_THREADS': '1', 'MKL_NUM_THREADS': '1', 'VECLIB_MAXIMUM_THREADS': '1'}
        try:
            result = subprocess.run([executable, '-I', str(Path(__file__).with_name('ml_worker.py'))],
                                    input=encode({'task': task, **kwargs}), stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, timeout=120, env=env)
        except subprocess.TimeoutExpired: error('Обучение превысило 120 секунд. Уменьшите число деревьев или глубину.', 408)
        except OSError: error('Не удалось запустить среду обучения. Проверьте ARCHITECT_ML_PYTHON.', 503)
        if result.returncode: error('Среда обучения завершилась с ошибкой. Проверьте зависимости и доступную память.', 503)
        response = json.loads(result.stdout)
        if 'error' in response: error(response['error'])
        return response['result']
    finally:
        WORKER_LOCK.release()


def columns(value):
    return [s.strip() for s in value.split(',') if s.strip()]


def prepare(rows, settings):
    target = settings['target'].strip()
    if not target: error('Укажите целевую колонку, например Species.')
    if not rows: error('В таблице нет строк.')
    features = columns(settings['features']) or [key for key in rows[0] if key != target and key not in columns(settings['drop'])]
    if not features or target in features or len(set(features)) != len(features): error('Укажите уникальные признаки без целевой колонки.')
    required = [*features, target]
    if any(key not in rows[0] for key in required): error('В CSV отсутствует колонка: ' + ', '.join(key for key in required if key not in rows[0]))
    X, y, row_ids, seen = [], [], [], set(); dropped = duplicates = 0
    for index, row in enumerate(rows):
        try:
            label = row[target]
            if label is None or not str(label).strip() or len(str(label)) > 200: raise ValueError()
            values = [float(row[key]) for key in features]
            if any(not math.isfinite(v) or abs(v) > 1e15 for v in values): raise ValueError()
        except (KeyError, TypeError, ValueError, OverflowError):
            if settings['missing'] == 'error': error(f'Строка {index + 1}: пропуск, нечисловой признак или некорректная цель. Выберите числовые признаки или удаление таких строк.')
            dropped += 1; continue
        label = str(label).strip(); signature = tuple(values) + (label,)
        if signature in seen and settings['duplicates'] == 'drop': duplicates += 1; continue
        seen.add(signature); X.append(values); y.append(label); row_ids.append(index)
    counts = Counter(y)
    if not 2 <= len(counts) <= 30: error('Для классификации нужно от 2 до 30 классов. Для непрерывной цели пока нет блока регрессии.')
    if min(counts.values()) < 2: error('Каждый класс должен содержать хотя бы 2 строки для разделения train/test.')
    return {'X': X, 'y': y, 'row_ids': row_ids, 'features': features, 'target': target, 'role': 'prepared',
            'source_sha256': hashlib.sha256(encode(rows)).hexdigest(), 'settings': settings}, {
                'input_rows': len(rows), 'rows': len(y), 'dropped_rows': dropped, 'duplicates_removed': duplicates,
                'features': features, 'target': target, 'classes': dict(counts)}


def execute(block, root=None):
    root = Path(root or data_root()); kind = block['kind']; inputs = block['inputs']; settings = block['settings']
    if kind == 'ml_prepare':
        table, details = prepare(inputs['rows'], settings)
        outputs = {'table': save(root, 'table', table)}
    elif kind == 'ml_split':
        table = load(root, inputs['table'], 'table')
        if table['role'] != 'prepared': error('Разделение ожидает таблицу из блока подготовки данных.')
        split = worker('split', table=table, settings=settings)
        split_id = hashlib.sha256(encode({'source': inputs['table'], 'settings': settings, 'split': split})).hexdigest()
        outputs = {}
        for side in ('train', 'test'):
            indices = split[side]
            part = {**table, 'role': side, 'split_id': split_id, 'source': inputs['table'],
                    'split_settings': settings, 'split_versions': split['versions']}
            for key in ('X', 'y', 'row_ids'): part[key] = [table[key][i] for i in indices]
            outputs[side] = save(root, 'table', part)
        details = {'train_rows': len(split['train']), 'test_rows': len(split['test']), 'settings': settings, 'versions': split['versions'], 'split_id': split_id}
    elif kind in ('ml_train', 'gpu_train'):
        table = load(root, inputs['train'], 'table')
        if table['role'] != 'train': error('Обучение принимает только выход Train блока разделения.')
        model = worker('gpu_train' if kind == 'gpu_train' else 'train', _root=root, table=table, settings=settings)
        model.update(features=table['features'], target=table['target'], split_id=table['split_id'], train=inputs['train'],
                     train_row_ids=table['row_ids'], settings=settings)
        outputs = {'model': save(root, 'trained_model', model)}
        details = {'train_rows': len(table['y']), 'features': model['features'], 'classes': model['classes'],
                   'settings': settings, 'versions': model['versions']}
        if 'feature_importances' in model: details['feature_importances'] = dict(zip(model['features'], model['feature_importances']))
        if 'loss_curve' in model: details['loss_curve'] = model['loss_curve']
        if 'resumed_from_epoch' in model: details['resumed_from_epoch'] = model['resumed_from_epoch']
    elif kind == 'ml_evaluate':
        model = load(root, inputs['model'], 'trained_model'); table = load(root, inputs['test'], 'table')
        if (table['role'] != 'test' or table.get('split_id') != model['split_id'] or table['features'] != model['features'] or
                table['target'] != model['target'] or set(table['row_ids']) & set(model['train_row_ids'])):
            error('Подайте Test из того же разбиения, что использовалось при обучении. Train нельзя использовать для итоговой оценки.')
        metrics = worker('evaluate', _root=root, table=table, model=model)
        metrics.update(model=inputs['model'], test=inputs['test'], test_rows=len(table['y']))
        outputs = {'model': inputs['model'], 'metrics': save(root, 'metrics', metrics)}
        details = {key: value for key, value in metrics.items() if key not in ('predictions', 'actual')}
    elif kind == 'ml_save':
        model = load(root, inputs['model'], 'trained_model'); metrics = load(root, inputs['metrics'], 'metrics')
        if metrics['model'] != inputs['model']: error('Метрики относятся к другой модели.')
        if not settings['name'].strip(): error('Укажите имя сохраняемой модели.')
        train = load(root, model['train'], 'table')
        # Export only schema/settings/provenance, not training rows.
        bundle = {'format': 'architect.model-package', 'version': 1, 'name': settings['name'].strip(), 'model': model,
                  'metrics': {k: v for k, v in metrics.items() if k not in ('actual', 'predictions')},
                  'preparation': train['settings'], 'split': train['split_settings'], 'source_sha256': train['source_sha256'],
                  'source_artifact': train['source'], 'split_versions': train['split_versions']}
        ref = save(root, 'model_bundle', bundle)
        outputs = {'bundle': ref}
        details = {'name': bundle['name'], 'artifact': ref, 'path': 'workspace/ml-artifacts/' + ref['id'] + '.json',
                   'format': bundle['format'], 'accuracy': metrics['accuracy'], 'macro_f1': metrics['macro_f1'], 'versions': model['versions']}
    else: error('Неизвестная операция обучения.')
    return {'status': 'ready', 'outputs': outputs, 'details': details}

