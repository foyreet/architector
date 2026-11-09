"""Validate Python block data and run code in a separate local process."""
import ast
import hashlib
import json
import os
import socket
import struct

import ml_operations as ml

from data_limits import JSON_DATA_BYTES, PYTHON_MESSAGE_BYTES

MAX_BYTES = PYTHON_MESSAGE_BYTES


def validate_json(value, maximum=JSON_DATA_BYTES):
    count = 0
    def walk(item, depth=0):
        nonlocal count
        count += 1
        if depth > 20 or count > 100000: ml.error('JSON слишком сложный: до 20 уровней и 100 000 значений.')
        if isinstance(item, dict):
            for key, child in item.items():
                if not isinstance(key, str) or len(key) > 200: ml.error('Ключи JSON должны быть строками до 200 символов.')
                walk(child, depth + 1)
        elif isinstance(item, list):
            for child in item: walk(child, depth + 1)
        elif item is not None and type(item) not in (str, int, float, bool): ml.error('Ожидаются данные в JSON.')
    walk(value)
    try: raw = ml.encode(value)
    except (ValueError, OverflowError): ml.error('JSON не поддерживает NaN или бесконечность.')
    if len(raw) > maximum: ml.error('JSON превышает допустимый размер.', 413)
    return value


def check_settings(settings):
    code = settings['code']
    if not code.strip(): ml.error('Напишите функцию run(inputs, params).')
    try: ast.parse(code, filename='<python-block>')
    except (SyntaxError, RecursionError) as exc: ml.error('Синтаксис Python: ' + str(exc)[:1000])
    try: params = json.loads(settings['params'])
    except (ValueError, RecursionError): ml.error('Параметры Python-блока должны быть объектом JSON.')
    if not isinstance(params, dict): ml.error('Параметры Python-блока должны быть объектом JSON.')
    return validate_json(params, 64000)


def receive(sock, size):
    result = bytearray()
    while len(result) < size:
        part = sock.recv(min(65536, size - len(result)))
        if not part: ml.error('Python-исполнитель прервал ответ.', 503)
        result.extend(part)
    return result


def sandbox(payload):
    path = os.environ.get('ARCHITECT_CODE_SOCKET')
    raw = ml.encode(payload)
    if len(raw) > MAX_BYTES: ml.error('Входные данные Python-блока больше 32 МиБ.', 413)
    if not path:
        import code_sandbox
        response = code_sandbox.run(payload)
    else:
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                connection.settimeout(payload['timeout'] + 30); connection.connect(path)
                connection.sendall(struct.pack('!I', len(raw)))
                connection.sendall(raw)
                del raw
                size = struct.unpack('!I', receive(connection, 4))[0]
                if not 0 < size <= MAX_BYTES: ml.error('Некорректный размер ответа среды.', 503)
                response = json.loads(receive(connection, size))
        except (OSError, ValueError, RecursionError):
            ml.error('Python-исполнитель недоступен. Перезапустите приложение через run_local.py.', 503)
    if not isinstance(response, dict): ml.error('Некорректный ответ среды Python.', 503)
    if response.get('error'):
        ml.error(str(response['error'])[:8000] + ('\nЖурнал:\n' + str(response.get('logs', ''))[:8000] if response.get('logs') else ''), 422)
    return response


def execute(block, root):
    import block_contracts as bc
    params = check_settings(block['settings']); inputs = dict(block['inputs'])
    references = {}
    for key, kind in [('data', 'python_data'), ('table', 'table'), ('model', 'trained_model')]:
        if key in inputs:
            references[key] = inputs[key]
            inputs[key] = ml.load(root, inputs[key], kind)
    response = sandbox({'code': block['settings']['code'], 'params': params, 'inputs': inputs, 'timeout': block['settings']['timeout']})
    result = response.get('result')
    if not isinstance(result, dict) or set(result) - {'rows', 'data', 'report'}:
        ml.error('Верните словарь с выходами rows, data и/или report.')
    rows = bc.validate_value(result.get('rows', []), {'type': 'rows'})
    data = validate_json(result.get('data', {})); report = validate_json(result.get('report', {}), 256 * 1024)
    outputs = {'rows': rows, 'data': ml.save(root, 'python_data', data), 'report': report}
    return {'status': 'ready', 'outputs': outputs, 'details': {
        'code_sha256': hashlib.sha256(block['settings']['code'].encode()).hexdigest(),
        'params': params, 'input_artifacts': references, 'runtime': response.get('runtime', {}),
        'logs': str(response.get('logs', ''))[:32000], 'row_count': len(rows), 'report': report}}

