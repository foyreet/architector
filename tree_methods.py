"""Editable local guidance for tree proposals. Response contracts stay in the callers."""
from block_contracts import ContractError


def method_settings(hub, user, mode, default, changes=None):
    with hub.db() as db:
        if changes is not None:
            db.execute('BEGIN IMMEDIATE')
        key = (user['id'], mode)
        row = db.execute('SELECT text FROM tree_methods WHERE owner=? AND mode=?', key).fetchone()
        current = row['text'] if row else default
        if changes is not None:
            value = changes.get('text')
            if 'text' not in changes or (value is not None and (not isinstance(value, str) or not value.strip())):
                raise ContractError('Введите методику или верните встроенную.')
            desired = default if value is None else value.strip()
            if current != desired:
                if current != changes.get('previous'):
                    raise ContractError('Методика изменилась в другой вкладке. Скопируйте свои правки и откройте методику заново.', 409)
                if desired == default:
                    db.execute('DELETE FROM tree_methods WHERE owner=? AND mode=?', key)
                else:
                    db.execute('INSERT OR REPLACE INTO tree_methods(owner,mode,text) VALUES(?,?,?)', (*key, desired))
            current = desired
        return {'text': current, 'default': default}


def instructions(hub, user, mode, default, contract):
    method = method_settings(hub, user, mode, default)['text']
    return method + '\n\nОбязательные правила ответа приложения:\n' + contract
