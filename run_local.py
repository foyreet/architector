"""Native local launcher (macOS/Linux). Docker runs only the Python sandbox."""
from pathlib import Path
import os
import socket
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parent

def main():
    if os.name=='nt': raise SystemExit('На Windows используйте docker compose up --build или запуск через WSL2; см. README.')
    os.environ.setdefault('ARCHITECT_DATA_DIR',str(ROOT/'data'))
    data=Path(os.environ['ARCHITECT_DATA_DIR']).resolve();data.mkdir(parents=True,exist_ok=True)
    sock=data/'runner.sock'
    os.environ['ARCHITECT_CODE_SOCKET']=str(sock)
    try:
        subprocess.run(['docker','info'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=True)
        if subprocess.run(['docker','image','inspect','architector-python:local'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode:
            subprocess.run(['docker','build','-t','architector-python:local',str(ROOT/'deploy/python-sandbox')],check=True)
    except (OSError,subprocess.CalledProcessError):
        raise SystemExit('Запустите Docker. Для редактора без Python-блоков можно выполнить python serve.py с ARCHITECT_DATA_DIR, указывающим папку данных.')
    if sock.exists():
        try:
            with socket.socket(socket.AF_UNIX) as s:s.connect(str(sock))
        except OSError:sock.unlink()
        else:raise SystemExit('Локальный исполнитель уже запущен. Используйте существующее приложение.')
    runner=subprocess.Popen([sys.executable,str(ROOT/'code_sandbox.py'),'--socket',str(sock)],cwd=ROOT)
    app=None
    try:
        for _ in range(100):
            if sock.exists():break
            if runner.poll() is not None:raise SystemExit('Не удалось запустить Python-исполнитель.')
            time.sleep(.1)
        app=subprocess.Popen([sys.executable,str(ROOT/'serve.py')],cwd=ROOT)
        app.wait()
    except KeyboardInterrupt:pass
    finally:
        for process in (app,runner):
            if process and process.poll() is None:
                process.terminate()
                try:process.wait(timeout=5)
                except subprocess.TimeoutExpired:process.kill();process.wait()
        sock.unlink(missing_ok=True)

if __name__=='__main__':main()
