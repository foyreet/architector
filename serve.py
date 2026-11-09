"""Serve the standalone editor. Python standard library only."""

import argparse
import json
import math
import os
import re
import socket
import sqlite3
import kaggle_data
import huggingface_models
import data_preview
import data_catalog
import personal_blocks
import analysis_tools
import experiment_queue
import resource_store
import gpu_compute
import model_registry
import python_blocks
import ml_operations
import block_contracts
import pipeline_runner
import project_store
import subgraphs
import local_workspace as community
import whiteboard
import design_documents
import app_config
import architect_mcp
import codex_chat
from http.cookies import SimpleCookie
from urllib.error import HTTPError, URLError
from urllib.request import Request, HTTPRedirectHandler, build_opener
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer as StandardThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qsl, quote, urlsplit

ROOT = Path(__file__).resolve().parent


class ThreadingHTTPServer(StandardThreadingHTTPServer):
    # HTTP/2 browsers request the editor assets together through the reverse proxy.
    # Python 3.10 defaults to a backlog of five, which drops bursts before accept().
    request_queue_size = 128


ASSETS = {
    '/local.css': ('local.css', 'text/css'),
    '/ai-connection.js': ('ai-connection.js', 'text/javascript'),
    '/design-chat.js': ('design-chat.js', 'text/javascript'),
    '/design-chat.css': ('design-chat.css', 'text/css'),
    '/design-docs.html': ('design-docs.html', 'text/html'),
    '/design-docs.js': ('design-docs.js', 'text/javascript'),
    '/design-docs.css': ('design-docs.css', 'text/css'),
    '/board.html': ('board.html', 'text/html'),
    '/board.js': ('board.js', 'text/javascript'),
    '/board.css': ('board.css', 'text/css'),
    '/board-pdf.js': ('board-pdf.js', 'text/javascript'),
    '/vendor/marked-18.1.1.js': ('vendor/marked-18.1.1.js', 'text/javascript'),
    '/chat-markdown.js': ('chat-markdown.js', 'text/javascript'),
    '/codex-chat.js': ('codex-chat.js', 'text/javascript'),
    '/codex-chat.css': ('codex-chat.css', 'text/css'),
    '/': ('architecture.html', 'text/html'),
    '/architecture.html': ('architecture.html', 'text/html'),
    '/architecture.css': ('architecture.css', 'text/css'),
    '/architecture.js': ('architecture.js', 'text/javascript'),
    '/python-workbench.js': ('python-workbench.js', 'text/javascript'),
    '/experiments.js': ('experiments.js', 'text/javascript'),
    '/project-insights.js': ('project-insights.js', 'text/javascript'),
    '/pipeline-debug.js': ('pipeline-debug.js', 'text/javascript'),
    '/lab-tools.js': ('lab-tools.js', 'text/javascript'),
    '/experiment-wizard.js': ('experiment-wizard.js', 'text/javascript'),
    '/training-console.js': ('training-console.js', 'text/javascript'),
    '/model-registry.js': ('model-registry.js', 'text/javascript'),
    '/discussions.js': ('discussions.js', 'text/javascript'),
    '/workspace-navigation.js': ('workspace-navigation.js', 'text/javascript'),
    '/community.js': ('community.js', 'text/javascript'),
    '/learning.js': ('learning.js', 'text/javascript'),
    '/learning.css': ('learning.css', 'text/css'),
    '/design-system.css': ('design-system.css', 'text/css'),
    '/device-ui.js': ('device-ui.js', 'text/javascript'),
    '/mobile-workspace.js': ('mobile-workspace.js', 'text/javascript'),
    '/mobile-workspace.css': ('mobile-workspace.css', 'text/css'),
    '/ios.css': ('ios.css', 'text/css'),
    '/android.css': ('android.css', 'text/css'),
    '/block-contracts.js': ('block-contracts.js', 'text/javascript'),
}


