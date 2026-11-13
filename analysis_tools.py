"""Tabular exploration and predictions with saved native classifier artifacts."""
from bisect import bisect_right
from collections import Counter
import csv
import hashlib
import io
import math
import uuid

import block_contracts as bc
import data_preview
import ml_operations as ml
import pipeline_runner as pr
import project_store as ps


def read_csv(text, separator=','):
    if not isinstance(text, str): raise bc.ContractError('Выберите CSV-файл.')
    if separator not in (',', ';', '\t'): raise bc.ContractError('Выберите разделитель CSV.')
    try:
        reader = csv.DictReader(io.StringIO(text.lstrip('\ufeff')), delimiter=separator, strict=True)
        headers = reader.fieldnames
        if not headers or len(set(headers)) != len(headers) or any(not h.strip() for h in headers): raise bc.ContractError('Нужны уникальные непустые заголовки.')
        rows = []
        for row in reader:
            if None in row or any(v is None for v in row.values()): raise bc.ContractError('Количество полей строки не совпадает с заголовком.')
            rows.append(row)
    except csv.Error: raise bc.ContractError('Не удалось прочитать CSV. Проверьте кавычки и разделитель.') from None
    bc.validate_value(rows, {'type': 'rows'})
    if not rows: raise bc.ContractError('В CSV нет строк данных.')
    return rows


def number(value):
    if value is None or isinstance(value, bool) or isinstance(value, str) and not value.strip(): return None
    try:
        v = float(value)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError, OverflowError): return None


def quantile(values, q):
    at = (len(values) - 1) * q; i = int(at)
    fraction = at - i
    return (1 - fraction) * values[i] + fraction * values[min(i + 1, len(values) - 1)]


def analyze(rows, target=''):
    bc.validate_value(rows, {'type': 'rows'})
    if not rows: raise bc.ContractError('Нет данных для анализа.')
    profile = data_preview.profile(rows); columns = [c['name'] for c in profile['columns']]
    if target and target not in columns: raise bc.ContractError('Целевая колонка не найдена.')
    statistics, numeric = [], []
    for col in columns:
        points = [(i, number(r.get(col))) for i, r in enumerate(rows)]
        valid = [(i, v) for i, v in points if v is not None]; values = sorted(v for _, v in valid)
        missing = sum(r.get(col) is None or isinstance(r.get(col), str) and not r[col].strip() for r in rows)
        entry = {'name': col, 'missing': missing, 'invalid_numeric': len(rows) - missing - len(values)}
        if values and len(values) == len(rows) - missing:
            numeric.append(col); q1, q3 = quantile(values, .25), quantile(values, .75); spread = q3 - q1
            low, high = q1 - 1.5 * spread, q3 + 1.5 * spread
            outliers = [i + 1 for i, v in valid if v < low or v > high]
            edges = [(1 - i / 10) * values[0] + (i / 10) * values[-1] for i in range(11)] if values[0] != values[-1] else [values[0], values[-1]]
            bins = [0] * (len(edges) - 1)
            for v in values:
                bins[min(len(bins) - 1, bisect_right(edges, v) - 1)] += 1
            entry.update(type='number', minimum=values[0], maximum=values[-1], mean=math.fsum(v / len(values) for v in values), median=quantile(values, .5), q1=q1, q3=q3,
                         histogram=[{'from': edges[i], 'to': edges[i + 1], 'count': count} for i, count in enumerate(bins)],
                         outliers={'rule': '1.5 × IQR', 'lower': low if math.isfinite(low) else None, 'upper': high if math.isfinite(high) else None, 'count': len(outliers), 'rows': outliers})
        else:
            counts = Counter(str(r.get(col)) for r in rows if r.get(col) is not None and str(r.get(col)).strip())
            entry.update(type='category', categories=[{'label': k, 'count': v} for k, v in counts.most_common()])
        statistics.append(entry)
    correlations = []
    for a in numeric:
        for b in numeric:
            pairs = [(number(r.get(a)), number(r.get(b))) for r in rows]; pairs = [(x, y) for x, y in pairs if x is not None and y is not None]
            correlation = None
            if len(pairs) >= 2:
                scale_x = max(abs(x) for x, _ in pairs) or 1
                scale_y = max(abs(y) for _, y in pairs) or 1
                pairs = [(x / scale_x, y / scale_y) for x, y in pairs]
                mx = math.fsum(x / len(pairs) for x, _ in pairs); my = math.fsum(y / len(pairs) for _, y in pairs)
                xx = math.fsum((x - mx) ** 2 for x, _ in pairs); yy = math.fsum((y - my) ** 2 for _, y in pairs)
                if xx and yy: correlation = max(-1, min(1, math.fsum((x - mx) * (y - my) for x, y in pairs) / math.sqrt(xx * yy)))
            correlations.append({'a': a, 'b': b, 'value': correlation, 'pairs': len(pairs)})
    balance = Counter(str(r[target]) for r in rows if target and r.get(target) is not None and str(r[target]).strip())
    return {'source_sha256': hashlib.sha256(ml.encode(rows)).hexdigest(), 'profile': profile, 'statistics': statistics, 'correlations': correlations, 'correlation_columns': numeric,
            'target': target, 'balance': [{'label': k, 'count': v} for k, v in balance.most_common()], 'target_classes': len(balance),
            'notes': 'Пропуски исключены из числовых расчётов. Корреляция Пирсона — по полным парам для числовых колонок; постоянные признаки дают null. Выбросы IQR — подсказка для проверки, а не команда удаления.'}


