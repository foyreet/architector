"""One local workspace. No accounts, passwords, sessions or remote catalog."""
from contextlib import contextmanager
from types import SimpleNamespace
from copy import deepcopy
import subgraphs as sg
import os
import sqlite3
import threading
import project_store as ps
import block_contracts as bc

LOCK = threading.RLock()
LOCAL_USER = {'id': 'local', 'username': 'На этом компьютере', 'primary': True}

# Contract digests saved before local data and execution limits were removed.
COMPATIBLE_PINS = {'gpu_train': ['1e75ae7c34be2094f6afdba40da93992cce784a6f981fadcb4c67fd6ce4cfebb',
               '423f9a33ac6f13773b6159236a2c9c9046f4ca67c8b642819e0eaa4a59003cb8'],
 'local_model': ['5f0d96b2407851ae6e2f6374f4bee490b03b7c16537266daa3a442f0f7d35f35'],
 'ml_prepare': ['d520c68be013b34337e58267b76c3f862021b265fd3b4279b5abdb2b9329e093'],
 'ml_train': ['0081881d10175f380747a3d4c592c16ed7c4c161103cd567acd39b86115f89a0',
              '44ea3edc709ab3294ed277e26ae6ccadd31624cf00f1a31417f5c9b3d4f036a9',
              '603789bdb9dc5fbd7898fd62cef1b2ac10471261dd6175248adef5189a3ae59d',
              'af432d256d4055f34e6f7969e3c8a9cf166694f34b0a371c781ea8344f48443d'],
 'openrouter': ['63a1ee2da3442da25439984290845a100c03f7425f5a7d632b2b60a644fb0955'],
 'python_code': ['7df81fcfe3ce096b5d1e0ed1896f2f3596b49f3bf72fbea1762be21b411d4c4f'],
 'template': ['f50aeb27b1f2c69a7e35b4eced0f256378938434cb385a2adc086df40db91d5e']}

class Community:
    def __init__(self, root=None):
        self.store = ps.ProjectStore(root)
        self.root = self.store.root

    @contextmanager
    def db(self):
        with LOCK:
            path = self.store.path('workspace/local/documents.sqlite3')
            path.parent.mkdir(parents=True, exist_ok=True)
            db = sqlite3.connect(path, timeout=10)
            os.chmod(path, 0o600)
            db.row_factory = sqlite3.Row
            try:
                db.execute('CREATE TABLE IF NOT EXISTS design_documents(id TEXT PRIMARY KEY, owner TEXT NOT NULL, title TEXT NOT NULL, sections TEXT NOT NULL, revision INTEGER NOT NULL, updated REAL NOT NULL, source_release TEXT)')
                with db: yield db
            finally: db.close()

    def enabled(self): return False
    def session(self, token=''): return dict(LOCAL_USER)
    def workspace(self, user=None): return self.store
    def release(self, identity): raise bc.ContractError('Каталог сообщества отсутствует в локальной версии.', 404)
    @staticmethod
    def check_pins(pins):
        for kind, pin in pins.get('builtins', {}).items():
            if kind == 'ml_train':
                legacy = deepcopy(bc.CONTRACTS[kind])
                next(s for s in legacy['settings'] if s['id'] == 'n_estimators')['maximum'] = 100
                if pin == {'version': legacy['version'], 'digest': sg.digest(legacy)}: continue
            if isinstance(pin, dict) and pin.get('version') == 1 and pin.get('digest') in COMPATIBLE_PINS.get(kind, ()):
                continue
            if kind not in bc.CONTRACTS or pin != {'version': bc.CONTRACTS[kind]['version'], 'digest': sg.digest(bc.CONTRACTS[kind])}:
                raise bc.ContractError('Версия блока несовместима со схемой: ' + kind, 409)

def private_context(server, hub, user, completion, kaggle, huggingface, pipeline):
    return SimpleNamespace(server=server, root=hub.root, completion=completion, kaggle=kaggle, huggingface=huggingface, pipeline=pipeline)
