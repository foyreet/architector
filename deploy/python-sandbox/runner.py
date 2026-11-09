"""This file runs ONLY inside the disposable, restricted container."""
import contextlib
import io
import json
import sys
import traceback


class Log(io.TextIOBase):
    def __init__(self): self.parts = []; self.size = 0
    def write(self, text):
        remaining = max(0, 32000 - self.size)
        if remaining: self.parts.append(text[:remaining])
        self.size += min(len(text), remaining)
        return len(text)
    def flush(self): pass


payload = json.load(sys.stdin)
log = Log()
try:
    namespace = {'__name__': '__user_block__'}
    with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
        exec(compile(payload['code'], '<python-block>', 'exec'), namespace)
        if not callable(namespace.get('run')): raise ValueError('Определите функцию run(inputs, params).')
        result = namespace['run'](payload['inputs'], payload['params'])
        if not isinstance(result, dict): raise ValueError('run() должна вернуть словарь выходов.')
        # Check serialization inside the sandbox; the host validates the schema again.
        json.dumps(result, allow_nan=False)
    response = {'result': result, 'logs': ''.join(log.parts)}
except BaseException:
    response = {'error': traceback.format_exc(limit=8)[-8000:], 'logs': ''.join(log.parts)}
print(json.dumps(response, ensure_ascii=False, allow_nan=False))

