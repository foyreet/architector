"""Native execution: real processes and synthetic inputs only."""
import os
import unittest
from unittest.mock import patch
import code_sandbox as runner


def execute(code, timeout=10):
    return runner.run({'code': code, 'inputs': {}, 'params': {}, 'timeout': timeout})


class NativePythonTests(unittest.TestCase):
    def test_real_process_imports_logs_and_environment(self):
        with patch.dict(os.environ, {'UNRELATED_SECRET_FOR_TEST': 'not-in-worker'}):
            result = execute('''import os
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
def run(inputs, params):
    model = LogisticRegression().fit([[0],[1],[9],[10]], [0,0,1,1])
    print("локальный Python")
    return {"report": {"score": model.score([[0],[10]],[0,1]),
        "sum": int(pd.Series(np.array([1,2])).sum()),
        "secret": os.environ.get("UNRELATED_SECRET_FOR_TEST")}}
''', 30)
        self.assertNotIn('error', result)
        self.assertEqual(result['result']['report'], {'score': 1., 'sum': 3, 'secret': None})
        self.assertIn('локальный Python', result['logs'])
        self.assertEqual(result['runtime']['executor'], 'local-process')

    def test_legacy_timeout_is_ignored(self):
        result = execute('import time\ndef run(inputs, params):\n    time.sleep(1.2)\n    return {}', 1)
        self.assertEqual(result['result'], {})

    def test_memory_monitor_stops_process_without_large_allocation(self):
        with patch.object(runner, 'MEMORY_MB', 256), patch.object(runner, 'memory_usage', return_value=10**12):
            result = execute('import time\ndef run(inputs, params): time.sleep(20)')
        self.assertIn('памяти', result['error'])
        self.assertEqual(execute('def run(inputs, params): return {}')['result'], {})

    def test_invalid_protocol(self):
        result = execute('import os\nos.write(1, b"invalid")\ndef run(inputs, params): return {}')
        self.assertIn('протокол', result['error'])

    def test_worker_exception(self):
        result = execute('def run(inputs, params): raise ValueError("test failure")')
        self.assertIn('test failure', result['error'])
