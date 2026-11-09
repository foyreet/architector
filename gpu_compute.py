"""Local GPU subprocess and bounded FIFO pipeline scheduling."""
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
import hashlib
import hmac
import json
import math
from pathlib import Path
import secrets
import threading
import time
import uuid

from app_config import data_root
from project_store import ProjectStore
import gpu_worker

FORMAT = 'architect.gpu-mlp'
MAX_BYTES = 8 * 1024 * 1024
ONLINE_SECONDS = 30
JOB_SECONDS = 600
EXECUTION = ContextVar('gpu_execution', default=None)
TRAINING = ContextVar('gpu_training', default=None)
PIPELINE_SLOT = threading.Lock()
PIPELINE_ADMISSION = threading.Lock()
PIPELINE_PENDING = {}
SLOT_CONDITION = threading.Condition()
SLOT_WAITERS = []
SLOT_ACTIVE = None


def enter_slot(root, run_id, cancelled):
    global SLOT_ACTIVE
    key = (str(Path(root).resolve()), run_id)
    with SLOT_CONDITION:
        if key not in SLOT_WAITERS:
            SLOT_WAITERS.append(key)
        try:
            while not cancelled.is_set():
                if SLOT_ACTIVE is None and SLOT_WAITERS[0] == key:
                    SLOT_WAITERS.pop(0); SLOT_ACTIVE = key
                    return True
                SLOT_CONDITION.wait(.2)
            return False
        finally:
            if key in SLOT_WAITERS: SLOT_WAITERS.remove(key)
            SLOT_CONDITION.notify_all()


def leave_slot():
    global SLOT_ACTIVE
    with SLOT_CONDITION:
        SLOT_ACTIVE = None; SLOT_CONDITION.notify_all()


def slot_status(root, run_id):
    key = (str(Path(root).resolve()), run_id)
    with SLOT_CONDITION:
        position = SLOT_WAITERS.index(key) + 1 if key in SLOT_WAITERS else None
        return {'queue_position': position,
                'queue_ahead': position - 1 + int(SLOT_ACTIVE is not None) if position is not None else None,
                'running': SLOT_ACTIVE == key}


def admit(root, run_id):
    # Reserve FIFO order before starting the worker thread. All account-specific
    # pipeline modules share this process-wide scheduler.
    scope = str(Path(root).resolve())
    key = (scope, run_id)
    with PIPELINE_ADMISSION, SLOT_CONDITION:
        if key in PIPELINE_PENDING:
            fail('Этот ID запуска уже используется в другом проекте.', 409)
        if len(PIPELINE_PENDING) >= 20 or sum(v == scope for v in PIPELINE_PENDING.values()) >= 2:
            fail('Очередь заполнена: не более двух запусков на этом компьютере, включая выполняющийся. Дождитесь завершения одного из запусков.', 429)
        PIPELINE_PENDING[key] = scope
        SLOT_WAITERS.append(key)
        SLOT_CONDITION.notify_all()


def release(root, run_id):
    key = (str(Path(root).resolve()), run_id)
    with PIPELINE_ADMISSION, SLOT_CONDITION:
        PIPELINE_PENDING.pop(key, None)
        # Also remove a reservation if saving the run or starting its thread failed.
        if key in SLOT_WAITERS:
            SLOT_WAITERS.remove(key)
        SLOT_CONDITION.notify_all()


def fail(message, status=400):
    from block_contracts import ContractError
    raise ContractError(message, status)


def worker_digest():
    return hashlib.sha256(Path(__file__).with_name('gpu_worker.py').read_bytes()).hexdigest()


