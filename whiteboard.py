"""Account-only lesson boards. Atomic object revisions prevent lost remote edits."""
from contextlib import contextmanager
import hashlib
import json
import math
import os
import re
import secrets
import sqlite3
import time
import uuid

from block_contracts import ContractError

SCHEMA = '''
CREATE TABLE IF NOT EXISTS boards(id TEXT PRIMARY KEY, owner TEXT NOT NULL, title TEXT NOT NULL,
 revision INTEGER NOT NULL DEFAULT 0, invite TEXT, updated REAL NOT NULL);
CREATE TABLE IF NOT EXISTS members(board TEXT, account TEXT, name TEXT, seen REAL,
 PRIMARY KEY(board,account));
CREATE TABLE IF NOT EXISTS objects(board TEXT, id TEXT, version INTEGER NOT NULL, data TEXT,
 PRIMARY KEY(board,id));
CREATE TABLE IF NOT EXISTS operations(board TEXT, account TEXT, id TEXT, digest TEXT, result TEXT,
 PRIMARY KEY(board,account,id));
'''


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-f0-9-]{36}', value):
        raise ContractError('Некорректный идентификатор доски или объекта.')
    return value


def title(value):
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= 120:
        raise ContractError('Название должно содержать от 1 до 120 символов.')
    return value.strip()


def compact(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':'))


def number(value, low=-100000, high=100000):
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise ContractError('Некорректные координаты или размер объекта.')
    return value


def drawing(value):
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ContractError('Некорректный объект доски.')
    kind = value.get('kind')
    fields = {'kind', 'x', 'y', 'color', 'width'}
    if kind == 'pen': fields |= {'points'}
    elif kind in ('rect', 'ellipse', 'arrow'): fields |= {'w', 'h'}
    elif kind == 'text': fields |= {'text'}
    else: raise ContractError('Неизвестный инструмент доски.')
    if set(value) != fields:
        raise ContractError('Некорректные свойства объекта.')
    number(value['x']); number(value['y']); number(value['width'], 1, 12)
    if not isinstance(value['color'], str) or not re.fullmatch(r'#[a-fA-F0-9]{6}', value['color']):
        raise ContractError('Некорректный цвет.')
    if kind == 'pen':
        points = value['points']
        if not isinstance(points, list) or not 2 <= len(points) <= 2000:
            raise ContractError('Штрих должен содержать от 2 до 2000 точек.')
        for point in points:
            if not isinstance(point, list) or len(point) != 2: raise ContractError('Некорректная точка.')
            number(point[0]); number(point[1])
    elif kind == 'text':
        if not isinstance(value['text'], str) or not 1 <= len(value['text'].strip()) <= 1000:
            raise ContractError('Текст должен содержать от 1 до 1000 символов.')
    else:
        number(value['w'], 0 if kind != 'arrow' else -100000)
        number(value['h'], 0 if kind != 'arrow' else -100000)
    return value


@contextmanager
def database(hub):
    for suffix in ('', '-wal', '-shm', '-journal'):
        hub.store.path('workspace/boards/boards.sqlite3' + suffix)
    path = hub.store.path('workspace/boards/boards.sqlite3')
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=10)
    os.chmod(path, 0o600)
    db.row_factory = sqlite3.Row
    try:
        db.executescript(SCHEMA)
        db.execute('BEGIN IMMEDIATE')
        with db:
            yield db
    finally:
        db.close()


