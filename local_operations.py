"""Bounded CSV reading and literal prompt templates; no code evaluation."""

import csv
import codecs
import hashlib
import io
import json
import re
import zipfile

from data_limits import JSON_DATA_BYTES

MAX_CSV_BYTES = 8 * 1024 * 1024

MAX_OUTPUT_BYTES = JSON_DATA_BYTES
PLACEHOLDER = re.compile(r'\{\{\s*([^{}]+?)\s*\}\}')


def template_fields(template):
    from block_contracts import ContractError
    if not template.strip():
        raise ContractError('Заполните шаблон промпта.')
    if '{{' in PLACEHOLDER.sub('', template) or '}}' in PLACEHOLDER.sub('', template):
        raise ContractError('Некорректный шаблон. Используйте {{имя_колонки}}.')
    return [match.group(1).strip() for match in PLACEHOLDER.finditer(template)]


def render_template(block):
    from block_contracts import ContractError
    row = block['inputs']['row']
    template = block['settings']['template']
    fields = template_fields(template)
    missing = [key for key in fields if key not in row]
    if missing:
        raise ContractError('В строке нет полей шаблона: ' + ', '.join(dict.fromkeys(missing))[:1000])
    def replace(match):
        value = row[match.group(1).strip()]
        return '' if value is None else str(value)
    text = PLACEHOLDER.sub(replace, template)
    if len(text) > 32000:
        raise ContractError('Промпт после подстановки длиннее 32 000 символов.', 413)
    return {'status': 'ready', 'outputs': {'text': text}, 'details': {'fields': list(dict.fromkeys(fields))}}


def csv_filename(requested, names):
    from block_contracts import ContractError
    if requested in names:
        return requested
    candidates = sorted(name for name in names if name.lower().endswith('.csv'))
    if not requested.strip() and len(candidates) == 1:
        return candidates[0]
    available = ' Доступные CSV: ' + '; '.join(candidates[:10]) if candidates else ' В датасете нет файлов с расширением .csv.'
    if len(candidates) > 10:
        available += '; … (показаны первые 10)'
    message = ('CSV-файл не найден в датасете: ' + requested[:200] + '.' if requested.strip()
               else 'В датасете несколько CSV. Укажите имя файла в настройках блока.' if candidates
               else 'Не удалось автоматически выбрать CSV.')
    raise ContractError(message + available + ' Укажите точное имя с учётом папок и регистра.', 404 if requested.strip() else 400)


def decode_csv(raw, encoding):
    from block_contracts import ContractError
    codec = encoding
    if encoding == 'auto':
        codec = ('utf-32' if raw.startswith((codecs.BOM_UTF32_LE, codecs.BOM_UTF32_BE)) else
                 'utf-16' if raw.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)) else 'utf-8-sig')
    elif encoding == 'utf-8':
        codec = 'utf-8-sig'
    try:
        text = raw.decode(codec)
    except UnicodeError:
        selected = 'UTF-8 / Unicode с BOM (авто)' if encoding == 'auto' else encoding
        raise ContractError('Не удалось прочитать CSV в кодировке «' + selected +
                            '». Выберите кодировку файла в настройках блока «Чтение CSV» и проверьте данные через просмотр. '
                            'Авто поддерживает UTF-8 и Unicode с BOM. Для другой кодировки можно попросить AI Chat подобрать её по фрагменту CSV.', 422) from None
    if '\x00' in text:
        raise ContractError('В CSV обнаружены нулевые символы. Проверьте кодировку: для UTF-16 без BOM выберите UTF-16 LE или UTF-16 BE. '
                            'Если файл не текстовый, выберите CSV.', 422)
    return text.removeprefix('\ufeff'), codec


