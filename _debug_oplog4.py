import tempfile, os, json
from tools import config as _tool_config
from tools import op_log

with tempfile.TemporaryDirectory() as d:
    db_path = os.path.join(d, 'op_log.db')
    _tool_config.set_config({'op_log_db': db_path}, plugin_dir=d)
    
    # Manually reproduce what record() does
    import sqlite3, uuid
    status, error_msg = op_log._result_status(json.dumps({'ok': True}))
    print(f'status={status}, error_msg={error_msg}')
    
    params_summary = op_log._params_summary({'old': 'x = 1'})
    print(f'params_summary={params_summary}')
    
    file_paths = op_log._extract_file_paths({'old': 'x = 1'})
    print(f'file_paths={file_paths}')
    
    session_id = op_log._SESSION_ID
    print(f'session_id={session_id}')
    
    # Now try to connect and insert
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS op_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            tool_name TEXT NOT NULL,
            params_summary TEXT,
            file_paths TEXT,
            result TEXT NOT NULL,
            error_msg TEXT,
            duration_ms INTEGER,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        )
    """)
    
    conn.execute(
        "INSERT INTO op_log(session_id, tool_name, params_summary, file_paths, result, error_msg, duration_ms) VALUES(?,?,?,?,?,?,?)",
        (session_id, 'safe_edit', params_summary, file_paths, status, error_msg, 12),
    )
    conn.commit()
    
    count = conn.execute("SELECT COUNT(*) FROM op_log").fetchone()[0]
    print(f'Manual INSERT count: {count}')
    conn.close()
    
    # Now try record()
    op_log.record('safe_edit', {'old': 'y = 2'}, json.dumps({'ok': True}), 12)
    
    conn2 = sqlite3.connect(db_path)
    count2 = conn2.execute("SELECT COUNT(*) FROM op_log").fetchone()[0]
    print(f'After record(), manual connect count: {count2}')
    conn2.close()
    
    # Try query
    result = op_log.query('recent', limit=5)
    print(f'query total_entries: {result["total_entries"]}')
