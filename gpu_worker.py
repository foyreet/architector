"""Fixed GPU neural classifier. JSON weights only; no eval, pickle or user code."""
import hashlib
from pathlib import Path
import json
import math
import sys

FORMAT = 'architect.gpu-mlp'


def device_info():
    import torch
    if torch.backends.mps.is_available():
        backend, name = 'mps', 'Apple GPU (Metal)'
    elif torch.cuda.is_available():
        backend, name = 'cuda', torch.cuda.get_device_name(0)
    else:
        raise ValueError('GPU недоступен. Нужен Apple Silicon с MPS или NVIDIA с CUDA. CPU-подмена отключена.')
    # Verify actual allocation and execution, rather than just advertised support.
    x = torch.ones((2, 2), device=backend)
    assert float((x @ x).sum().cpu()) == 8.0
    return {'backend': backend, 'device': name, 'torch': torch.__version__}


def integer(value, low, high):
    if type(value) is not int or not low <= value <= high: raise ValueError('Параметр вне допустимого диапазона.')
    return value


def vector(value, size):
    if not isinstance(value, list) or len(value) != size or any(type(v) not in (float, int) or not math.isfinite(v) or abs(v) > 1e15 for v in value):
        raise ValueError('Некорректный числовой массив.')
    return value


CHECKPOINT_FORMAT = 'architect.gpu-checkpoint'


