"""Versioned block contracts shared by the editor and local API."""

import json
import math
from pathlib import Path
import re
import local_operations
import ml_operations
import python_blocks
from data_limits import JSON_DATA_BYTES

CATALOG = json.loads((Path(__file__).parent / 'block_contracts.json').read_text(encoding='utf-8'))
CONTRACTS = {item['kind']: item for item in CATALOG['blocks']}


class ContractError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def artifact(kind, provider, identifier, revision=None):
    result = {'type': 'artifact', 'kind': kind, 'provider': provider, 'id': identifier}
    if revision is not None:
        result['revision'] = revision
    return validate_artifact(result, kind)


def validate_artifact(value, kind):
    if (not isinstance(value, dict) or set(value) - {'type', 'kind', 'provider', 'id', 'revision'} or
            value.get('type') != 'artifact' or value.get('kind') != kind):
        raise ContractError('Ожидается ссылка на локальный артефакт, а не путь или содержимое файла.')
    identifier = value.get('id')
    if (kind in ml_operations.ARTIFACT_TYPES or kind == 'dataset') and value.get('provider') == 'local':
        valid = isinstance(identifier, str) and re.fullmatch(r'[a-f0-9]{64}', identifier) and 'revision' not in value
    elif kind == 'dataset' and value.get('provider') == 'kaggle' and 'revision' not in value:
        valid = isinstance(identifier, str) and re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]{0,99}/[a-zA-Z0-9][a-zA-Z0-9_-]{0,99}(?:/versions/[1-9][0-9]{0,8})?', identifier)
    elif kind == 'model' and value.get('provider') == 'huggingface':
        valid = (isinstance(identifier, str) and re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]{0,95}(?:/[A-Za-z0-9_][A-Za-z0-9_.-]{0,95})?', identifier)
                 and '..' not in identifier and '--' not in identifier and
                 isinstance(value.get('revision'), str) and re.fullmatch(r'[a-f0-9]{40}', value['revision']))
    else:
        valid = False
    if not valid:
        raise ContractError('Некорректная ссылка на артефакт.')
    return dict(value)


def validate_value(value, spec):
    kind = spec['type']
    if kind in ('dataset', 'model', *ml_operations.ARTIFACT_TYPES):
        return validate_artifact(value, kind)
    if kind == 'json':
        return python_blocks.validate_json(value)
    if kind in ('string', 'text'):
        valid = isinstance(value, str) and len(value) <= spec.get('maxLength', 32000)
        if valid and 'pattern' in spec:
            valid = re.fullmatch(spec['pattern'], value) is not None
    elif kind in ('integer', 'number'):
        valid = (type(value) is int if kind == 'integer' else type(value) in (int, float))
        valid = valid and math.isfinite(value) and spec.get('minimum', -math.inf) <= value <= spec.get('maximum', math.inf)
    elif kind == 'string[]':
        valid = isinstance(value, list) and len(value) <= spec.get('maxItems', 5000) and all(isinstance(s, str) and len(s) <= spec.get('maxLength', 500) for s in value)
    elif kind == 'rows':
        valid = isinstance(value, list)
        if valid:
            for row in value: validate_value(row, {'type': 'row'})
            if len(json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode('utf-8')) > JSON_DATA_BYTES:
                raise ContractError('Табличные данные в JSON больше 16 МиБ.', 413)
    elif kind == 'row':
        valid = isinstance(value, dict) and len(value) <= 100 and all(
            isinstance(k, str) and len(k) <= 200 and
            (v is None or type(v) in (str, int, float, bool)) and
            (not isinstance(v, str) or len(v) <= 32000) and
            (type(v) not in (float, int) or math.isfinite(v)) for k, v in value.items())
    else:
        valid = False
    if not valid or ('enum' in spec and value not in spec['enum']):
        raise ContractError('Некорректное значение: ' + spec.get('label', spec.get('id', kind)))
    return value


def normalize_block(value, required=False):
    if not isinstance(value, dict) or not isinstance(value.get('kind'), str):
        raise ContractError('Некорректный формат блока.')
    contract = CONTRACTS.get(value['kind'])
    if not contract or type(value.get('version')) is not int or value['version'] != contract['version']:
        raise ContractError('Неизвестный тип или версия контракта блока.')
    result = {'kind': contract['kind'], 'version': contract['version'], 'inputs': {}, 'settings': {}}
    for section, specs in (('inputs', contract['inputs']), ('settings', contract['settings'])):
        supplied = value.get(section, {})
        if not isinstance(supplied, dict):
            raise ContractError('Некорректные входы или настройки блока.')
        # Only declared fields survive import; credentials are excluded. Python source is declared only by python_code.
        for spec in specs:
            if spec['id'] in supplied:
                item = validate_value(supplied[spec['id']], spec)
            elif 'default' in spec:
                item = spec['default']
            else:
                if required and spec.get('required'):
                    raise ContractError('Не задан вход: ' + spec['label'])
                continue
            if required and spec.get('required') and isinstance(item, str) and not item.strip():
                raise ContractError('Не задан вход: ' + spec['label'])
            result[section][spec['id']] = item
    return result


def execution_fields(block):
    contract = CONTRACTS[block['kind']]
    return {spec['field']: block[section][spec['id']]
            for section in ('inputs', 'settings') for spec in contract[section]
            if 'field' in spec and spec['id'] in block[section]}


def execute(body, completion, kaggle, huggingface, poll=False):
    if set(body) - {'block', 'secrets'}:
        raise ContractError('Неизвестные параметры выполнения блока.')
    block = normalize_block(body.get('block'), required=True)
    contract = CONTRACTS[block['kind']]
    if not contract['operation']['available']:
        raise ContractError(contract['operation']['description'], 501)
    secrets = body.get('secrets', {})
    if not isinstance(secrets, dict) or set(secrets) - {'api_key', 'token'}:
        raise ContractError('Некорректный формат секретов блока.')
    if block['kind'] == 'python_code':
        if poll: raise ContractError('Python-блок возвращает результат сразу после завершения.')
        return python_blocks.execute(block, root=kaggle.ROOT)
    if block['kind'] in ml_operations.KINDS:
        if poll: raise ContractError('Обучение возвращает результат в ответе на выполнение.')
        return ml_operations.execute(block, root=kaggle.ROOT)
    fields = execution_fields(block)
    if block['kind'] in ('csv', 'template'):
        if poll:
            raise ContractError('Локальная операция возвращает результат сразу.')
        return local_operations.read_csv(block, kaggle) if block['kind'] == 'csv' else local_operations.render_template(block)
    if block['kind'] == 'openrouter':
        if poll:
            raise ContractError('OpenRouter возвращает результат в ответе на выполнение.')
        data = completion(dict(fields, api_key=secrets.get('api_key', '')))
        return {'status': 'ready', 'outputs': {'text': data['text']}, 'details': data}
    if block['kind'] == 'kaggle':
        payload = {'dataset': fields['dataset']}
        if not poll:
            payload['token'] = secrets.get('token', '')
        data = kaggle.request(payload, 'files' if poll else 'download')
        outputs = {'dataset': data['artifact']} if data['status'] == 'ready' else {}
    else:
        payload = {'repo': fields['hf_repo'], 'commit': fields['hf_commit']}
        if not poll:
            payload.update(files=fields['hf_files'], token=secrets.get('token', ''))
        data = huggingface.request(payload, 'status' if poll else 'download')
        # A model artifact denotes the locally available subset, not a runnable model guarantee.
        outputs = {'model': data['artifact']} if data['status'] == 'ready' else {}
    return {'status': data['status'], 'outputs': outputs, 'details': data}

