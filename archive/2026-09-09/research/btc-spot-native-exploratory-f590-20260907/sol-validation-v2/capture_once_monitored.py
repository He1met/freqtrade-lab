import hashlib
import json
import os
import signal
import sys
import time
import traceback
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from runtime_control import ROOT, append, put, verify_freeze
from scripts import fetch_okx_profile_data as capture

verify_freeze()
assert json.loads((ROOT/'benchmark-artificial-receipt.json').read_text())['status']=='PASS'
assert (ROOT/'database-initialization-receipt.json').exists()
assert not (ROOT/'source-sd-01').exists()
command=json.loads((ROOT/'commands.json').read_text())['capture_sd']
start=time.monotonic()
events=[]
state={'http_calls':0,'decoded_response_bytes':0,'peak_observed_run_bytes':0}
os.umask(0o077)

def size():
    return sum(p.stat().st_size for p in ROOT.rglob('*') if p.is_file() and not p.is_symlink())

def alarm(*args):
    raise TimeoutError('authorized capture 900 second watchdog exceeded')

original_guard=capture.install_request_guard
def monitored_guard(exchange):
    original_guard(exchange)
    original=exchange.session.request
    def request(method,url,*args,**kwargs):
        p=urlparse(url);q=parse_qs(p.query)
        assert method.upper()=='GET' and p.hostname=='www.okx.com'
        assert p.path in {'/api/v5/public/instruments','/api/v5/market/history-candles'}
        assert q.get('instId')==['SOL-USDT']
        if p.path.endswith('/instruments'):
            assert q.get('instType')==['SPOT'] and state['http_calls']==0
        else:
            assert q.get('bar')==['1Dutc']
            assert int(q['before'][0])>=1612051200000-1
            assert int(q['after'][0])<=1675209600000
        assert state['http_calls']<9, 'authorized HTTP call count exceeded'
        state['http_calls']+=1
        event={'index':state['http_calls'],'method':'GET','url':url}
        try:
            response=original(method,url,*args,**kwargs)
            content=response.content
            state['decoded_response_bytes']+=len(content)
            event.update(status=response.status_code,decoded_bytes=len(content),response_sha256=hashlib.sha256(content).hexdigest())
            return response
        except BaseException as exc:
            event['error_type']=type(exc).__name__
            raise
        finally:
            events.append(event)
            with (ROOT/'capture-network-events.jsonl').open('a') as f:
                f.write(json.dumps(event,sort_keys=True)+'\n')
            state['peak_observed_run_bytes']=max(state['peak_observed_run_bytes'],size())
            if state['peak_observed_run_bytes']>50*1024**2 or state['decoded_response_bytes']>50*1024**2:
                raise RuntimeError('authorized response-after 50MiB threshold exceeded')
    exchange.session.request=request
capture.install_request_guard=monitored_guard
pre=append({'record_type':'AUTHORIZED_CONDITIONAL_VALIDATION_CAPTURE_START','pair':'SOL/USDT','source_window':['2021-01-31','2023-02-01'],
    'maximum_http_calls':9,'maximum_seconds':900,'maximum_bytes_response_after':50*1024**2,'capture_invocations':1,
    'market_native_calls':0,'D_machine_QC_only':True,'D_researcher_values_read':False})
put('capture-start-receipt.json',pre)
signal.signal(signal.SIGALRM,alarm);signal.alarm(900)
sys.argv=command[4:]
result_code=0
error=None
try:
    capture.main()
except BaseException as exc:
    error={'type':type(exc).__name__,'message':str(exc)[:600]}
    result_code=1
    traceback.print_exc()
finally:
    signal.alarm(0)
    state['peak_observed_run_bytes']=max(state['peak_observed_run_bytes'],size())
    if state['peak_observed_run_bytes']>50*1024**2:
        result_code=1;error={'type':'BudgetExceeded','message':'post-write output size exceeded 50MiB'}
    receipt={'status':'CAPTURE_PASS_PENDING_SOURCE_QC' if result_code==0 else 'CAPTURE_FAILED_STOP',
        'capture_invocations':1,'market_native_calls':0,'elapsed_seconds':time.monotonic()-start,'error':error,**state,
        'monitoring':'maximum 9 before-request calls; 900s signal watchdog; response-after and final-write 50MiB checks',
        'wire_call_counter':'requests.session.request observed calls','retry_allowed':False}
    put('capture-execution-receipt.json',receipt)
    receipt['ledger']=append({'record_type':'CONDITIONAL_VALIDATION_CAPTURE_TERMINAL',**receipt})
    put('capture-delivery-receipt.json',receipt)
    print(json.dumps(receipt,indent=2))
sys.exit(result_code)