def request(hub, user, body, action):
    if user is None:
        raise ContractError('Для совместной доски войдите в аккаунт Архитектора.', 401)
    if action in ('share', 'join', 'revoke'): raise ContractError('Совместный доступ отсутствует в локальной версии.', 404)
    account = user['id']
    with database(hub) as db:
        now = time.time()
        if action == 'list':
            rows = db.execute('SELECT b.id,b.title,b.updated,b.owner FROM boards b JOIN members m '
                              'ON m.board=b.id WHERE m.account=? ORDER BY b.updated DESC LIMIT 200', (account,))
            return {'boards': [dict(row) for row in rows]}
        if action == 'create':
            board_id = str(uuid.uuid4())
            name = title(body.get('title', 'Новая доска'))
            db.execute('INSERT INTO boards(id,owner,title,updated) VALUES(?,?,?,?)', (board_id, account, name, now))
            db.execute('INSERT INTO members VALUES(?,?,?,?)', (board_id, account, user['username'], now))
            return {'id': board_id}
        board_id = identifier(body.get('board_id'))
        board = db.execute('SELECT * FROM boards WHERE id=?', (board_id,)).fetchone()
        if action == 'join':
            token = body.get('token')
            if not board or not board['invite'] or not isinstance(token, str) or not secrets.compare_digest(board['invite'], token):
                raise ContractError('Ссылка недействительна. Попросите владельца прислать новую.', 404)
            db.execute('INSERT OR IGNORE INTO members VALUES(?,?,?,?)', (board_id, account, user['username'], now))
            return {'id': board_id}
        if not board or not db.execute('SELECT 1 FROM members WHERE board=? AND account=?', (board_id, account)).fetchone():
            raise ContractError('Доска недоступна. Откройте ссылку от её владельца.', 404)
        if action == 'get':
            db.execute('UPDATE members SET seen=?,name=? WHERE board=? AND account=?', (now, user['username'], board_id, account))
            items = None
            if body.get('since') != board['revision']:
                items = [{'id': r['id'], 'version': r['version'], 'data': json.loads(r['data']) if r['data'] else None}
                         for r in db.execute('SELECT * FROM objects WHERE board=? ORDER BY rowid', (board_id,))]
            return {'board': {k: board[k] for k in ('id', 'title', 'revision', 'owner')}, 'items': items,
                    'people': [r['name'] for r in db.execute('SELECT name FROM members WHERE board=? AND seen>? ORDER BY name', (board_id, now-30))]}
        if action in ('share', 'revoke', 'rename'):
            if board['owner'] != account:
                raise ContractError('Это действие доступно владельцу доски.', 403)
            if action == 'rename':
                db.execute('UPDATE boards SET title=?,updated=? WHERE id=?', (title(body.get('title')), now, board_id))
            elif action == 'share':
                token = board['invite'] or secrets.token_urlsafe(32)
                db.execute('UPDATE boards SET invite=? WHERE id=?', (token, board_id))
                return {'token': token}
            else:
                db.execute('UPDATE boards SET invite=NULL WHERE id=?', (board_id,))
                db.execute('DELETE FROM members WHERE board=? AND account<>?', (board_id, account))
            return {'ok': True}
        if action != 'apply': raise ContractError('Маршрут доски не найден.', 404)
        op_id, object_id = identifier(body.get('op_id')), identifier(body.get('object_id'))
        expected = body.get('expected')
        if type(expected) is not int or expected < 0: raise ContractError('Некорректная версия объекта.')
        value = drawing(body.get('data'))
        payload = compact(value) if value is not None else None
        digest = hashlib.sha256(compact([object_id, expected, value]).encode()).hexdigest()
        previous = db.execute('SELECT * FROM operations WHERE board=? AND account=? AND id=?', (board_id, account, op_id)).fetchone()
        if previous:
            if previous['digest'] != digest: raise ContractError('Идентификатор правки уже использован.', 409)
            return json.loads(previous['result'])
        existing = db.execute('SELECT version,data FROM objects WHERE board=? AND id=?', (board_id, object_id)).fetchone()
        if expected != (existing['version'] if existing else 0):
            raise ContractError('Этот объект уже изменил другой участник. Выберите, какую правку оставить.', 409)
        count, size = db.execute('SELECT COUNT(*),COALESCE(SUM(length(CAST(data AS BLOB))),0) FROM objects WHERE board=?', (board_id,)).fetchone()
        if (not existing and count >= 2000) or size - len((existing['data'] or '').encode() if existing else b'') + len((payload or '').encode()) > 2*1024*1024:
            raise ContractError('Доска заполнена. Создайте новую доску для продолжения.', 413)
        version = expected + 1
        db.execute('INSERT INTO objects VALUES(?,?,?,?) ON CONFLICT(board,id) DO UPDATE SET version=excluded.version,data=excluded.data', (board_id, object_id, version, payload))
        db.execute('UPDATE boards SET revision=revision+1,updated=? WHERE id=?', (now, board_id))
        result = {'version': version}
        db.execute('INSERT INTO operations VALUES(?,?,?,?,?)', (board_id, account, op_id, digest, compact(result)))
        return result

