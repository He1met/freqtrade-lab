"""Read-only post-run evidence checks; no native case reruns or data requests."""
import datetime,hashlib,json,pathlib,subprocess,psutil
ROOT=pathlib.Path(__file__).resolve().parent
def digest(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def command(args,cwd=None): return subprocess.run(args,cwd=cwd,capture_output=True,text=True,check=True).stdout.strip()
freeze=json.loads((ROOT/'freeze-manifest.json').read_text())
verified={}
for name,meta in freeze['files'].items():
    actual=ROOT/('run_synthetic_frozen.py' if name=='run_synthetic.py' else name)
    assert digest(actual)==meta['sha256'],name
    verified[name]={'equal':True,'retained_path':actual.name}
spec=json.loads((ROOT/'synthetic-cases.json').read_text())
for case in spec['execution']['cases']:
    name=case['name']; result=json.loads((ROOT/('synthetic-'+name+'.json')).read_text())
    assert result['status']=='PASS_SYNTHETIC_ONLY' and result['native_backtest_called']
    assert result['flow_rows']==42 and result['flow_missing_indices']==[] and result['network_attempts']==[]
    for k,v in case['expect'].items(): assert result['actual'][k]==v
    work=ROOT/('synthetic-'+name)
    inputs=json.loads((work/'data/futures/LINK_USDT_USDT-trades.json').read_text())
    assert len(inputs)==84
    for i in range(42):
        assert inputs[2*i][0]==946684800000+i*300000+1
        assert inputs[2*i+1][0]==946684800000+i*300000+2
    trades=json.loads((work/'native-synthetic-trades.json').read_text())
    assert len(trades)==case['expect']['count']
    if name in ['R1_NORMAL','R2_NORMAL']:
        assert trades[0]['open_rate']==101 and trades[0]['close_rate']==101
        assert trades[0]['open_date']=='2000-01-01T02:45:00.000Z'
        assert trades[0]['close_date']=='2000-01-01T02:50:00.000Z'
resources=[json.loads(p.read_text()) for p in ROOT.glob('*.resources.json')]
alive=[]
for x in resources:
    try:
        p=psutil.Process(x['owned_pid'])
        if p.create_time()==x['owned_process_created'] and p.is_running(): alive.append(x['owned_pid'])
    except psutil.NoSuchProcess: pass
assert not alive
for x in resources:
    if not x['label'].startswith('resource-'):
        assert x['stop_reason'] is None
        assert max(x['sampled_tree_peak_rss_bytes'],x['os_child_peak_rss_bytes'])<=2147483648
        assert x['elapsed_seconds']<=x['timeout_seconds']<=300
        assert x['exit_code']==0 or x['label']=='real-roundtrip'
lab='/Users/shenjianpeng/.codex/worktrees/9ce1/freqtrade-lab'
native='/Users/shenjianpeng/.codex/runs/freqtrade-lab/issue-43-profile-driven-v1/freqtrade'
assert command(['git','status','--porcelain'],lab)==''
assert command(['git','status','--porcelain'],native)==''
assert command(['git','rev-parse','HEAD'],lab)=='dc82c61fe8a27a654977344755c088412518d858'
assert command(['git','rev-parse','HEAD'],native)=='52bc96f4480b1a0da6a9b455bd00b17fbb6786a5'
remote=command(['git','ls-remote','origin','refs/heads/main'],lab)
assert remote.split()[0]=='dc82c61fe8a27a654977344755c088412518d858'
issue=json.loads(command(['gh','issue','view','67','--json','body,state,url,number'],lab))
assert issue['state']=='OPEN' and issue['body']==(ROOT/'issue-body.md').read_text()
old=pathlib.Path('/Users/shenjianpeng/.codex/runs/freqtrade-lab/link-native-orderflow-g1-v1/g1-20260904T215103Z')
assert digest(old/'g1-receipt.md')=='864b5d27351e6c7fffe8cc94a64d7a96616eb0b590fd423c06dea43fd9983f9a'
assert digest(old/'g1-final-evidence.json')=='32db17b44cb3aeb937751bd3af8ab1fdfd3c26acc2b1bb0c3d9166b3b25e2282'
states={str(n):json.loads(command(['gh','issue','view',str(n),'--json','state'],lab))['state'] for n in [62,65,66]}
assert states=={'62':'OPEN','65':'CLOSED','66':'OPEN'}
assert ROOT.stat().st_mode & 0o077==0
for n in ['catalog','api','zip']:
    req=json.loads((ROOT/(n+'-request.json')).read_text())
    assert req['actual_attempts']==1 and req['status']=='RECEIVED'
    assert digest(ROOT/(n+'.raw'))==req['sha256']
files={str(p.relative_to(ROOT)):{'bytes':p.stat().st_size,'sha256':digest(p)} for p in sorted(ROOT.rglob('*')) if p.is_file()}
out={'verified_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'files':files,
 'frozen_manifest_checks':verified,'root_mode':oct(ROOT.stat().st_mode & 0o777),
 'resources':resources,'owned_processes_alive':alive,'remote_main':remote,'lab_clean':True,'native_clean':True,
 'original_checkout_dirty_preserved':command(['git','status','--porcelain'],'/Users/shenjianpeng/Documents/freqtrade-lab'),
 'issue_67_body_equal':True,'issue_67_state':'OPEN','old_issue_states':states,'old_g1_receipt_and_index_unchanged':True,
 'native_source_critical_hashes':{n:digest(pathlib.Path(native)/n) for n in ['freqtrade/strategy/interface.py','freqtrade/data/dataprovider.py','freqtrade/data/history/datahandlers/jsondatahandler.py','freqtrade/data/converter/orderflow.py','freqtrade/optimize/backtesting.py']},
 'native_output_readback':'PASS: 84 trades exact +1/+2ms for all 42 candles, all five native executions and normal open prices checked from saved native outputs; no rerun',
 'wire_repair_count':1,'semantic_case_executions':6,'native_backtest_executions':5,
 'limitations':['Sample only','Historical contractSize/base amount unproven','Cross-file semantics/full-window JSON resources/funding/availability unproven','No economic research','Service tier UNKNOWN']}
(ROOT/'final-evidence.json').write_text(json.dumps(out,indent=2)+'\n')
print(json.dumps({k:v for k,v in out.items() if k not in ['files','resources','frozen_manifest_checks','native_source_critical_hashes']},indent=2))
print('INDEX_SHA256',digest(ROOT/'final-evidence.json'))
