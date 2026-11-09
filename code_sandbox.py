"""Fixed Docker broker. No client-selected commands, images, paths or mounts.

The HTTP app talks to its Unix socket and is never granted access to Docker.
"""
import argparse
import json
import os
from pathlib import Path
import selectors
import socketserver
import struct
import subprocess
import tempfile
import threading
import time
import uuid

from data_limits import PYTHON_MESSAGE_BYTES

MAX_BYTES = PYTHON_MESSAGE_BYTES
LOCK = threading.Lock()
IMAGE = 'architector-python:local'
MEMORY = str(max(256, min(65536, int(os.environ.get('ARCHITECTOR_PYTHON_MEMORY_MB', '1024'))))) + 'm'
CPUS = str(max(0.25, min(64, float(os.environ.get('ARCHITECTOR_PYTHON_CPUS', '2')))))


def receive(sock, length):
    chunks = bytearray()
    while len(chunks) < length:
        part = sock.recv(min(65536, length - len(chunks)))
        if not part: raise ValueError('Incomplete request')
        chunks.extend(part)
    return chunks


def validate(payload):
    if not isinstance(payload, dict) or set(payload) != {'code', 'inputs', 'params', 'timeout'}: raise ValueError('Invalid sandbox request')
    if not isinstance(payload['code'], str) or not 0 < len(payload['code']) <= 64000: raise ValueError('Invalid code')
    if not isinstance(payload['inputs'], dict) or not isinstance(payload['params'], dict): raise ValueError('Inputs and params must be objects')
    if type(payload['timeout']) is not int or not 1 <= payload['timeout'] <= 60: raise ValueError('Invalid timeout')


def run(payload):
    validate(payload)
    if not LOCK.acquire(blocking=False): return {'error': 'Изолированная среда занята. Повторите запуск после завершения.'}
    name = 'architect-code-' + uuid.uuid4().hex
    process = None
    try:
        info = subprocess.run(['docker', 'image', 'inspect', IMAGE, '--format', '{{.Id}}'], capture_output=True, timeout=10)
        image = info.stdout.decode().strip()
        if info.returncode or not image.startswith('sha256:'): return {'error': 'Образ Python не установлен. Соберите deploy/python-sandbox.'}
        command = ['docker', 'run', '--rm', '-i', '--pull=never', '--name', name,
                   '--label', 'architect.sandbox=1', '--network=none', '--read-only', '--user=10001:10001', '--cap-drop=ALL',
                   '--security-opt=no-new-privileges', '--pids-limit=64', '--memory='+MEMORY, '--memory-swap='+MEMORY,
                   '--cpus='+CPUS, '--ulimit', 'nofile=128:128', '--ulimit', 'fsize=33554432:33554432',
                   '--tmpfs', '/tmp:rw,noexec,nosuid,size=64m,mode=1777', '--shm-size=16m',
                   '--log-driver=none', image]
        with tempfile.TemporaryFile(mode='w+', encoding='utf-8') as source:
            json.dump(payload, source, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
            source.flush(); source.seek(0)
            process = subprocess.Popen(command, stdin=source, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            chunks = bytearray(); deadline = time.monotonic() + payload['timeout'] + 5
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                while True:
                    if time.monotonic() > deadline: return {'error': 'Превышено время выполнения Python-блока.'}
                    events = selector.select(.2)
                    if not events: continue
                    part = os.read(process.stdout.fileno(), 65536)
                    if not part: break
                    chunks.extend(part)
                    if len(chunks) > MAX_BYTES: return {'error': 'Вывод Python-блока больше 32 МиБ.'}
            process.wait(timeout=5)
            if process.returncode: return {'error': 'Контейнер завершился с ошибкой или превысил лимит памяти.', 'logs': bytes(chunks[-8000:]).decode(errors='replace')}
            try: response = json.loads(chunks)
            except (ValueError, UnicodeError, RecursionError): return {'error': 'Код повредил протокол вывода. Используйте print() для журнала и return для результата.'}
            if not isinstance(response, dict): return {'error': 'Некорректный ответ Python-блока.'}
            response['runtime'] = {'image': image, 'memory_mb': int(MEMORY[:-1]), 'cpus': float(CPUS), 'network': False, 'timeout': payload['timeout']}
            return response
    except (OSError, subprocess.SubprocessError):
        return {'error': 'Изолированная среда Docker недоступна.'}
    finally:
        # Also removes containers when a client exits, the code forks, or a limit fires.
        try: subprocess.run(['docker', 'rm', '-f', name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
        except (OSError, subprocess.SubprocessError): pass
        if process is not None and process.poll() is None:
            process.kill(); process.wait()
        LOCK.release()


class Handler(socketserver.BaseRequestHandler):
    def handle(self):
        self.request.settimeout(10)
        try:
            size = struct.unpack('!I', receive(self.request, 4))[0]
            if not 0 < size <= MAX_BYTES: raise ValueError('Request too large')
            response = run(json.loads(receive(self.request, size)))
        except (ValueError, OSError, RecursionError): response = {'error': 'Некорректный запрос к изолированной среде.'}
        raw = json.dumps(response, ensure_ascii=False, allow_nan=False).encode()
        if len(raw) > MAX_BYTES: raw = b'{"error":"Sandbox response too large"}'
        try:
            self.request.sendall(struct.pack('!I', len(raw)))
            self.request.sendall(raw)
        except OSError: pass


class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True
    request_queue_size = 8


def cleanup():
    result = subprocess.run(['docker', 'ps', '-aq', '--filter', 'label=architect.sandbox=1'], capture_output=True, timeout=10)
    identifiers = result.stdout.decode().split()
    if identifiers:
        subprocess.run(['docker', 'rm', '-f', *identifiers], stdout=subprocess.DEVNULL, timeout=20)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--socket'); parser.add_argument('--cleanup', action='store_true')
    args = parser.parse_args()
    if args.cleanup:
        cleanup(); raise SystemExit(0)
    if not args.socket: parser.error('--socket is required')
    path = Path(args.socket)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists(): path.unlink()
    with Server(str(path), Handler) as server:
        os.chmod(path, 0o660)
        server.serve_forever()

