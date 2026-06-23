import tempfile, os, json, traceback
from tools import config as c
from tools import op_log as m

c.set_config({}, '')
d = tempfile.mkdtemp()
p = os.path.join(d, 'op_log.db')
c.set_config({'op_log_db': p}, plugin_dir=d)

long_code = 'x' * 200

try:
    m.record('safe_edit', {'filepath':'a.py','old':long_code,'new':long_code}, json.dumps({'ok':True}), 12)
    print('record OK')
except Exception as e:
    print(f'{type(e).__name__}: {e}')
    traceback.print_exc()

r = m.query('recent')
print(f'total: {r["total_entries"]}')

import shutil
shutil.rmtree(d)
