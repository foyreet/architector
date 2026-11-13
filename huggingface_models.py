"""Hugging Face model metadata and verified local downloads (stdlib only)."""

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import threading
import unicodedata
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request, HTTPRedirectHandler, build_opener
from block_contracts import artifact
from app_config import data_root

ALLOW_ENVIRONMENT = True
ROOT = data_root()
LOCK = threading.RLock()
JOBS = {}


class HubError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def model_id(value):
    if not isinstance(value, str):
        raise HubError('Укажите ID модели или ссылку Hugging Face.')
    value = value.strip()
    if value.startswith('https://'):
        parsed = urlsplit(value)
        if parsed.netloc != 'huggingface.co' or parsed.query or parsed.fragment:
            raise HubError('Укажите ссылку на репозиторий https://huggingface.co/owner/model.')
        value = parsed.path.strip('/')
    parts = value.split('/')
    if (len(parts) not in (1, 2) or parts[0] in ('datasets', 'spaces', 'api') or
            any(not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]{0,95}', part) or
                part.endswith(('.', '-')) or '--' in part or '..' in part for part in parts)):
        raise HubError('Нужен ID модели owner/model. Ссылки на datasets, spaces и отдельные файлы не поддерживаются.')
    return value


def revision_id(value, pinned=False):
    pattern = r'[a-f0-9]{40}' if pinned else r'[A-Za-z0-9_][A-Za-z0-9_./-]{0,159}'
    if not isinstance(value, str) or not re.fullmatch(pattern, value) or any(p in ('', '.', '..') for p in value.split('/')):
        raise HubError('Укажите ветку, тег или полный commit SHA модели.' if not pinned else 'Сначала загрузите список файлов модели, чтобы зафиксировать версию.')
    return value


def filename(value):
    if (not isinstance(value, str) or not value or '\\' in value or ':' in value or
            any(ord(c) < 32 or ord(c) == 127 for c in value) or
            any(p in ('', '.', '..') or p.endswith((' ', '.')) for p in value.split('/'))):
        raise HubError('Репозиторий содержит неподдерживаемый путь файла.', 422)
    return value


def token_value(body):
    token = body.get('token', '')
    if not isinstance(token, str):
        raise HubError('Некорректный токен Hugging Face.')
    token = token.strip() or (os.environ.get('HF_TOKEN', '').strip() if ALLOW_ENVIRONMENT else '')
    if token and not re.fullmatch(r'[!-~]+', token):
        raise HubError('Некорректный токен Hugging Face.')
    return token


class HubRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        parsed = urlsplit(newurl)
        # Resolve may redirect to the Hub's cache or signed LFS/Xet storage.
        hosts = {'huggingface.co', 'cdn-lfs.huggingface.co', 'cdn-lfs.hf.co',
                 'cdn-lfs-us-1.hf.co', 'cdn-lfs-eu-1.hf.co',
                 'cas-bridge.xethub.hf.co', 'transfer.xethub.hf.co'}
        regional_cdn = re.fullmatch(r'[a-z0-9-]+(?:\.[a-z0-9-]+)*\.cdn\.hf\.co', parsed.netloc)
        if parsed.scheme != 'https' or (parsed.netloc not in hosts and not regional_cdn):
            raise HubError('Hugging Face вернул неподдерживаемый адрес скачивания.', 502)
        redirected = super().redirect_request(request, fp, code, msg, headers, newurl)
        if redirected is not None and parsed.netloc != urlsplit(request.full_url).netloc:
            redirected.remove_header('Authorization')
        return redirected