def training_digest(data):
    return hashlib.sha256(json.dumps({k: data[k] for k in ('table', 'settings')}, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def validate_checkpoint(value, data, info=None):
    """Validate bounded JSON without importing torch (also used by the server)."""
    if not isinstance(value, dict) or value.get('format') != CHECKPOINT_FORMAT or value.get('version') != 1:
        raise ValueError('Неподдерживаемая контрольная точка обучения.')
    if value.get('worker_digest') != hashlib.sha256(Path(__file__).read_bytes()).hexdigest():
        raise ValueError('Версия GPU-программы изменилась. Начните новое обучение.')
    if value.get('training_digest') != training_digest(data):
        raise ValueError('Данные или параметры не совпадают с сохранённой точкой.')
    settings = data['settings']; width = len(data['table']['X'][0]); hidden = settings['hidden_size']
    classes = sorted(set(data['table']['y']))
    epoch = integer(value.get('epoch'), 1, settings['epochs'])
    curve = vector(value.get('loss_curve'), epoch)
    if any(v < 0 for v in curve) or value.get('classes') != classes: raise ValueError('Некорректная история обучения.')
    vector(value.get('mean'), width)
    if any(v <= 0 for v in vector(value.get('scale'), width)): raise ValueError('Некорректная нормализация.')
    versions = value.get('versions')
    if not isinstance(versions, dict) or versions.get('device') not in ('mps', 'cuda') or not isinstance(versions.get('torch'), str):
        raise ValueError('В точке отсутствуют сведения о среде обучения.')
    if info and (versions['device'] != info['backend'] or versions['torch'] != info['torch']):
        raise ValueError('Для продолжения нужны тот же backend GPU и версия PyTorch, что в сохранённой точке.')
    shapes = {'0.weight': (hidden,width), '0.bias': (hidden,None), '2.weight': (len(classes),hidden), '2.bias': (len(classes),None)}
    weights, states = value.get('weights'), value.get('optimizer')
    if not isinstance(weights, dict) or set(weights) != set(shapes) or not isinstance(states, dict) or set(states) != set(shapes):
        raise ValueError('Некорректные веса или состояние Adam.')
    def tensor(values, rows, cols):
        if cols:
            if not isinstance(values, list) or len(values) != rows: raise ValueError('Размер состояния обучения не совпадает.')
            for row in values: vector(row, cols)
        else: vector(values, rows)
    for key, (rows, cols) in shapes.items():
        tensor(weights[key], rows, cols)
        state = states[key]
        if not isinstance(state, dict) or set(state) != {'step','exp_avg','exp_avg_sq'} or type(state['step']) not in (int,float) or state['step'] != epoch:
            raise ValueError('Некорректный шаг Adam.')
        for name in ('exp_avg','exp_avg_sq'): tensor(state[name], rows, cols)
        values = state['exp_avg_sq']
        if any(v < 0 for row in (values if cols else [values]) for v in row): raise ValueError('Некорректный второй момент Adam.')
    return value


def run(data, progress=lambda value: None):
    import torch
    info = device_info(); device = info['backend']; torch.set_num_threads(1)
    versions = {'python': sys.version.split()[0], 'torch': torch.__version__, 'device': device, 'gpu': info['device']}
    task = data.get('task')
    if task not in ('train', 'evaluate', 'predict'): raise ValueError('Неизвестная GPU-операция.')
    rows = data.get('table', {}).get('X')
    if not isinstance(rows, list) or not rows or not isinstance(rows[0], list): raise ValueError('Нужна непустая таблица.')
    width = len(rows[0])
    if not width: raise ValueError('Нужен хотя бы один признак.')
    for row in rows: vector(row, width)
    X = torch.tensor(rows, dtype=torch.float32, device=device)
    if task == 'train':
        settings = data['settings']; epochs = integer(settings.get('epochs'), 1, 200)
        hidden = integer(settings.get('hidden_size'), 4, 128); seed = integer(settings.get('seed'), 0, 2147483647)
        lr = settings.get('learning_rate')
        if type(lr) not in (float, int) or not math.isfinite(lr) or not .0001 <= lr <= .1: raise ValueError('Learning rate должен быть от 0.0001 до 0.1.')
        labels = data['table'].get('y')
        if not isinstance(labels, list) or len(labels) != len(rows) or any(not isinstance(v, str) or len(v) > 200 for v in labels): raise ValueError('Некорректные классы.')
        classes = sorted(set(labels)); integer(len(classes), 2, 30)
        torch.manual_seed(seed)
        checkpoint = data.get('checkpoint')
        if checkpoint is not None: validate_checkpoint(checkpoint, data, info)
        mean = torch.tensor(checkpoint['mean'], device=device) if checkpoint else X.mean(dim=0)
        scale = torch.tensor(checkpoint['scale'], device=device) if checkpoint else X.std(dim=0, correction=0).clamp_min(1e-6)
        X = (X - mean) / scale
        y = torch.tensor([classes.index(v) for v in labels], dtype=torch.long, device=device)
        network = torch.nn.Sequential(torch.nn.Linear(width, hidden), torch.nn.ReLU(), torch.nn.Linear(hidden, len(classes))).to(device)
        optimizer = torch.optim.Adam(network.parameters(), lr=lr)
        curve = checkpoint['loss_curve'][:] if checkpoint else []
        if checkpoint:
            network.load_state_dict({k: torch.tensor(v, dtype=torch.float32, device=device) for k,v in checkpoint['weights'].items()})
            for name, parameter in network.named_parameters():
                saved = checkpoint['optimizer'][name]
                optimizer.state[parameter] = {'step': torch.tensor(float(saved['step'])),
                    **{k: torch.tensor(saved[k], dtype=torch.float32, device=device) for k in ('exp_avg','exp_avg_sq')}}
        def snapshot(epoch):
            return {'format': CHECKPOINT_FORMAT, 'version': 1, 'worker_digest': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                    'training_digest': training_digest(data), 'epoch': epoch, 'classes': classes,
                    'mean': mean.cpu().tolist(), 'scale': scale.cpu().tolist(), 'loss_curve': curve[:], 'versions': versions,
                    'weights': {k: v.detach().cpu().tolist() for k,v in network.state_dict().items()},
                    'optimizer': {name: {k: v.detach().cpu().tolist() for k,v in optimizer.state[parameter].items()}
                                  for name,parameter in network.named_parameters()}}
        for epoch in range(len(curve), epochs):
            optimizer.zero_grad(); loss = torch.nn.functional.cross_entropy(network(X), y)
            loss.backward(); optimizer.step()
            value = float(loss.detach().cpu())
            if not math.isfinite(value): raise ValueError('Обучение расходится. Уменьшите learning rate.')
            curve.append(value)
            update = {'epoch': epoch + 1, 'epochs': epochs, 'loss_curve': curve[:]}
            if data.get('checkpointing') and (epoch == 0 or (epoch + 1) % 5 == 0 or epoch + 1 == epochs): update['checkpoint'] = snapshot(epoch + 1)
            progress(update)
        return {'format': FORMAT, 'version': 1, 'classes': classes, 'hidden_size': hidden,
                'mean': mean.cpu().tolist(), 'scale': scale.cpu().tolist(),
                'weights': {k: v.detach().cpu().tolist() for k, v in network.state_dict().items()},
                'loss_curve': curve, 'resumed_from_epoch': checkpoint['epoch'] if checkpoint else 0, 'versions': versions}
    model = data.get('model', {})
    if model.get('format') != FORMAT or model.get('version') != 1: raise ValueError('Неподдерживаемая модель GPU.')
    classes = model.get('classes')
    if not isinstance(classes, list) or not 2 <= len(classes) <= 30 or len(set(classes)) != len(classes) or any(not isinstance(v, str) or len(v) > 200 for v in classes): raise ValueError('Некорректные классы модели.')
    hidden = integer(model.get('hidden_size'), 4, 128)
    mean = vector(model.get('mean'), width); scale = vector(model.get('scale'), width)
    if any(v <= 0 for v in scale): raise ValueError('Некорректный масштаб модели.')
    network = torch.nn.Sequential(torch.nn.Linear(width, hidden), torch.nn.ReLU(), torch.nn.Linear(hidden, len(classes))).to(device)
    weights = model.get('weights', {})
    if not isinstance(weights, dict) or set(weights) != {'0.weight', '0.bias', '2.weight', '2.bias'}: raise ValueError('Некорректные веса модели.')
    for key, count, cols in [('0.weight', hidden, width), ('0.bias', hidden, None), ('2.weight', len(classes), hidden), ('2.bias', len(classes), None)]:
        if cols:
            if not isinstance(weights[key], list) or len(weights[key]) != count: raise ValueError('Размер весов не совпадает.')
            for row in weights[key]: vector(row, cols)
        else: vector(weights[key], count)
    network.load_state_dict({k: torch.tensor(v, dtype=torch.float32, device=device) for k, v in weights.items()})
    network.eval()
    with torch.no_grad():
        normalized = (X - torch.tensor(mean, device=device)) / torch.tensor(scale, device=device)
        predictions = [classes[i] for i in network(normalized).argmax(dim=1).cpu().tolist()]
    if task == 'predict': return {'predictions': predictions, 'versions': versions}
    from sklearn.metrics import accuracy_score, f1_score, confusion_matrix, classification_report
    import sklearn
    actual = data['table'].get('y')
    if not isinstance(actual, list) or len(actual) != len(rows) or any(not isinstance(v, str) or len(v) > 200 for v in actual): raise ValueError('Некорректные целевые классы.')
    labels = sorted(set(actual) | set(classes)); versions['scikit-learn'] = sklearn.__version__
    return {'accuracy': accuracy_score(actual, predictions), 'macro_f1': f1_score(actual, predictions, labels=labels, average='macro', zero_division=0),
            'classes': labels, 'confusion_matrix': confusion_matrix(actual, predictions, labels=labels).tolist(),
            'report': classification_report(actual, predictions, labels=labels, output_dict=True, zero_division=0),
            'predictions': predictions, 'actual': actual, 'versions': versions}


if __name__ == '__main__':
    try:
        payload = json.loads(sys.stdin.buffer.readline())
        def progress(value):
            print(json.dumps(value, allow_nan=False), file=sys.stderr, flush=True)
            if 'checkpoint' in value and sys.stdin.buffer.readline(100) != b'checkpoint-saved\n':
                raise ValueError('Сервер не подтвердил сохранение точки. Обучение остановлено.')
        print(json.dumps({'result': run(payload, progress)}, ensure_ascii=False, allow_nan=False))
    except Exception as exc:
        print(json.dumps({'error': str(exc)[:500] if isinstance(exc, (ValueError, ImportError)) else 'Ошибка GPU. Проверьте доступную память и зависимости.'}, ensure_ascii=False))

