import tempfile, os, json
from tools import config as _tool_config
from tools import op_log as mod

_tool_config.set_config({}, plugin_dir="")

with tempfile.TemporaryDirectory() as tmp_dir:
    db_path = os.path.join(tmp_dir, 'op_log.db')
    _tool_config.set_config({'op_log_db': db_path}, plugin_dir=tmp_dir)
    
    # Trace _connect
    conn = mod._connect()
    print(f'conn path (from _db_path): {mod._db_path()}')
    
    # Check if table exists
    tables = conn.execute("SELECT name FROM sqlite3_master WHERE type='table'").fetchall()
    print(f'Tables: {[t[0] for t in tables]}')
    
    # Insert directly with this connection
    conn.execute(
        "INSERT INTO op_log(session_id, tool_name, params_summary, file_paths, result, error_msg, duration_ms) VALUES(?,?,?,?,?,?,?)",
        (mod._SESSION_ID, 'test', '{}', '', 'ok', '', 1),
    )
    conn.commit()
    
    count = conn.execute("SELECT COUNT(*) FROM op_log").fetchone()[0]
    print(f'Count after manual INSERT: {count}')
    conn.close()
    
    # Now try record
    mod.record('test2', {}, json.dumps({'ok': True}), 2)
    
    conn2 = mod._connect()
    count2 = conn2.execute("SELECT COUNT(*) FROM op_log").fetchone()[0]
    print(f'Count after record: {count2}')
    conn2.close()
