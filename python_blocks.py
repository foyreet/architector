"""Validate Python block data and run code in a separate local process."""
import ast
import hashlib
import json
import math
import os
import socket
import struct

import ml_operations as ml


def validate_json(value):
    def walk(item):
        if isinstance(item, dict):
            for key, child in item.items():
                if not isinstance(key, str): ml.error('Ключи JSON должны быть строками.')
                walk(child)
        elif isinstance(item, list):
            for child in item: walk(child)
        elif type(item) is float and not math.isfinite(item):
            ml.error('JSON не поддерживает NaN или бесконечность.')
        elif item is not None and type(item) not in (str, int, float, bool): ml.error('Ожидаются данные в JSON.')
    walk(value)
    return value


def check_settings(settings):
    code = settings['code']
    if not code.strip(): ml.error('Напишите функцию run(inputs, params).')
    try: ast.parse(code, filename='<python-block>')
    except (SyntaxError, RecursionError) as exc: ml.error('Синтаксис Python: ' + str(exc)[:1000])
    try: params = json.loads(settings['params'])
    except (ValueError, RecursionError): ml.error('Параметры Python-блока должны быть объектом JSON.')
    if not isinstance(params, dict): ml.error('Параметры Python-блока должны быть объектом JSON.')
    return validate_json(params)


def receive(sock, size):
    result = bytearray()
    while len(result) < size:
        part = sock.recv(min(65536, size - len(result)))
        if not part: ml.error('Python-исполнитель прервал ответ.', 503)
        result.extend(part)
    return result


def sandbox(payload):
    path = os.environ.get('ARCHITECT_CODE_SOCKET')
    if not path:
        import code_sandbox
        response = code_sandbox.run(payload)
    else:
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                connection.connect(path)
                raw = ml.encode(payload)
                connection.sendall(struct.pack('!I', len(raw)))
                connection.sendall(raw)
                del raw
                size = struct.unpack('!I', receive(connection, 4))[0]
                if size <= 0: ml.error('Некорректный размер ответа среды.', 503)
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
    response = sandbox({'code': block['settings']['code'], 'params': params, 'inputs': inputs})
    result = response.get('result')
    if not isinstance(result, dict) or set(result) - {'rows', 'data', 'report'}:
        ml.error('Верните словарь с выходами rows, data и/или report.')
    rows = bc.validate_value(result.get('rows', []), {'type': 'rows'})
    data = validate_json(result.get('data', {})); report = validate_json(result.get('report', {}))
    outputs = {'rows': rows, 'data': ml.save(root, 'python_data', data), 'report': report}
    return {'status': 'ready', 'outputs': outputs, 'details': {
        'code_sha256': hashlib.sha256(block['settings']['code'].encode()).hexdigest(),
        'params': params, 'input_artifacts': references, 'runtime': response.get('runtime', {}),
        'logs': str(response.get('logs', ''))[:32000], 'row_count': len(rows), 'report': report}}

