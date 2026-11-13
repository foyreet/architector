"""CSV reading and literal prompt templates; no code evaluation."""

import csv
import codecs
from contextlib import contextmanager
import hashlib
import io
import struct
import sys
import re
import zipfile

try:
    csv.field_size_limit(sys.maxsize)
except OverflowError:
    # Older CPython CSV parsers use C long, which is 32-bit on 64-bit Windows.
    csv.field_size_limit((1 << (struct.calcsize('l') * 8 - 1)) - 1)

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


def csv_codec(prefix, encoding):
    codec = encoding
    if encoding == 'auto':
        codec = ('utf-32' if prefix.startswith((codecs.BOM_UTF32_LE, codecs.BOM_UTF32_BE)) else
                 'utf-16' if prefix.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)) else 'utf-8-sig')
    elif encoding == 'utf-8':
        codec = 'utf-8-sig'
    return codec


def decode_csv(raw, encoding):
    from block_contracts import ContractError
    codec = csv_codec(raw, encoding)
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


def detect_delimiter(text):
    end = text.find('\n', 8192)
    sample = text if end < 0 else text[:end + 1]
    return csv.Sniffer().sniff(sample, delimiters=',;\t').delimiter


def csv_headers(headers):
    from block_contracts import ContractError
    if not headers:
        raise ContractError('CSV должен содержать заголовки.')
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
                with archive.open(name) as source:
                    raw = source.read()
        return raw, name
    except FileNotFoundError:
        raise ContractError('Сначала скачайте датасет в блоке Kaggle.', 404) from None
    except (OSError, zipfile.BadZipFile, RuntimeError, NotImplementedError):
        raise ContractError('Не удалось прочитать CSV из локального датасета.', 422) from None


@contextmanager
def csv_lines(block, kaggle):
    from block_contracts import ContractError
    ref = block['inputs']['dataset']
    if ref['provider'] == 'local':
        import ml_operations as ml
        dataset = ml.load(kaggle.ROOT, ref, 'dataset')
        if dataset.get('format') != 'architect.uploaded-csv':
            raise ContractError('CSV-файл не найден в загруженном датасете.', 404)
        requested = block['inputs']['file']
        name = csv_filename(requested, [dataset['name']]) if requested.strip() else dataset['name']
        text = dataset['csv']
        digest = hashlib.sha256()
        for start in range(0, len(text), 65536):
            digest.update(text[start:start + 65536].encode('utf-8'))
        with io.StringIO(text, newline='') as source:
            yield source, name, 'utf-8-sig', digest
        return

    try:
        with zipfile.ZipFile(kaggle.archive_path(kaggle.dataset_handle(ref['id']))) as archive:
            names = [entry['name'] for entry in kaggle.archive_members(archive)]
            name = csv_filename(block['inputs']['file'], names)
            with archive.open(name) as raw:
                digest = hashlib.file_digest(raw, 'sha256')
                raw.seek(0)
                codec = csv_codec(raw.peek(4), block['settings'].get('encoding', 'auto'))
                with io.TextIOWrapper(raw, encoding=codec, newline='') as source:
                    yield source, name, codec, digest
    except UnicodeError:
        raise ContractError('Не удалось прочитать CSV. Выберите кодировку файла в настройках блока «Чтение CSV».', 422) from None
    except FileNotFoundError:
        raise ContractError('Сначала скачайте датасет в блоке Kaggle.', 404) from None
    except (OSError, zipfile.BadZipFile, RuntimeError, NotImplementedError):
        raise ContractError('Не удалось прочитать CSV из локального датасета.', 422) from None


def read_csv(block, kaggle):
    from block_contracts import ContractError
    settings = block['settings']
    try:
        with csv_lines(block, kaggle) as (source, name, encoding, digest):
            def lines():
                for index, line in enumerate(source):
                    if '\x00' in line:
                        raise ContractError('В CSV обнаружены нулевые символы. Проверьте кодировку файла.', 422)
                    yield line.removeprefix('\ufeff') if index == 0 else line
            reader = csv.reader(lines(), delimiter=settings['delimiter'], strict=True)
            headers, generated = csv_headers(next(reader, None))
            rows = []
            for values in reader:
                if not values:  # Ignore empty physical rows, like common CSV readers.
                    continue
                if len(values) != len(headers):
                    raise ContractError('Некорректная строка CSV: проверьте разделитель, число столбцов.')
                row = dict(zip(headers, values))
                rows.append(row)
            if settings['row_index'] >= len(rows):
                raise ContractError('Выбранной строки нет в CSV. Уменьшите её номер.')
            return {'status': 'ready', 'outputs': {'rows': rows, 'row': rows[settings['row_index']]},
                    'details': {'file': name, 'row_count': len(rows), 'row_index': settings['row_index'],
                                'truncated': False, 'sha256': digest.hexdigest(), 'encoding': encoding,
                                'generated_headers': generated}}
    except csv.Error:
        raise ContractError('Не удалось разобрать структуру CSV. Проверьте разделитель и кавычки в файле.', 422) from None

