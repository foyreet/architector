"""Worker for an ordinary local Python subprocess, with the current user permissions."""
import contextlib
import io
import json
import sys
import traceback


# -I ignores PYTHONIOENCODING; explicitly use UTF-8 on Windows too.
sys.stdin.reconfigure(encoding='utf-8')
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')
payload = json.load(sys.stdin)
log = io.StringIO()
try:
    namespace = {'__name__': '__user_block__'}
    with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
        exec(compile(payload['code'], '<python-block>', 'exec'), namespace)
        if not callable(namespace.get('run')): raise ValueError('Определите функцию run(inputs, params).')
        result = namespace['run'](payload['inputs'], payload['params'])
        if not isinstance(result, dict): raise ValueError('run() должна вернуть словарь выходов.')
        # Check serialization inside the worker; the host validates the schema again.
        json.dumps(result, allow_nan=False)
    response = {'result': result, 'logs': log.getvalue()}
except BaseException:
    response = {'error': traceback.format_exc(), 'logs': log.getvalue()}
print(json.dumps(response, ensure_ascii=False, allow_nan=False))

