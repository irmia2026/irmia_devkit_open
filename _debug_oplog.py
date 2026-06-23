import tempfile, os, json
from tools import config as _tool_config
from tools import op_log

d = tempfile.mkdtemp()
db_path = os.path.join(d, 'op_log.db')
print(f'db_path: {db_path}')
print(f'_INITIALIZED_DB before: {op_log._INITIALIZED_DB}')

_tool_config.set_config({'op_log_db': db_path}, plugin_dir=d)

# Check what _db_path returns
from tools.op_log import _db_path as _op_db_path
actual = str(_op_db_path())
print(f'_db_path() returns: {actual}')
print(f'matches db_path: {actual == db_path}')

# Try record
op_log.record('safe_edit', {'old': 'x = 1'}, json.dumps({'ok': True}), 12)

# Check directly
import sqlite3
conn = sqlite3.connect(db_path)
count = conn.execute('SELECT COUNT(*) FROM op_log').fetchone()[0]
print(f'Direct DB count: {count}')
conn.close()

# Query
result = op_log.query('recent', limit=5)
print(f'result ok: {result["ok"]}')
print(f'total_entries: {result["total_entries"]}')
print(f'recent: {result.get("recent", [])}')

import shutil
shutil.rmtree(d, ignore_errors=True)