def csv_headers(headers):
    from block_contracts import ContractError
    if not headers or len(headers) > 100 or any(len(name) > 200 for name in headers):
        raise ContractError('CSV должен содержать заголовки, до 100 столбцов и 200 символов в имени.')
    named = [name for name in headers if name.strip()]
    if len(set(named)) != len(named):
        raise ContractError('CSV должен иметь уникальные заголовки: переименуйте повторяющиеся столбцы.')
    used, generated = set(named), []
    for index, name in enumerate(headers):
        if name.strip():
            continue
        base = 'column_' + str(index + 1)
        name, suffix = base, 2
        while name in used:
            name = base + '_' + str(suffix)
            suffix += 1
        headers[index] = name
        used.add(name)
        generated.append(name)
    return headers, generated


def csv_source(block, kaggle):
    from block_contracts import ContractError
    ref, name = block['inputs']['dataset'], block['inputs']['file']
    try:
        if ref['provider'] == 'local':
            import ml_operations as ml
            dataset = ml.load(kaggle.ROOT, ref, 'dataset')
            if dataset.get('format') != 'architect.uploaded-csv':
                raise ContractError('CSV-файл не найден в загруженном датасете.', 404)
            name = csv_filename(name, [dataset['name']]) if name.strip() else dataset['name']
            raw = dataset['csv'].encode('utf-8')
        else:
            handle = kaggle.dataset_handle(ref['id'])
            with zipfile.ZipFile(kaggle.archive_path(handle)) as archive:
                members = {item['name']: item for item in kaggle.archive_members(archive)}
                name = csv_filename(name, members)
                if members[name]['size'] > MAX_CSV_BYTES:
                    raise ContractError('Для чтения CSV поддерживаются файлы до 8 МиБ.', 413)
                with archive.open(name) as source:
                    raw = source.read(MAX_CSV_BYTES + 1)
        if len(raw) > MAX_CSV_BYTES:
            raise ContractError('CSV больше лимита 8 МиБ.', 413)
        return raw, name
    except FileNotFoundError:
        raise ContractError('Сначала скачайте датасет в блоке Kaggle.', 404) from None
    except (OSError, zipfile.BadZipFile, RuntimeError, NotImplementedError):
        raise ContractError('Не удалось прочитать CSV из локального датасета.', 422) from None


def read_csv(block, kaggle):
    from block_contracts import ContractError
    settings = block['settings']
    raw, name = csv_source(block, kaggle)
    try:
        # Uploaded datasets already contain Unicode normalized by the upload wizard.
        text, encoding = decode_csv(raw, 'utf-8' if block['inputs']['dataset']['provider'] == 'local' else settings.get('encoding', 'auto'))
        reader = csv.reader(io.StringIO(text), delimiter=settings['delimiter'], strict=True)
        headers, generated = csv_headers(next(reader, None))
        rows, size = [], 1
        for values in reader:
            if not values:  # Ignore empty physical rows, like common CSV readers.
                continue
            if len(values) != len(headers) or any(len(value) > 32000 for value in values):
                raise ContractError('Некорректная строка CSV: проверьте разделитель, число столбцов и длину ячеек.')
            row = dict(zip(headers, values))
            size += len(json.dumps(row, ensure_ascii=False, separators=(',', ':')).encode('utf-8')) + 1
            if size > MAX_OUTPUT_BYTES:
                raise ContractError('Результат чтения CSV больше 16 МиБ. Файл не обработан: частичное чтение не выполняется.', 413)
            rows.append(row)
        if settings['row_index'] >= len(rows):
            raise ContractError('Выбранной строки нет в CSV. Уменьшите её номер.')
        return {'status': 'ready', 'outputs': {'rows': rows, 'row': rows[settings['row_index']]},
                'details': {'file': name, 'row_count': len(rows), 'row_index': settings['row_index'],
                            'truncated': False, 'sha256': hashlib.sha256(raw).hexdigest(), 'encoding': encoding,
                            'generated_headers': generated}}
    except csv.Error:
        raise ContractError('Не удалось разобрать структуру CSV. Проверьте разделитель и кавычки в файле.', 422) from None

