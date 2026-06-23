import tempfile, os, json, sys, traceback
from tools import config as _tool_config
from tools import op_log

with tempfile.TemporaryDirectory() as d:
    db_path = os.path.join(d, 'op_log.db')
    _tool_config.set_config({'op_log_db': db_path}, plugin_dir=d)
    
    long_code = 'def hello():\n    print("hello world")\n    return 42\n' * 5
    print(f'long_code len: {len(long_code)}')
    
    try:
        op_log.record(
            'safe_edit',
            {
                'filepath': 'a.py',
                'old': long_code,
                'new': long_code.replace('hello', 'goodbye'),
                'url': 'https://example.com',
            },
            json.dumps({'ok': True}),
            12,
        )
    except Exception:
        traceback.print_exc()
    
    result = op_log.query('recent', limit=5)
    print(f'ok: {result["ok"]}, total_entries: {result["total_entries"]}, recent: {len(result.get("recent", []))}')
    if result.get('recent'):
        print(f'params_summary: {result["recent"][0]["params_summary"][:200]}')
