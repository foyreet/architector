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
            if kind not in bc.CONTRACTS or pin != {'version': bc.CONTRACTS[kind]['version'], 'digest': sg.digest(bc.CONTRACTS[kind])}:
                raise bc.ContractError('Версия блока несовместима со схемой: ' + kind, 409)

def private_context(server, hub, user, completion, kaggle, huggingface, pipeline):
    return SimpleNamespace(server=server, root=hub.root, completion=completion, kaggle=kaggle, huggingface=huggingface, pipeline=pipeline)