def hub_open(path, token):
    headers = {'User-Agent': 'Architect/1.0', 'Accept-Encoding': 'identity'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    try:
        return build_opener(HubRedirect()).open(Request('https://huggingface.co/' + path, headers=headers), timeout=30)
    except HTTPError as error:
        code = error.code
        error.close()
        messages = {401: 'Hugging Face требует токен с доступом к модели.',
                    403: 'Нет доступа к модели. Проверьте токен и получите доступ на странице модели Hugging Face.',
                    404: 'Модель, версия или файл не найдены. Для приватной модели проверьте токен.',
                    429: 'Hugging Face ограничил запросы. Повторите позже.'}
        raise HubError(messages.get(code, 'Hugging Face временно недоступен.'), code if code in messages else 502) from None
    except (TimeoutError, URLError):
        raise HubError('Не удалось связаться с Hugging Face. Проверьте соединение.', 502) from None


def model_info(repo, revision, token):
    with hub_open('api/models/' + quote(repo, safe='/') + '/revision/' + quote(revision, safe='') + '?blobs=true', token) as response:
        raw = response.read()
    try:
        data = json.loads(raw)
        commit = revision_id(data['sha'], pinned=True)
        siblings = data['siblings']
        if not isinstance(siblings, list):
            raise HubError('Поддерживаются репозитории до 5 000 файлов.', 413)
        files, names = [], set()
        for item in siblings:
            name = filename(item['rfilename'])
            normalized = unicodedata.normalize('NFC', name).casefold()
            if normalized in names:
                raise HubError('Имена файлов модели конфликтуют на локальном диске.', 422)
            names.add(normalized)
            size = item['size']
            if type(size) is not int or size < 0:
                raise ValueError()
            lfs = item.get('lfs')
            digest = lfs['sha256'] if lfs else item['blobId']
            algorithm = 'sha256' if lfs else 'git-sha1'
            if not isinstance(digest, str) or not re.fullmatch(r'[a-f0-9]{64}' if lfs else r'[a-f0-9]{40}', digest):
                raise ValueError()
            files.append({'name': name, 'size': size, 'digest': digest, 'algorithm': algorithm})
        # Catch file/directory collisions before writing anything.
        if any('/'.join(name.split('/')[:i]) in names for name in names for i in range(1, len(name.split('/')))):
            raise HubError('Пути файлов модели конфликтуют.', 422)
        card = data.get('cardData') or {}
        license_name = card.get('license', '') if isinstance(card, dict) else ''
        clean_text = lambda value: value if isinstance(value, str) else ''
        return {'repo': repo, 'commit': commit, 'files': files,
                'pipeline': clean_text(data.get('pipeline_tag')), 'library': clean_text(data.get('library_name')),
                'license': clean_text(license_name), 'gated': bool(data.get('gated'))}
    except (KeyError, TypeError, ValueError, UnicodeError):
        raise HubError('Hugging Face вернул некорректные метаданные модели.', 502) from None


def checked_path(path):
    if not path.is_relative_to(ROOT):
        raise HubError('Недопустимая папка модели.', 403)
    for parent in (path, *path.parents):
        if parent == ROOT:
            break
        if parent.is_symlink():
            raise HubError('Папка модели содержит символическую ссылку.', 403)
    return path


def model_folder(repo, commit):
    # Hash avoids collisions on case-insensitive filesystems, including legacy IDs.
    key = hashlib.sha256(repo.encode()).hexdigest()[:20]
    return checked_path(ROOT / 'workspace' / 'models' / 'huggingface' / key / commit)


def read_manifest(repo, commit):
    folder = model_folder(repo, commit)
    path = checked_path(folder / 'manifest.json')
    if not path.exists():
        return {'repo': repo, 'commit': commit, 'files': []}
    try:
        with path.open('rb') as source:
            raw = source.read()
        data = json.loads(raw)
        if data['repo'] != repo or data['commit'] != commit or not isinstance(data['files'], list):
            raise ValueError()
        for item in data['files']:
            filename(item['name'])
            if type(item['size']) is not int or item['size'] < 0 or type(item['mtime_ns']) is not int:
                raise ValueError()
        return data
    except (OSError, ValueError, KeyError, TypeError):
        raise HubError('Не удалось прочитать локальное описание модели.', 422) from None


def is_cached(folder, item):
    path = checked_path(folder / 'files' / item['name'])
    return path.is_file() and path.stat().st_size == item['size'] and path.stat().st_mtime_ns == item.get('mtime_ns')


def local_status(repo, commit):
    folder = model_folder(repo, commit)
    data = read_manifest(repo, commit)
    files = [{'name': item['name'], 'size': item['size']} for item in data['files'] if is_cached(folder, item)]
    return {'status': 'ready' if files else 'missing', 'repo': repo, 'commit': commit, 'files': files,
            'artifact': artifact('model', 'huggingface', repo, commit) if files else None,
            'path': str((folder / 'files').relative_to(ROOT)) if files else ''}


def download_file(repo, commit, item, token, destination, progress):
    size = item['size']
    digest = hashlib.sha256() if item['algorithm'] == 'sha256' else hashlib.sha1()
    if item['algorithm'] == 'git-sha1':
        digest.update(f'blob {size}\0'.encode())
    count = 0
    path = quote(repo, safe='/') + '/resolve/' + commit + '/' + quote(item['name'], safe='/')
    with hub_open(path, token) as response, destination.open('wb') as output:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            count += len(chunk)
            if count > size:
                raise HubError('Размер файла отличается от метаданных Hugging Face.', 502)
            digest.update(chunk)
            output.write(chunk)
            progress(count)
    if count != size or digest.hexdigest() != item['digest']:
        raise HubError('Файл скачан не полностью или не прошёл проверку контрольной суммы. Повторите загрузку.', 502)


def run_download(repo, commit, names, token):
    key = (repo, commit)
    try:
        info = model_info(repo, commit, token)
        if info['commit'] != commit:
            raise HubError('Hugging Face вернул другую версию модели.', 502)
        by_name = {item['name']: item for item in info['files']}
        if not set(names) <= by_name.keys():
            raise HubError('Выбранный файл отсутствует в этой версии модели.')
        items = [by_name[name] for name in names]
        total = sum(item['size'] for item in items)
        folder = model_folder(repo, commit)
        folder.mkdir(parents=True, exist_ok=True)
        manifest = read_manifest(repo, commit)
        cached = {item['name']: item for item in manifest['files']}
        needed = [item for item in items if not (item['name'] in cached and
                  cached[item['name']].get('digest') == item['digest'] and is_cached(folder, cached[item['name']]))]
        if shutil.disk_usage(folder).free < sum(item['size'] for item in needed):
            raise HubError('Недостаточно свободного места для выбранных файлов.', 507)
        done = sum(item['size'] for item in items if item not in needed)
        with LOCK:
            JOBS[key].update(bytes=done, total=total)
        with tempfile.TemporaryDirectory(prefix='.download-', dir=folder) as staging:
            temporary = Path(staging) / 'file.part'
            for item in needed:
                with LOCK:
                    JOBS[key]['current_file'] = item['name']
                def progress(count):
                    with LOCK:
                        JOBS[key]['bytes'] = done + count
                download_file(repo, commit, item, token, temporary, progress)
                target = checked_path(folder / 'files' / item['name'])
                target.parent.mkdir(parents=True, exist_ok=True)
                os.replace(temporary, checked_path(target))
                cached[item['name']] = dict(item, mtime_ns=target.stat().st_mtime_ns)
                manifest['files'] = list(cached.values())
                meta = Path(staging) / 'manifest.json'
                meta.write_text(json.dumps(manifest, ensure_ascii=False), encoding='utf-8')
                os.replace(meta, checked_path(folder / 'manifest.json'))
                done += item['size']
                progress(0)
        with LOCK:
            JOBS.pop(key, None)
    except Exception as error:
        message = str(error) if isinstance(error, HubError) else (
            'Соединение прервалось. Повторите загрузку; готовые файлы останутся на диске.'
            if isinstance(error, (TimeoutError, URLError, ConnectionError)) else
            'Не удалось сохранить модель. Проверьте свободное место и повторите загрузку.')
        with LOCK:
            JOBS[key] = {'status': 'error', 'error': message}


def request(body, action):
    allowed = {'repo', 'revision', 'token'} if action == 'info' else {'repo', 'commit', 'files', 'token'} if action == 'download' else {'repo', 'commit'}
    if set(body) - allowed:
        raise HubError('Неизвестные параметры Hugging Face.')
    repo = model_id(body.get('repo'))
    if action == 'info':
        try:
            return model_info(repo, revision_id(body.get('revision', 'main')), token_value(body))
        except (TimeoutError, URLError, ConnectionError):
            raise HubError('Не удалось загрузить список файлов Hugging Face. Повторите позже.', 502) from None
    commit = revision_id(body.get('commit'), pinned=True)
    key = (repo, commit)
    if action == 'status':
        with LOCK:
            job = JOBS.get(key)
            result = local_status(repo, commit)
            return dict(result, **job) if job else result
    names = body.get('files')
    if not isinstance(names, list) or not names:
        raise HubError('Выберите файлы модели для скачивания.')
    names = [filename(name) for name in names]
    if len(set(names)) != len(names):
        raise HubError('В списке повторяются файлы.')
    token = token_value(body)
    with LOCK:
        if JOBS.get(key, {}).get('status') == 'downloading':
            raise HubError('Уже скачивается модель. Дождитесь завершения.', 409)
        model_folder(repo, commit)
        JOBS[key] = {'status': 'downloading', 'bytes': 0, 'total': 0, 'current_file': ''}
        threading.Thread(target=run_download, args=(repo, commit, names, token), daemon=True).start()
        return dict(JOBS[key], repo=repo, commit=commit)

