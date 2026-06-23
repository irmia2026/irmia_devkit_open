import tempfile, os, json
from tools import config as _tool_config
from tools import op_log

# Simulate what pytest does
_tool_config.set_config({}, plugin_dir="")  # _reset_config fixture

with tempfile.TemporaryDirectory() as tmp_dir:
    db_path = os.path.join(tmp_dir, 'op_log.db')
    _tool_config.set_config({'op_log_db': db_path}, plugin_dir=tmp_dir)
    
    print(f'config op_log_db: {_tool_config.get_config().get("op_log_db")}')
    print(f'_INITIALIZED_DB: {op_log._INITIALIZED_DB}')
    
    long_code = 'def hello():\n    print("hello world")\n    return 42\n' * 5
    
    op_log.record(
        'safe_edit',
        {'filepath': 'a.py', 'old': long_code, 'new': long_code.replace('hello', 'goodbye'), 'url': 'https://example.com'},
        json.dumps({'ok': True}),
        12,
    )
    
    print(f'_INITIALIZED_DB after: {op_log._INITIALIZED_DB}')
    
    result = op_log.query('recent', limit=5)
    print(f'total: {result["total_entries"]}, recent: {len(result.get("recent", []))}')
