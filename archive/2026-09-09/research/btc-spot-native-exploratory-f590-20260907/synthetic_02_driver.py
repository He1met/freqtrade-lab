import hashlib
import json
import runpy
import sys
import traceback
from pathlib import Path
from initialize_and_synthetic_once import ROOT, append, put

assert not (ROOT/'synthetic-02').exists()
assert hashlib.sha256((ROOT/'synthetic_probe.py').read_bytes()).hexdigest()=='d498a7428bc710bdc89ef8ca4ca69c57445e91246a108237f6e4f5dd42f7a117'
assert hashlib.sha256((ROOT/'synthetic_probe_v1_original.py').read_bytes()).hexdigest()=='4136d68cd45e9424f449fd65da334b534438056ee1a5de6f01645b56916b4676'
facts={'actual_Backtesting_start_calls':0,'actual_Backtesting_constructor_calls':0,'network_deny_verified_on_exchange':False,'denied_network_calls':0}
def observe(frame,event,arg):
    if event!='call':
        return
    name=frame.f_code.co_name
    filename=frame.f_code.co_filename
    if filename.endswith('/freqtrade/optimize/backtesting.py'):
        if name=='start':
            facts['actual_Backtesting_start_calls']+=1
        elif name=='__init__':
            facts['actual_Backtesting_constructor_calls']+=1
            exchange=frame.f_locals.get('exchange')
            facts['network_deny_verified_on_exchange']=bool(exchange and getattr(exchange._api.fetch,'__name__',None)=='deny' and getattr(exchange._api_async.fetch,'__name__',None)=='deny')
    if filename==str(ROOT/'synthetic_probe.py') and name=='deny':
        facts['denied_network_calls']+=1

pre=append({'record_type':'AUTHORIZED_SYNTHETIC_TECHNICAL_RECOVERY_START','authorization_source_thread':'01a05dcc-17fd-7972-9177-9fed95e4b07a',
    'repair':'Only local probe Profile exchange=okx added','old_probe_sha256':'4136d68cd45e9424f449fd65da334b534438056ee1a5de6f01645b56916b4676',
    'new_probe_sha256':'d498a7428bc710bdc89ef8ca4ca69c57445e91246a108237f6e4f5dd42f7a117','old_slot_consumed':1,'new_slot_consumed':1,
    'synthetic_output_root':str(ROOT/'synthetic-02'),'market_budget_unchanged':1},'26cd2644cd36c44261a06bdf827ab5fb3743c9f80daf0ab6e4bfa11d94ba54bc')
put('synthetic-02-authorization-receipt.json',pre)
sys.argv=[str(ROOT/'synthetic_probe.py'),str(ROOT/'synthetic-02'),str(ROOT/'BtcWeeklyMomentumFixedStake.py')]
code=0
sys.setprofile(observe)
try:
    runpy.run_path(str(ROOT/'synthetic_probe.py'),run_name='__main__')
except BaseException as exc:
    code=1
    traceback.print_exc()
finally:
    sys.setprofile(None)
    evidence=ROOT/'synthetic-02/evidence.json'
    result={'status':'SYNTHETIC_02_PASS' if code==0 and evidence.exists() else 'SYNTHETIC_02_FAILED_STOP',
        'process_result':code,'synthetic_invocations_total':2,'synthetic_slots_consumed_total':2,**facts,
        'market_native_calls':0,'capture_invocations':0,'retry_authorized':False,
        'evidence_sha256':hashlib.sha256(evidence.read_bytes()).hexdigest() if evidence.exists() else None}
    put('synthetic-02-execution-receipt.json',result)
    result['ledger']=append({'record_type':'SYNTHETIC_TECHNICAL_RECOVERY_TERMINAL',**result})
    put('synthetic-02-delivery-receipt.json',result)
    print(json.dumps(result,indent=2))
sys.exit(code)
