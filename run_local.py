"""One-command local startup; dependencies stay inside this checkout."""
from pathlib import Path
import argparse
import hashlib
import os
import subprocess
import sys
import threading
import time
import urllib.request
import venv
import webbrowser

ROOT = Path(__file__).resolve().parent


def prepare():
    if sys.version_info < (3, 11):
        raise SystemExit('Нужен Python 3.11 или новее. Установите его с https://www.python.org/downloads/.')
    env = ROOT / '.venv'
    python = env / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    if not python.exists():
        print('Создаём окружение Python в папке приложения…', flush=True)
        venv.EnvBuilder(with_pip=True).create(env)
    requirements = ['requirements.txt', 'requirements-ml.txt', 'requirements-chat.txt']
    fingerprint = hashlib.sha256(b''.join((ROOT / p).read_bytes() for p in requirements)).hexdigest()
    marker = env / '.architector-dependencies'
    if not marker.exists() or marker.read_text() != fingerprint:
        print('Устанавливаем зависимости. При первом запуске нужен интернет; это может занять несколько минут…', flush=True)
        subprocess.run([str(python), '-m', 'pip', 'install', '-r', str(ROOT / 'requirements.txt')], check=True, cwd=ROOT)
        marker.write_text(fingerprint)
    return python


def main():
    parser = argparse.ArgumentParser(description='Запустить Архитектор локально')
    parser.add_argument('--port', type=int, default=8770)
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    print('Проверяем Python…', flush=True)
    try: python = prepare()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SystemExit('Не удалось подготовить Python. Проверьте интернет и права на папку приложения, затем повторите запуск.\n' + str(exc))
    env = dict(os.environ)
    env.setdefault('ARCHITECT_DATA_DIR', str(ROOT / 'data'))
    env.pop('ARCHITECT_CODE_SOCKET', None)
    url = f'http://localhost:{args.port}'
    print(f'Запускаем Архитектор: {url}\nДля остановки нажмите Ctrl+C.', flush=True)
    app = subprocess.Popen([str(python), str(ROOT / 'serve.py'), '--port', str(args.port)], cwd=ROOT, env=env)
    def open_browser():
        for _ in range(100):
            if app.poll() is not None: return
            try:
                with urllib.request.urlopen(url + '/api/blocks/contracts', timeout=1): pass
                if app.poll() is None: webbrowser.open(url)
                return
            except OSError: time.sleep(.2)
    if not args.no_browser: threading.Thread(target=open_browser, daemon=True).start()
    try:
        result = app.wait()
        if result: raise SystemExit('Архитектор не запустился. Проверьте сообщение выше; возможно, порт уже занят другим запуском.')
    except KeyboardInterrupt: pass
    finally:
        if app.poll() is None:
            app.terminate()
            try: app.wait(timeout=5)
            except subprocess.TimeoutExpired: app.kill(); app.wait()


if __name__ == '__main__': main()
