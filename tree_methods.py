"""Editable local guidance. Response contracts stay in the callers."""
from block_contracts import ContractError


def method_group(hub, user, defaults, changes=None):
    """Apply just the edited methods together, including the conflict checks."""
    if changes is not None and (not isinstance(changes, dict) or not changes or changes.keys() - defaults.keys()):
        raise ContractError('Выберите методику для сохранения.')
    result = {}
    with hub.db() as db:
        db.execute('BEGIN IMMEDIATE' if changes is not None else 'BEGIN')
        for mode, default in defaults.items():
            key = (user['id'], mode)
            row = db.execute('SELECT text FROM tree_methods WHERE owner=? AND mode=?', key).fetchone()
            current = row['text'] if row else default
            if changes and mode in changes:
                change = changes[mode]
                if not isinstance(change, dict) or 'text' not in change:
                    raise ContractError('Введите методику или верните встроенную.')
                value = change['text']
                if value is not None and (not isinstance(value, str) or not value.strip()):
                    raise ContractError('Введите методику или верните встроенную.')
                desired = default if value is None else value.strip()
                if desired != current:
                    if current != change.get('previous'):
                        raise ContractError('Методика изменилась в другой вкладке. Скопируйте свои правки и откройте методику заново.', 409)
                    if desired == default:
                        db.execute('DELETE FROM tree_methods WHERE owner=? AND mode=?', key)
                    else:
                        db.execute('INSERT OR REPLACE INTO tree_methods(owner,mode,text) VALUES(?,?,?)', (*key, desired))
                current = desired
            result[mode] = {'text': current, 'default': default}
    return result


def method_settings(hub, user, mode, default, changes=None):
    edits = {mode: changes} if changes is not None else None
    return method_group(hub, user, {mode: default}, edits)[mode]


def with_contract(method, contract):
    return method + '\n\nОбязательные правила ответа приложения:\n' + contract


def instructions(hub, user, mode, default, contract):
    return with_contract(method_settings(hub, user, mode, default)['text'], contract)
