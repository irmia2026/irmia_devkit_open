import tempfile, os, json, sys, traceback
from tools import config as _tool_config
from tools import op_log

with tempfile.TemporaryDirectory() as d:
    db_path = os.path.join(d, 'op_log.db')
    _tool_config.set_config({'op_log_db': db_path}, plugin_dir=d)
    
    long_code = 'def hello():\n    print("hello world")\n    return 42\n' * 5
    
    # Monkey-patch to see the exception
    import tools.op_log as mod
    original_connect = mod._connect
    def debug_connect():
        conn = original_connect()
        print(f'  _connect() returned: {conn}')
        return conn
    mod._connect = debug_connect
    
    try:
        mod.record(
            'safe_edit',
            {'filepath': 'a.py', 'old': long_code, 'new': long_code.replace('hello', 'goodbye'), 'url': 'https://example.com'},
            json.dumps({'ok': True}),
            12,
        )
        print('record() completed')
    except Exception as e:
        print(f'record() raised: {type(e).__name__}: {e}')
        traceback.print_exc()
    
    result = mod.query('recent', limit=5)
    print(f'query: ok={result["ok"]}, total={result["total_entries"]}')