class ApiError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def upstream_error(code):
    messages = {
        400: 'OpenRouter отклонил параметры. Проверьте модель, длину промпта и лимит ответа.',
        401: 'OpenRouter не принял API-ключ. Проверьте ключ в настройках подключения.',
        402: 'Недостаточно средств или исчерпан лимит ключа OpenRouter.',
        403: 'OpenRouter запретил запрос. Проверьте доступ к модели и ограничения аккаунта.',
        404: 'Модель или маршрут не найдены. Обновите каталог OpenRouter.',
        408: 'OpenRouter не успел ответить. Автоматический повтор не выполнялся.',
        429: 'Превышен лимит запросов OpenRouter. Повторите позже.',
    }
    return ApiError(messages.get(code, 'OpenRouter временно недоступен или вернул ошибку провайдера. Автоматический повтор не выполнялся.'),
                    code if code in messages else 502)


def provider_request(path, key='', payload=None):
    # Fixed origin and no redirects: a diagram cannot change the destination of a key.
    headers = {'Accept': 'application/json', 'Content-Type': 'application/json', 'X-OpenRouter-Title': 'Architect'}
    if key:
        headers['Authorization'] = 'Bearer ' + key
    request = Request('https://openrouter.ai/api/v1/' + path,
                      data=json.dumps(payload).encode() if payload is not None else None,
                      headers=headers)
    try:
        with build_opener(NoRedirect()).open(request, timeout=90 if payload else 20) as response:
            data = response.read(8 * 1024 * 1024 + 1)
        if len(data) > 8 * 1024 * 1024:
            raise ApiError('Ответ OpenRouter слишком большой.', 502)
        value = json.loads(data)
    except HTTPError as error:
        code = error.code
        error.close()
        raise upstream_error(code) from None
    except (TimeoutError, socket.timeout):
        raise ApiError('Время ожидания OpenRouter истекло. Запрос мог быть обработан; автоматический повтор не выполнялся.', 504) from None
    except URLError:
        raise ApiError('Не удалось подключиться к OpenRouter. Проверьте интернет-соединение.', 502) from None
    except (ValueError, UnicodeError, RecursionError):
        raise ApiError('OpenRouter вернул некорректный ответ.', 502) from None
    if not isinstance(value, dict):
        raise ApiError('OpenRouter вернул некорректный ответ.', 502)
    if 'error' in value:
        error = value['error']
        code = error.get('code') if isinstance(error, dict) else None
        raise upstream_error(code if isinstance(code, int) else 502)
    return value


def api_key(body, required=True, allow_environment=True):
    key = body.get('api_key', '')
    if not isinstance(key, str):
        raise ApiError('Некорректный API-ключ.')
    key = key.strip() or (os.environ.get('OPENROUTER_API_KEY', '').strip() if allow_environment else '')
    if not key:
        if required:
            raise ApiError('Укажите API-ключ в подключении OpenRouter.', 401)
        return ''
    if len(key) > 512 or not re.fullmatch(r'[!-~]+', key):
        raise ApiError('Некорректный формат API-ключа.')
    return key


def chat_payload(body):
    if set(body) - {'api_key', 'model', 'prompt', 'system', 'max_tokens', 'temperature'}:
        raise ApiError('Неизвестные параметры запроса.')
    model = body.get('model')
    prompt = body.get('prompt')
    system = body.get('system', '')
    if not isinstance(model, str) or not re.fullmatch(r'[a-zA-Z0-9~][a-zA-Z0-9_./:~@+-]{0,159}', model):
        raise ApiError('Укажите ID модели из каталога OpenRouter.')
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 32000:
        raise ApiError('Промпт должен содержать от 1 до 32000 символов.')
    if not isinstance(system, str) or len(system) > 16000:
        raise ApiError('Системная инструкция должна быть не длиннее 16000 символов.')
    limit = body.get('max_tokens', 1024)
    temperature = body.get('temperature', 0.7)
    if type(limit) is not int or not 1 <= limit <= 16384:
        raise ApiError('Лимит ответа должен быть целым числом от 1 до 16384 токенов.')
    if type(temperature) not in (int, float) or not math.isfinite(temperature) or not 0 <= temperature <= 2:
        raise ApiError('Температура должна быть числом от 0 до 2.')
    messages = ([{'role': 'system', 'content': system}] if system.strip() else [])
    messages.append({'role': 'user', 'content': prompt})
    return {'model': model, 'messages': messages, 'temperature': temperature, 'max_tokens': limit, 'stream': False}


