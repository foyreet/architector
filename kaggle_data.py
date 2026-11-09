"""Bounded Kaggle downloads and local ZIP previews; no third-party packages."""

import csv
import io
import os
from pathlib import Path, PurePosixPath
import re
import tempfile
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, HTTPRedirectHandler, build_opener
import zipfile
from block_contracts import artifact
from app_config import data_root

ALLOW_ENVIRONMENT = True
ROOT = data_root()
MAX_DOWNLOAD = 512 * 1024 * 1024
MAX_UNPACKED = 2 * 1024 * 1024 * 1024
MAX_FILES = 10000
PREVIEW_BYTES = 64 * 1024
LOCK = threading.RLock()
JOBS = {}


class KaggleError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def dataset_handle(value):
    if not isinstance(value, str) or len(value) > 500:
        raise KaggleError('Укажите ссылку Kaggle или owner/dataset.')
    value = value.strip()
    if value.startswith('https://'):
        parsed = urlsplit(value)
        if parsed.netloc not in ('kaggle.com', 'www.kaggle.com') or not parsed.path.startswith('/datasets/'):
            raise KaggleError('Нужна ссылка вида https://www.kaggle.com/datasets/owner/dataset.')
        value = parsed.path[len('/datasets/'):].rstrip('/')
    if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]{0,99}/[a-zA-Z0-9][a-zA-Z0-9_-]{0,99}(?:/versions/[1-9][0-9]{0,8})?', value):
        raise KaggleError('Укажите owner/dataset или ссылку на датасет Kaggle. Соревнования не поддерживаются.')
    return value.lower()


def archive_path(handle, root=None):
    root = ROOT if root is None else Path(root)
    parts = handle.split('/')
    path = root / 'workspace' / 'datasets' / parts[0] / parts[1] / (parts[3] if len(parts) == 4 else 'latest') / 'dataset.zip'
    # Never follow a locally supplied symlink outside the project (or into another dataset).
    for parent in (path, *path.parents):
        if parent == root:
            break
        if parent.is_symlink():
            raise KaggleError('Папка датасета содержит символическую ссылку.', 403)
    return path


class KaggleRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        parsed = urlsplit(newurl)
        if parsed.scheme != 'https' or parsed.netloc not in (
                'www.kaggle.com', 'kaggle.com', 'storage.googleapis.com', 'storage.googleapis.com:443'):
            raise KaggleError('Kaggle вернул неподдерживаемый адрес скачивания.', 502)
        redirected = super().redirect_request(request, fp, code, msg, headers, newurl)
        if redirected is not None:
            # Signed storage URLs don't need the Kaggle credential.
            redirected.remove_header('Authorization')
        return redirected


def download_archive(handle, token, destination, progress):
    parts = handle.split('/')
    url = 'https://www.kaggle.com/api/v1/datasets/download/' + '/'.join(parts[:2])
    if len(parts) == 4:
        url += '?datasetVersionNumber=' + parts[3]
    headers = {'User-Agent': 'Architect/1.0', 'Accept': 'application/zip'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    started = time.monotonic()
    try:
        with build_opener(KaggleRedirect()).open(Request(url, headers=headers), timeout=30) as response:
            length = response.headers.get('Content-Length', '')
            total = int(length) if length.isdigit() else 0
            if total > MAX_DOWNLOAD:
                raise KaggleError('Архив больше лимита 512 МиБ.', 413)
            count = 0
            with destination.open('wb') as output:
                while True:
                    if time.monotonic() - started > 600:
                        raise KaggleError('Скачивание превысило 10 минут. Повторите позже.', 504)
                    chunk = response.read(256 * 1024)
                    if not chunk:
                        break
                    count += len(chunk)
                    if count > MAX_DOWNLOAD:
                        raise KaggleError('Архив больше лимита 512 МиБ.', 413)
                    output.write(chunk)
                    progress(count, total)
            if total and count != total:
                raise KaggleError('Скачивание прервалось. Повторите загрузку.', 502)
    except HTTPError as error:
        code = error.code
        error.close()
        messages = {401: 'Kaggle требует API-токен. Укажите его и повторите загрузку.',
                    403: 'Нет доступа. Проверьте токен и примите условия датасета на Kaggle.',
                    404: 'Датасет не найден или недоступен этому аккаунту.',
                    429: 'Kaggle ограничил запросы. Повторите позже.'}
        raise KaggleError(messages.get(code, 'Kaggle временно недоступен.'), code if code in messages else 502) from None
    except (TimeoutError, URLError):
        raise KaggleError('Не удалось скачать датасет. Проверьте соединение и повторите.', 502) from None


def archive_members(archive):
    entries = archive.infolist()
    if len(entries) > MAX_FILES or sum(item.file_size for item in entries) > MAX_UNPACKED:
        raise KaggleError('Датасет превышает лимит: 10 000 записей или 2 ГиБ содержимого.', 413)
    names = set()
    files = []
    for item in entries:
        name = item.filename
        if (len(name) > 1000 or name in names or name.startswith('/') or '\\' in name or
                '..' in PurePosixPath(name).parts or any(ord(c) < 32 for c in name) or
                item.flag_bits & 1 or (item.external_attr >> 16) & 0o170000 == 0o120000):
            raise KaggleError('Архив содержит неподдерживаемые имена, ссылки или зашифрованные файлы.', 502)
        names.add(name)
        if not item.is_dir():
            files.append({'name': name, 'size': item.file_size})
    return files


def local_files(handle):
    path = archive_path(handle)
    if not path.is_file():
        return {'status': 'missing', 'dataset': handle}
    try:
        with zipfile.ZipFile(path) as archive:
            files = archive_members(archive)
    except (zipfile.BadZipFile, OSError):
        raise KaggleError('Не удалось прочитать локальный архив датасета.', 502) from None
    return {'status': 'ready', 'dataset': handle, 'files': files, 'artifact': artifact('dataset', 'kaggle', handle),
            'path': str(path.relative_to(ROOT)), 'size': path.stat().st_size}


def run_download(handle, token):
    def progress(count, total):
        with LOCK:
            JOBS[handle].update(bytes=count, total=total)
    try:
        path = archive_path(handle)
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='.download-', dir=path.parent) as staging:
            temporary = Path(staging) / 'dataset.zip'
            download_archive(handle, token, temporary, progress)
            with zipfile.ZipFile(temporary) as archive:
                archive_members(archive)
            archive_path(handle)  # Recheck before publishing the completed archive.
            os.replace(temporary, path)
        with LOCK:
            JOBS.pop(handle, None)
    except Exception as error:
        # No upstream URLs, tokens or exception details are exposed to browser/logs.
        message = str(error) if isinstance(error, KaggleError) else (
            'Kaggle не вернул корректный ZIP-архив. Проверьте доступ к датасету и API-токен.'
            if isinstance(error, zipfile.BadZipFile) else 'Не удалось сохранить датасет. Проверьте свободное место и повторите.')
        with LOCK:
            JOBS[handle] = {'status': 'error', 'error': message}