class Broker:
    """Only a subprocess on this computer; no workers, remote addresses or tokens."""
    def __init__(self, root=None):
        self.root = Path(root or data_root()).resolve()
        self.lock = threading.RLock()
        self._info, self._seen = None, 0

    def info(self):
        import subprocess, sys, os
        with self.lock:
            if time.monotonic()-self._seen < 30: return self._info
            self._seen = time.monotonic()
            try:
                executable=os.environ.get('ARCHITECT_GPU_PYTHON') or sys.executable
                result=subprocess.run([executable,'-c','import json,gpu_worker; print(json.dumps(gpu_worker.device_info()))'],cwd=Path(__file__).parent,capture_output=True,timeout=15)
                self._info=json.loads(result.stdout) if result.returncode==0 else None
            except (OSError,ValueError,subprocess.TimeoutExpired): self._info=None
            return self._info

    def manage(self, root, body, action):
        if action != 'list': fail('Доступен только GPU этого компьютера.',404)
        info=self.info()
        devices=[] if not info else [dict(id='local-gpu',name=info['device'],shared=False,online=True,allowed=True,busy=SLOT_ACTIVE is not None,queue_count=len(SLOT_WAITERS),remaining_seconds=600,reason='',backend=info['backend'])]
        return {'devices':devices,'selected':'local-gpu' if devices else None}

    def selected(self, root, identity=None, require_available=True):
        if identity not in (None,'local-gpu'): fail('Выберите GPU этого компьютера.')
        info=self.info()
        if not info: fail('GPU недоступен в среде запуска. Для Apple GPU запустите приложение нативно с PyTorch; для NVIDIA настройте CUDA. CPU-подмена отключена.',503)
        return dict(id='local-gpu',name=info['device'],backend=info['backend'])

    def monitor(self, root, run_id): return []

    def execute(self, root, task, data):
        import subprocess,sys,os,queue
        device=self.selected(root)
        execution=EXECUTION.get(); training=TRAINING.get() if task=='train' else None
        cancelled=execution[1] if execution else None
        observer=execution[3] if execution and len(execution)>3 else None
        payload={'task':task,**data}
        if training:
            payload['checkpointing']=True
            if training[0] is not None: payload['checkpoint']=deepcopy(training[0])
        raw=json.dumps(payload,allow_nan=False).encode()+b'\n'
        if len(raw)>MAX_BYTES: fail('GPU-задание больше 8 МиБ.',413)
        process=subprocess.Popen([os.environ.get('ARCHITECT_GPU_PYTHON') or sys.executable,str(Path(__file__).with_name('gpu_worker.py'))],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        events=queue.Queue(maxsize=512)
        def read(stream,kind):
            while True:
                line=stream.readline(MAX_BYTES+1)
                if not line: break
                try: events.put((kind,line),timeout=1)
                except queue.Full: process.kill();break
        readers=[threading.Thread(target=read,args=(stream,kind),daemon=True) for stream,kind in ((process.stdout,'result'),(process.stderr,'progress'))]
        for reader in readers: reader.start()
        deadline=time.monotonic()+JOB_SECONDS; answer=None
        try:
            process.stdin.write(raw);process.stdin.flush()
            while time.monotonic()<deadline:
                if cancelled and cancelled.is_set(): fail('GPU-задание отменено.',409)
                try: kind,line=events.get(timeout=.1)
                except queue.Empty:
                    if process.poll() is not None and all(not t.is_alive() for t in readers): break
                    continue
                if len(line)>MAX_BYTES: fail('Ответ GPU слишком большой.',413)
                try: value=json.loads(line)
                except ValueError: continue
                if kind=='result': answer=value
                else:
                    if 'checkpoint' in value and training:
                        training[1](value['checkpoint'])
                        process.stdin.write(b'checkpoint-saved\n');process.stdin.flush()
                    if observer: observer({k:v for k,v in value.items() if k!='checkpoint'})
            if not answer: fail('GPU не завершил задачу за отведённое время.',504)
            if 'error' in answer: fail(answer['error'],503)
            result=answer['result'];result.setdefault('versions',{})['executor']=device
            return result
        finally:
            if process.poll() is None: process.kill()
            process.wait(timeout=5)
            for reader in readers: reader.join(2)
            for stream in (process.stdin,process.stdout,process.stderr): stream.close()


_BROKER = None
_INIT_LOCK = threading.Lock()


def broker():
    global _BROKER
    with _INIT_LOCK:
        if _BROKER is None: _BROKER = Broker()
        return _BROKER


@contextmanager
def execution(device, cancel_event, run_id=None, observer=None):
    token = EXECUTION.set((device, cancel_event, run_id, observer))
    try: yield
    finally: EXECUTION.reset(token)


def resolve(root, needs_gpu, selection=None, legacy_device=None, require_available=True):
    if selection is not None:
        if not isinstance(selection, dict) or set(selection) - {'mode', 'device_id'} or selection.get('mode') not in ('cpu', 'gpu'): fail('Выберите сервер CPU или GPU компьютера.')
        if selection['mode'] == 'cpu':
            if needs_gpu: fail('В схеме есть GPU-блок. Выберите GPU этого компьютера; сервер CPU его не выполняет.')
            return {'mode': 'cpu', 'name': 'CPU этого компьютера'}
        if not needs_gpu: fail('GPU используется блоком «Нейросеть · GPU компьютера». Для этой CPU-схемы выберите сервер CPU.')
        legacy_device = selection.get('device_id')
        if not isinstance(legacy_device, str): fail('Выберите конкретный GPU.')
    if needs_gpu: return {'mode': 'gpu', **broker().selected(root, legacy_device, require_available)}
    return {'mode': 'cpu', 'name': 'CPU этого компьютера'}


@contextmanager
def training(checkpoint, sink):
    token = TRAINING.set((checkpoint, sink))
    try: yield
    finally: TRAINING.reset(token)

