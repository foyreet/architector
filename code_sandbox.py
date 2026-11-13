"""Local Python subprocess execution. Resource monitoring is not a security sandbox."""
import json
import os
from pathlib import Path
import queue
import signal
import socketserver
import struct
import subprocess
import sys
import tempfile
import threading
import time

import psutil

LOCK = threading.Lock()
MEMORY_MB = int(os.environ.get('ARCHITECTOR_PYTHON_MEMORY_MB', '0'))


def receive(sock, length):
    chunks = bytearray()
    while len(chunks) < length:
        part = sock.recv(min(65536, length - len(chunks)))
        if not part: raise ValueError('Incomplete request')
        chunks.extend(part)
    return chunks


def validate(payload):
    if not isinstance(payload, dict) or set(payload) != {'code', 'inputs', 'params', 'timeout'}: raise ValueError('Invalid Python request')
    if not isinstance(payload['code'], str) or not 0 < len(payload['code']) <= 64000: raise ValueError('Invalid code')
    if not isinstance(payload['inputs'], dict) or not isinstance(payload['params'], dict): raise ValueError('Inputs and params must be objects')
    if type(payload['timeout']) is not int or not 1 <= payload['timeout'] <= 60: raise ValueError('Invalid timeout')


def memory_usage(process, descendants):
    try:
        parent = psutil.Process(process.pid)
        descendants.update({child.pid: child for child in parent.children(recursive=True)})
        processes = [parent, *descendants.values()]
    except psutil.NoSuchProcess:
        processes = list(descendants.values())
    total = 0
    for child in processes:
        try: total += child.memory_info().rss
        except (psutil.NoSuchProcess, psutil.AccessDenied): pass
    return total


def stop(process, descendants):
    if process is None: return
    if os.name == 'posix':
        try: os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError: pass
    for child in descendants.values():
        try: child.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied): pass
    if process.poll() is None: process.kill()
    process.wait(timeout=5)


def run(payload):
    validate(payload)
    if not LOCK.acquire(blocking=False): return {'error': 'Python-исполнитель занят. Дождитесь завершения запуска.'}
    process = None
    descendants = {}
    finished = threading.Event()
    reader = None
    try:
        # Do not inherit API keys or application configuration into ordinary user code.
        env = {key: value for key, value in os.environ.items() if key in ('PATH', 'LANG', 'SYSTEMROOT', 'WINDIR')}
        env.update(PYTHONIOENCODING='utf-8', OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1')
        with tempfile.TemporaryDirectory(prefix='architector-python-') as work, tempfile.TemporaryFile(mode='w+', encoding='utf-8') as source:
            json.dump(payload, source, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
            source.flush(); source.seek(0)
            process = subprocess.Popen([sys.executable, '-I', str(Path(__file__).with_name('python_runner.py'))],
                stdin=source, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=work, env=env,
                start_new_session=os.name == 'posix')
            parts = queue.Queue(maxsize=8)
            def read_output():
                try:
                    while not finished.is_set():
                        part = os.read(process.stdout.fileno(), 65536)
                        while not finished.is_set():
                            try: parts.put(part, timeout=.1); break
                            except queue.Full: pass
                        if not part: break
                except OSError: pass
            reader = threading.Thread(target=read_output, daemon=True); reader.start()
            chunks = bytearray(); deadline = time.monotonic() + payload['timeout']
            try:
                while True:
                    if time.monotonic() > deadline: return {'error': 'Превышено время выполнения Python-блока.'}
                    if MEMORY_MB > 0 and memory_usage(process, descendants) > MEMORY_MB * 1024 * 1024:
                        return {'error': f'Python-блок превысил лимит памяти {MEMORY_MB} МиБ.'}
                    try: part = parts.get(timeout=.1)
                    except queue.Empty: continue
                    if not part: break
                    chunks.extend(part)
                process.wait(timeout=max(.01, deadline-time.monotonic()))
                if process.returncode: return {'error': 'Процесс Python завершился с ошибкой.', 'logs': bytes(chunks[-8000:]).decode(errors='replace')}
                try: response = json.loads(chunks)
                except (ValueError, UnicodeError, RecursionError): return {'error': 'Код повредил протокол вывода. Используйте print() для журнала и return для результата.'}
                if not isinstance(response, dict): return {'error': 'Некорректный ответ Python-блока.'}
                response['runtime'] = {'executor': 'local-process', 'python': sys.version.split()[0], 'memory_mb': MEMORY_MB,
                    'memory_limit': 'monitored' if MEMORY_MB > 0 else 'none', 'network': True, 'timeout': payload['timeout']}
                return response
            finally:
                finished.set(); stop(process, descendants)
                reader.join(timeout=2); process.stdout.close()
    except subprocess.TimeoutExpired:
        return {'error': 'Превышено время выполнения Python-блока.'}
    except (OSError, subprocess.SubprocessError):
        return {'error': 'Не удалось запустить локальный Python. Перезапустите Архитектор через run_local.py.'}
    finally:
        finished.set()
        if process is not None and process.poll() is None: stop(process, descendants)
        LOCK.release()


class Handler(socketserver.BaseRequestHandler):
    def handle(self):
        self.request.settimeout(10)
        try:
            size = struct.unpack('!I', receive(self.request, 4))[0]
            if size <= 0: raise ValueError('Empty request')
            response = run(json.loads(receive(self.request, size)))
        except (ValueError, OSError, RecursionError): response = {'error': 'Некорректный запрос к среде Python.'}
        raw = json.dumps(response, ensure_ascii=False, allow_nan=False).encode()
        try:
            self.request.sendall(struct.pack('!I', len(raw)))
            self.request.sendall(raw)
        except OSError: pass


class Server(socketserver.ThreadingMixIn, getattr(socketserver, 'UnixStreamServer', socketserver.TCPServer)):
    daemon_threads = True
    request_queue_size = 8