def completion(body, allow_environment=True):
    payload = chat_payload(body)
    key = api_key(body, allow_environment=allow_environment)
    value = provider_request('chat/completions', key, payload)
    try:
        choice = value['choices'][0]
        message = choice['message']
        content = message.get('content')
        if content is None and isinstance(message.get('refusal'), str):
            content = message['refusal']
        if not isinstance(content, str):
            raise ValueError()
        reason = choice.get('finish_reason')
    except (KeyError, IndexError, TypeError, ValueError):
        raise ApiError('Модель не вернула текстовый ответ. Выберите текстовую модель или увеличьте лимит ответа.', 502) from None
    if reason == 'error' or (not content.strip() and reason != 'length'):
        raise ApiError('Модель не вернула текстовый ответ. Проверьте модель и лимит токенов.', 502)
    usage = value.get('usage')
    usage = usage if isinstance(usage, dict) else {}
    safe_usage = {}
    for name in ('prompt_tokens', 'completion_tokens', 'total_tokens', 'cost'):
        number = usage.get(name)
        if type(number) in (int, float) and math.isfinite(number) and number >= 0:
            safe_usage[name] = number
    return {'text': content, 'model': value.get('model') if isinstance(value.get('model'), str) else payload['model'],
            'finish_reason': reason if isinstance(reason, str) else '', 'usage': safe_usage}


def models(body, allow_environment=True):
    value = provider_request('models', api_key(body, required=False, allow_environment=allow_environment))
    if not isinstance(value.get('data'), list):
        raise ApiError('Не удалось прочитать каталог OpenRouter.', 502)
    result = []
    for item in value['data']:
        if not isinstance(item, dict) or not isinstance(item.get('id'), str):
            continue
        architecture = item.get('architecture') or {}
        if not isinstance(architecture, dict):
            continue
        modalities = architecture.get('output_modalities', ['text'])
        if not isinstance(modalities, list) or 'text' not in modalities:
            continue
        result.append({'id': item['id'], 'name': item.get('name') if isinstance(item.get('name'), str) else item['id']})
    return {'models': result}