def request(body, action):
    allowed = {'dataset', 'token'} if action == 'download' else {'dataset', 'file'} if action == 'preview' else {'dataset'}
    if set(body) - allowed:
        raise KaggleError('Неизвестные параметры Kaggle.')
    handle = dataset_handle(body.get('dataset'))
    if action == 'preview':
        return preview(handle, body.get('file'))
    with LOCK:
        job = JOBS.get(handle)
        if job and (action != 'download' or job['status'] == 'downloading'):
            return dict(job, dataset=handle)
        result = local_files(handle)
        if result['status'] == 'ready' or action == 'files':
            return result
        token = body.get('token', '')
        if not isinstance(token, str):
            raise KaggleError('Некорректный API-токен Kaggle.')
        token = token.strip() or (os.environ.get('KAGGLE_API_TOKEN', '').strip() if ALLOW_ENVIRONMENT else '')
        if token and not re.fullmatch(r'[!-~]{1,2048}', token):
            raise KaggleError('Некорректный API-токен Kaggle.')
        if any(job['status'] == 'downloading' for job in JOBS.values()):
            raise KaggleError('Уже скачивается другой датасет. Дождитесь завершения.', 409)
        if len(JOBS) >= 64:
            JOBS.clear()  # Only failed jobs remain here; completed files live on disk.
        JOBS[handle] = {'status': 'downloading', 'bytes': 0, 'total': 0}
        threading.Thread(target=run_download, args=(handle, token), daemon=True).start()
        return dict(JOBS[handle], dataset=handle)


def preview(handle, name):
    if not isinstance(name, str) or len(name) > 1000:
        raise KaggleError('Выберите файл датасета.')
    try:
        with zipfile.ZipFile(archive_path(handle)) as archive:
            if name not in {item['name'] for item in archive_members(archive)}:
                raise KaggleError('Файл не найден в датасете.', 404)
            suffix = PurePosixPath(name).suffix.lower()
            if suffix not in ('.csv', '.tsv', '.txt', '.md', '.json', '.jsonl', '.log', '.xml', '.yaml', '.yml'):
                return {'kind': 'unsupported', 'message': 'Для этого формата доступен только размер файла. Откройте локальный ZIP для работы с ним.'}
            with archive.open(name) as source:
                raw = source.read(PREVIEW_BYTES + 1)
    except (zipfile.BadZipFile, OSError, RuntimeError, NotImplementedError):
        raise KaggleError('Не удалось прочитать файл из локального архива.', 422) from None
    truncated = len(raw) > PREVIEW_BYTES
    content = raw[:PREVIEW_BYTES].decode('utf-8-sig', errors='replace')
    if suffix in ('.csv', '.tsv'):
        try:
            delimiter = '\t' if suffix == '.tsv' else ','
            if suffix == '.csv':
                try:
                    delimiter = csv.Sniffer().sniff(content[:8192], delimiters=',;\t|').delimiter
                except csv.Error:
                    pass
            rows = []
            for row in csv.reader(io.StringIO(content), delimiter=delimiter):
                if len(rows) == 21:
                    truncated = True
                    break
                if len(row) > 30 or any(len(cell) > 500 for cell in row):
                    truncated = True
                rows.append([cell[:500] for cell in row[:30]])
            return {'kind': 'table', 'rows': rows, 'truncated': truncated}
        except csv.Error:
            pass
    return {'kind': 'text', 'text': content, 'truncated': truncated}

