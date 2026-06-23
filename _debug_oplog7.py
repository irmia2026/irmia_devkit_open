import tempfile, os, json, traceback, sqlite3
from tools import config as _tool_config
from tools import op_log as mod

_tool_config.set_config({}, plugin_dir="")

with tempfile.TemporaryDirectory() as tmp_dir:
    db_path = os.path.join(tmp_dir, 'op_log.db')
    _tool_config.set_config({'op_log_db': db_path}, plugin_dir=tmp_dir)
    
    long_code = 'def hello():\n    print("hello world")\n    return 42\n' * 5
    
    # Manually replicate record() with exception visibility
    status, error_msg = mod._result_status(json.dumps({'ok': True}))
    conn = None
    try:
        conn = mod._connect()
        print(f'Connected to: {mod._db_path()}')
        print(f'Tables before INSERT: {[r[0] for r in conn.execute("SELECT name FROM sqlite3_master WHERE type=\"table\"").fetchall()]}')
        conn.execute(
            "INSERT INTO op_log(session_id, tool_name, params_summary, file_paths, result, error_msg, duration_ms) "
            "VALUES(?,?,?,?,?,?,?)",
            (
                mod._SESSION_ID,
                'safe_edit',
                mod._params_summary({'filepath': 'a.py', 'old': long_code, 'new': long_code.replace('hello', 'goodbye'), 'url': 'https://example.com'}),
                mod._extract_file_paths({'filepath': 'a.py', 'old': long_code}),
                status,
                error_msg,
                12,
            ),
        )
        conn.commit()
        print('INSERT + commit done')
        count = conn.execute("SELECT COUNT(*) FROM op_log").fetchone()[0]
        print(f'Count in this connection: {count}')
    except Exception as e:
        print(f'Error: {type(e).__name__}: {e}')
        traceback.print_exc()
    finally:
        if conn:
            conn.close()
    
    # Now query through the API
    result = mod.query('recent', limit=5)
    print(f'query total_entries: {result["total_entries"]}')
    print(f'query recent count: {len(result.get("recent", []))}')
    
    # Also check with raw sqlite3
    raw_conn = sqlite3.connect(db_path)
    raw_count = raw_conn.execute("SELECT COUNT(*) FROM op_log").fetchone()[0]
    print(f'Raw connect count: {raw_count}')
    raw_conn.close()