class Handler(BaseHTTPRequestHandler):
    def known_host(self):
        port = self.server.server_port
        public_origin = getattr(self.server, 'public_origin', '')
        hosts = {urlsplit(public_origin).netloc} if public_origin else {f'127.0.0.1:{port}', f'localhost:{port}'}
        host = self.headers.get('Host', '')
        if host not in hosts:
            raise ApiError('Недопустимый адрес сервера.', 403)
        return public_origin, host

    def local_request(self):
        public_origin, host = self.known_host()
        origin = self.headers.get('Origin')
        if origin is not None and origin != (public_origin or 'http://' + host):
            raise ApiError('Запросы разрешены только из этого редактора.', 403)
        if self.headers.get('Sec-Fetch-Site') not in (None, 'same-origin', 'none') and not self.page_navigation():
            raise ApiError('Запросы разрешены только из этого редактора.', 403)

    def page_navigation(self):
        """A link on another site may open the static page itself; the API stays same-origin."""
        return (self.command == 'GET' and urlsplit(self.path).path in ('/', '/architecture.html', '/board.html', '/design-docs.html') and
                self.headers.get('Sec-Fetch-Mode') == 'navigate' and self.headers.get('Sec-Fetch-Dest') == 'document')

    def send_json(self, value, status=200):
        data = json.dumps(value, ensure_ascii=False, allow_nan=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        if status == 401 and urlsplit(self.path).path == '/mcp':
            self.send_header('WWW-Authenticate', 'Bearer realm="architect"')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(data)

    def send_page(self, html, status=200, policy="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"):
        data = html.encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        # Not no-referrer: with it the browser posts the entry form with Origin: null.
        self.send_header('Referrer-Policy', 'same-origin')
        self.send_header('Content-Security-Policy', policy)
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        if urlsplit(self.path).path == '/mcp':
            return self.handle_mcp()
        try:
            self.local_request()
            path = urlsplit(self.path).path
            if not path.startswith(('/api/community/', '/api/boards/', '/api/design-documents/')) and path not in ('/api/codex/config', '/api/codex/configure', '/api/codex/test', '/api/local/info', '/api/codex/status', '/api/codex/login', '/api/codex/logout', '/api/codex/history', '/api/codex/send', '/api/codex/clear', '/api/codex/proposal', '/api/codex/models', '/api/codex/upload', '/api/codex/remove-attachment', '/api/codex/design-get', '/api/codex/design-attach', '/api/codex/design-update', '/api/codex/design-remove', '/api/openrouter/chat', '/api/openrouter/models',
                            '/api/kaggle/download', '/api/kaggle/files', '/api/kaggle/preview',
                            '/api/huggingface/info', '/api/huggingface/download', '/api/huggingface/status',
                            '/api/series/preview', '/api/series/start', '/api/series/list', '/api/series/get', '/api/series/cancel', '/api/series/resume',
                            '/api/lab/analyze', '/api/lab/predict', '/api/lab/predictions', '/api/lab/model-info', '/api/resources/status', '/api/resources/asset', '/api/resources/pin', '/api/resources/unpin', '/api/resources/delete-prediction',
                            '/api/resources/cleanup-preview', '/api/resources/cleanup', '/api/resources/delete-run',
                            '/api/gpu/list', '/api/gpu/register', '/api/gpu/select', '/api/gpu/revoke', '/api/gpu/share', '/api/gpu/policy', '/api/gpu/drain',
                            '/api/wizard/inspect', '/api/wizard/preview', '/api/wizard/create',
                            '/api/compute/options', '/api/pipelines/monitor', '/api/pipelines/resume-training',
                            '/api/models/list', '/api/models/register', '/api/models/best', '/api/models/compare', '/api/models/endpoints',
                            '/api/models/endpoint-create', '/api/models/endpoint-revoke', '/api/models/endpoint-delete',
                            '/api/blocks/execute', '/api/blocks/result', '/api/ml/export', '/api/data/preview', '/api/data/catalog', '/api/blocks/personal-list', '/api/blocks/personal-create', '/api/code/examples', '/api/code/test', '/api/code/export',
                            '/api/practice/open', '/api/practice/state', '/api/practice/submit', '/api/practice/resend',
                            '/api/pipelines/debug-preview', '/api/pipelines/validate', '/api/pipelines/start', '/api/pipelines/runs',
                            '/api/pipelines/run', '/api/pipelines/step', '/api/pipelines/cancel',
                            '/api/pipelines/experiments', '/api/pipelines/compare', '/api/pipelines/experiment',
                            '/api/pipelines/overview', '/api/pipelines/assets', '/api/pipelines/asset',
                            '/api/projects/tutorial', '/api/projects/list', '/api/projects/get', '/api/projects/create', '/api/projects/save',
                            '/api/projects/export', '/api/projects/import', '/api/subgraphs/pack', '/api/subgraphs/unpack', '/api/subgraphs/normalize'):
                raise ApiError('Маршрут не найден.', 404)
            if self.headers.get('X-Architect-Request') != '1' or self.headers.get_content_type() != 'application/json':
                raise ApiError('Ожидается JSON-запрос из редактора.', 403)
            if self.headers.get('Transfer-Encoding'):
                raise ApiError('Неподдерживаемый формат запроса.')
            size = int(self.headers.get('Content-Length', '0'))
            limit = 1024 * 1024 if path.startswith('/api/design-documents/') else 32 * 1024 * 1024 if path.startswith('/api/projects/') or path == '/api/codex/upload' else 4 * 1024 * 1024 if path.startswith(('/api/pipelines/', '/api/subgraphs/', '/api/code/', '/api/data/', '/api/lab/', '/api/compute/', '/api/wizard/', '/api/blocks/personal-')) else 256 * 1024
            if not 0 < size <= limit:
                raise ApiError('Слишком большой или пустой запрос.', 413)
            self.connection.settimeout(100)
            body = json.loads(self.rfile.read(size))
            if not isinstance(body, dict):
                raise ApiError('Ожидается JSON-объект.')
            hub = community.Community()
            token = ''
            user = hub.session(token)
            expected_account = self.headers.get('X-Architect-Account')
            if (user and expected_account is not None and expected_account != user['id'] and
                    path not in ('/api/community/session', '/api/community/login', '/api/community/register')):
                raise ApiError('Аккаунт изменился в другой вкладке. Обновите страницу перед продолжением.', 409)
            if path.startswith('/api/community/'):
                if path == '/api/community/session':
                    self.send_json({'enabled': False, 'local': True, 'user': dict(community.LOCAL_USER), 'registration_open': False})
                    return
                raise ApiError('Каталог сообщества и аккаунты отсутствуют в локальной версии.', 404)
            if path.startswith(('/api/practice/', '/api/models/', '/api/gpu/')) or path in ('/api/projects/tutorial', '/api/code/examples'):
                raise ApiError('Эта функция отсутствует в локальной версии.', 404)
            if path.startswith('/api/design-documents/'):
                self.send_json(design_documents.request(hub, user, body, path.rsplit('/', 1)[1]))
                return
            if path.startswith('/api/boards/'):
                self.send_json(whiteboard.request(hub, user, body, path.rsplit('/', 1)[1]))
                return
            context = community.private_context(self.server, hub, user, completion, kaggle_data, huggingface_models, pipeline_runner)
            if path == '/api/local/info':
                self.send_json({'data_dir': str(hub.root), 'mode': 'local', 'mcp_url': 'http://' + self.headers['Host'] + '/mcp'})
                return
            if path.startswith('/api/codex/'):
                result = codex_chat.request(context.root, user, body, path.rsplit('/', 1)[1], hub=hub)
            elif path.startswith('/api/wizard/'):
                import experiment_wizard
                result = experiment_wizard.request(context.kaggle.ROOT,body,path.rsplit('/',1)[1])
            elif path.startswith('/api/models/'):
                result = model_registry.manage(context, body, path.rsplit('/', 1)[1])
                if path.endswith('/endpoints') and (experiment_queue.active(self.server) or ml_operations.WORKER_LOCK.locked()):
                    for endpoint in result['endpoints']:
                        if endpoint['available']: endpoint.update(available=False,reason='Сервер занят другим запуском. Повторите запрос позже.')
            elif path == '/api/compute/options':
                source = body.get('diagram')
                if body.get('project_id'): source = project_store.ProjectStore(context.root).get(body['project_id'])['diagram']
                result = gpu_compute.broker().manage(context.kaggle.ROOT, {}, 'list')
                result.update(needs_gpu=pipeline_runner.uses_gpu(source,context.kaggle.ROOT), cpu_busy=experiment_queue.active(self.server) or ml_operations.WORKER_LOCK.locked())
            elif path.startswith('/api/gpu/'):
                result = gpu_compute.broker().manage(context.kaggle.ROOT, body, path.rsplit('/', 1)[1])
            elif path.startswith('/api/series/'):
                result = experiment_queue.request(self.server, context, body, path.rsplit('/', 1)[1])
            elif path.startswith('/api/resources/'):
                result = resource_store.request(self.server, context, body, path.rsplit('/', 1)[1])
            elif path == '/api/lab/model-info':
                ref = body.get('artifact', {})
                if not isinstance(ref, dict): raise ApiError('Выберите сохранённый классификатор.')
                if ref.get('kind') not in ('trained_model', 'model_bundle'): raise ApiError('Выберите сохранённый классификатор.')
                model = ml_operations.load(context.kaggle.ROOT, ref, ref['kind'])
                if ref['kind'] == 'model_bundle': model = model['model']
                result = {k: model.get(k) for k in ('format', 'features', 'target', 'classes', 'versions')}
            elif path == '/api/lab/predictions':
                result = analysis_tools.prediction_list(context)
            elif path == '/api/lab/predict':
                with pipeline_runner.CREATION_LOCK:
                    if experiment_queue.active(self.server) or ml_operations.WORKER_LOCK.locked(): raise ApiError('Сервер выполняет вычисления. Дождитесь завершения текущего запуска.', 409)
                    self.server.lab_inference = True
                try: result = analysis_tools.predict(context, body)
                finally:
                    with pipeline_runner.CREATION_LOCK: self.server.lab_inference = False
            elif path == '/api/lab/analyze':
                def history(action, fields):
                    if body.get('project_id'): fields = dict(fields, project_id=body['project_id'])
                    return context.pipeline.request(context.server, fields, action, context.completion, context.kaggle, context.huggingface)
                if 'csv' in body: rows = analysis_tools.read_csv(body['csv'], body.get('separator', ','))
                else:
                    resolver = data_preview.Resolver(body, context.kaggle, history)
                    node = resolver.nodes.get(body.get('node_id'))
                    if not node: raise ApiError('Выберите источник данных.')
                    rows = resolver.outputs(node['id'])['rows'] if node['block']['kind'] == 'csv' else resolver.inputs(node['id'])['inputs'].get('rows')
                result = analysis_tools.analyze(rows, body.get('target', ''))
            elif path == '/api/blocks/personal-list':
                result = personal_blocks.listing(context.root)
            elif path == '/api/blocks/personal-create':
                result = personal_blocks.create(context.root, body)
            elif path == '/api/data/catalog':
                result = data_catalog.listing(context.root)
            elif path in ('/api/data/preview', '/api/code/test'):
                def history(action, fields):
                    if body.get('project_id'): fields = dict(fields, project_id=body['project_id'])
                    return context.pipeline.request(context.server, fields, action, context.completion, context.kaggle, context.huggingface)
                if path == '/api/data/preview':
                    result = data_preview.preview(body, context.kaggle, history)
                else:
                    resolver = data_preview.Resolver(body, context.kaggle, history)
                    block = resolver.inputs(body.get('node_id'))
                    if block['kind'] != 'python_code': raise ApiError('Выберите Python-блок.')
                    result = python_blocks.execute(block, context.kaggle.ROOT)
            elif path == '/api/code/export':
                result = ml_operations.load(context.kaggle.ROOT, body.get('artifact'), 'python_data')
            elif path == '/api/ml/export':
                result = ml_operations.load(context.kaggle.ROOT, body.get('artifact'), 'model_bundle')
            elif path.startswith('/api/projects/'):
                result = project_store.request(body, path.rsplit('/', 1)[1], root=context.root)
            elif path.startswith('/api/subgraphs/'):
                result = subgraphs.request(body, path.rsplit('/', 1)[1])
            elif path.startswith('/api/pipelines/'):
                with pipeline_runner.CREATION_LOCK:
                    if path.endswith(('/start', '/resume-training')):
                        if getattr(self.server, 'lab_inference', False): raise ApiError('Сервер выполняет предсказания. Дождитесь завершения.', 409)
                    result = context.pipeline.request(context.server, body, path.rsplit('/', 1)[1], context.completion, context.kaggle, context.huggingface)
            elif path.startswith('/api/blocks/'):
                result = block_contracts.execute(body, context.completion, context.kaggle, context.huggingface, poll=path.endswith('/result'))
            elif path.startswith('/api/kaggle/'):
                result = context.kaggle.request(body, path.rsplit('/', 1)[1])
            elif path.startswith('/api/huggingface/'):
                result = context.huggingface.request(body, path.rsplit('/', 1)[1])
            else:
                result = context.completion(body) if path.endswith('/chat') else models(body, allow_environment=user is None or user['primary'])
            self.send_json(result)
        except (ApiError, kaggle_data.KaggleError, huggingface_models.HubError, block_contracts.ContractError) as error:
            self.send_json({'error': str(error)}, error.status)
        except (ValueError, UnicodeError, RecursionError):
            self.send_json({'error': 'Некорректный JSON-запрос.'}, 400)
        except sqlite3.Error:
            self.send_json({'error': 'Каталог недоступен. Проверьте свободное место и права на локальное хранилище.'}, 503)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except TimeoutError:
            self.close_connection = True

    def handle_mcp(self):
        try:
            self.local_request()
            hub = community.Community()
            user = dict(community.LOCAL_USER)
            if self.command != 'POST':
                self.send_response(405); self.send_header('Allow', 'POST'); self.send_header('Content-Length', '0'); self.end_headers()
                return
            protocol = self.headers.get('MCP-Protocol-Version')
            if protocol is not None and protocol not in architect_mcp.PROTOCOLS:
                raise ApiError('Неподдерживаемая версия MCP.', 400)
            if self.headers.get('Transfer-Encoding') or self.headers.get_content_type() != 'application/json':
                raise ApiError('Ожидается JSON с Content-Length.', 400)
            accept = self.headers.get('Accept', '')
            if 'application/json' not in accept or 'text/event-stream' not in accept:
                raise ApiError('Accept должен включать application/json и text/event-stream.', 406)
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 4 * 1024 * 1024: raise ApiError('Лимит MCP-запроса — 4 МиБ.', 413)
            self.connection.settimeout(30)
            try:
                message = json.loads(self.rfile.read(length))
            except (ValueError, UnicodeError, RecursionError):
                self.send_json({'jsonrpc': '2.0', 'id': None, 'error': {'code': -32700, 'message': 'Parse error'}}, 400)
                return
            origin = getattr(self.server, 'public_origin', '') or 'http://' + self.headers['Host']
            result = architect_mcp.rpc(hub, user, message, origin)
            if result is None:
                self.send_response(202); self.send_header('Content-Length', '0'); self.end_headers()
            else: self.send_json(result)
        except (ApiError, block_contracts.ContractError) as exc:
            self.send_json({'error': str(exc)}, exc.status)
        except (ValueError, UnicodeError, RecursionError):
            self.send_json({'error': 'Некорректный запрос MCP.'}, 400)
        except (sqlite3.Error, OSError):
            self.send_json({'error': 'MCP временно недоступен.'}, 503)

    def do_DELETE(self):
        if urlsplit(self.path).path == '/mcp': return self.handle_mcp()
        self.send_error(405)

    def do_GET(self):
        if urlsplit(self.path).path == '/mcp': return self.handle_mcp()
        try:
            self.local_request()
        except ApiError as error:
            self.send_json({'error': str(error)}, error.status)
            return
        if urlsplit(self.path).path == '/api/blocks/contracts':
            self.send_json(block_contracts.CATALOG)
            return
        if urlsplit(self.path).path == '/api/openrouter/status':
            hub = community.Community()
            user = hub.session('')
            if (getattr(self.server, 'public_origin', '') or hub.enabled()) and user is None:
                self.send_json({'error': 'Войдите в аккаунт.'}, 401)
                return
            self.send_json({'server_key': (user is None or user['primary']) and bool(os.environ.get('OPENROUTER_API_KEY', '').strip())})
            return
        asset = ASSETS.get(urlsplit(self.path).path)
        if asset is None:
            self.send_error(404)
            return
        filename, mime = asset
        body = (ROOT / 'annotator' / filename).read_bytes()
        self.send_response(200)
        self.send_header('Content-Type', mime + '; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; connect-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(body)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8770)
    args = parser.parse_args()
    with ThreadingHTTPServer(('0.0.0.0' if os.environ.get('ARCHITECTOR_CONTAINER') == '1' else '127.0.0.1', args.port), Handler) as server:
        app_config.configure_server(server)
        origin = server.public_origin or f'http://127.0.0.1:{server.server_port}'
        print(f'Architect: {origin}/architecture.html', flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == '__main__':
    main()