def infer_rows(root, model, rows):
    bc.validate_value(rows, {'type': 'rows'})
    if not rows: raise bc.ContractError('Нет строк для предсказаний.')
    features = model['features']; X = []
    for i, row in enumerate(rows):
        values = [number(row.get(key)) for key in features]
        if any(v is None for v in values): raise bc.ContractError('Строка ' + str(i + 1) + ': нужны числовые значения колонок ' + ', '.join(features))
        X.append(values)
    return ml.worker('predict', _root=root, model=model, table={'X': X})


def predict(context, body):
    ref = body.get('artifact'); kind = ref.get('kind') if isinstance(ref, dict) else None
    if kind not in ('trained_model', 'model_bundle'): raise bc.ContractError('Выберите сохранённый классификатор Архитектора.')
    model = ml.load(context.kaggle.ROOT, ref, kind)
    if kind == 'model_bundle': model = model['model']
    if model.get('format') not in ('architect.random-forest', 'architect.gpu-mlp'): raise bc.ContractError('Для этой модели пока нет операции предсказания.')
    origin = body.get('origin')
    if origin:
        if not isinstance(origin, dict): raise bc.ContractError('Некорректный источник модели.')
        step = context.pipeline.request(context.server, {k: origin.get(k) for k in ('project_id', 'run_id', 'node_id')}, 'step', context.completion, context.kaggle, context.huggingface)
        if step.get('outputs', {}).get(origin.get('port')) != ref: raise bc.ContractError('Модель не соответствует выбранному результату.')
    rows = read_csv(body.get('csv'), body.get('separator', ',')); features = model['features']
    result = infer_rows(context.kaggle.ROOT, model, rows)
    column = 'prediction'
    while column in rows[0]: column = '_' + column
    output = [dict(row, **{column: label}) for row, label in zip(rows, result['predictions'])]
    identity = str(uuid.uuid4())
    saved = {'format': 'architect.predictions', 'id': identity, 'created_at': pr.now(), 'model': ref, 'origin': origin,
             'source_sha256': hashlib.sha256(body['csv'].encode()).hexdigest(), 'features': features, 'prediction_column': column, 'rows': output, 'versions': result['versions']}
    artifact = ml.save(context.kaggle.ROOT, 'python_data', saved)
    ps.ProjectStore(context.root).write('workspace/predictions/' + identity + '.json', {'id': identity, 'created_at': saved['created_at'], 'model': ref, 'artifact': artifact, 'rows': len(rows), 'origin': origin})
    return {**saved, 'artifact': artifact}


def prediction_list(context):
    store = ps.ProjectStore(context.root); folder = store.path('workspace/predictions')
    result = [store.read('workspace/predictions/' + p.name) for p in folder.glob('*.json')] if folder.exists() else []
    return {'predictions': sorted(result, key=lambda r: r['created_at'], reverse=True)}

