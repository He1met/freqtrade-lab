"""One-shot launch with fresh machine checks and frozen script verification."""
import datetime,hashlib,json,pathlib,re,subprocess,sys,time,os
from resource_guard import run,DEADLINE
ROOT=pathlib.Path(__file__).resolve().parent
mode=sys.argv[1]; assert mode in {'small','generate','process'}
assert time.time()<DEADLINE
frozen=json.loads((ROOT/'freeze-manifest.json').read_text())
for name,sha in frozen['local_sources'].items():
    assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==sha,name
assert json.loads((ROOT/'remote-freeze-readback.json').read_text())['body']==(ROOT/'issue-body.md').read_text()
assert json.loads((ROOT/'resource-prechecks.json').read_text())['status']=='PASS'
if mode=='generate': assert json.loads((ROOT/'small-result.json').read_text())['status']=='PASS_SYNTHETIC_ONLY'
if mode=='process':
    assert json.loads((ROOT/'generate-result.json').read_text())['status']=='PASS_SYNTHETIC_ONLY'
    gen=json.loads((ROOT/'generate.resources.json').read_text()); assert gen['exit_code']==0 and gen['stop_reason'] is None
ram=int(subprocess.check_output(['sysctl','-n','hw.memsize'],text=True))
mem=subprocess.check_output(['memory_pressure','-Q'],text=True)
free=int(re.search(r'free percentage: (\d+)%',mem)[1])
stat=os.statvfs(ROOT); disk=stat.f_bavail*stat.f_frsize
size=sum(p.stat().st_size for p in ROOT.rglob('*') if p.is_file())
record={'time_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'ram_bytes':ram,'free_percent':free,'available_disk_bytes':disk,'root_bytes':size}
(ROOT/(mode+'-machine-preflight.json')).write_text(json.dumps(record,indent=2)+'\n')
assert ram==17179869184 and free>=40 and disk>2*1024**3 and size<2*1024**3,'BLOCKED_CURRENT_RESOURCES'
r=run(mode,600,4*1024**3,[sys.executable,str(ROOT/'scale_case.py'),mode])
assert sum(p.stat().st_size for p in ROOT.rglob('*') if p.is_file())<2*1024**3,'ROOT_SIZE_LIMIT'
sys.exit(0 if r['exit_code']==0 and r['stop_reason'] is None else 2)
