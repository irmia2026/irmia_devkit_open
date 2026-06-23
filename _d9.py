import tempfile, os, json, traceback, sqlite3
from tools import config as c
from tools import op_log as m

c.set_config({}, '')
d = tempfile.mkdtemp()
p = os.path.join(d, 'op_log.db')
c.set_config({'op_log_db': p}, plugin_dir=d)

long_code = 'x' * 200
status, error_msg = m._result_status(json.dumps({'ok': True}))
conn = m._connect()
print(f'Tables: {conn.execute("SELECT name FROM sqlite_master").fetchall()}')
params = m._params_summary({'filepath':'a.py','old':long_code,'new':long_code})
fps = m._extract_file_paths({'filepath':'a.py','old':long_code})
print(f'params len: {len(params)}, fps: {fps}')

try:
    conn.execute(
        "INSERT INTO op_log(session_id, tool_name, params_summary, file_paths, result, error_msg, duration_ms) "
        "VALUES(?,?,?,?,?,?,?)",
        (m._SESSION_ID, 'safe_edit', params, fps, status, error_msg, 12),
    )
    conn.commit()
    print('INSERT OK')
except Exception as e:
    print(f'INSERT FAILED: {type(e).__name__}: {e}')
    traceback.print_exc()

count = conn.execute("SELECT COUNT(*) FROM op_log").fetchone()[0]
print(f'count: {count}')
conn.close()

import shutil
shutil.rmtree(d)
