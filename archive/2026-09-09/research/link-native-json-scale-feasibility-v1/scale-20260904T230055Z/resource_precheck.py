import sys,json,pathlib
from resource_guard import run
root=pathlib.Path(__file__).resolve().parent
normal=run('resource-normal',5,67108864,[sys.executable,'-c','import time; a=bytearray(4*1024*1024); time.sleep(.1)'])
assert normal['exit_code']==0 and normal['stop_reason'] is None and normal['os_child_peak_rss_bytes']>0
timeout=run('resource-timeout',.2,67108864,[sys.executable,'-c','import time; time.sleep(10)'])
assert timeout['stop_reason']=='TIMEOUT' and timeout['exit_code']<0
memory=run('resource-memory',5,33554432,[sys.executable,'-c','import time; a=[]; [(a.append(bytearray(1024*1024)),time.sleep(.02)) for i in range(64)]'])
assert memory['stop_reason']=='RSS_LIMIT' and memory['exit_code']<0
(root/'resource-prechecks.json').write_text(json.dumps({'status':'PASS','normal':normal,'timeout':timeout,'memory':memory},indent=2)+'\n')
