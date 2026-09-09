"""Issue 87 one-shot budget envelope around the unchanged project producer."""
from pathlib import Path
import importlib.util,json,sys,time,signal,hashlib
ROOT=Path('/Users/shenjianpeng/.codex/runs/freqtrade-lab/issue-87-trx-daily-pullback-v1')
REPO=Path('/Users/shenjianpeng/.codex/worktrees/42b5/freqtrade-lab')
sys.path.insert(0,str(REPO))
spec=importlib.util.spec_from_file_location('issue87_producer',REPO/'scripts/fetch_okx_profile_data.py');p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)
claim=ROOT/'acquisition-once.claim';claim.open('x').write('One authorized acquisition; no retry.\n')
started=time.monotonic();events=[];seen=set();pages=0
original_guard=p.install_request_guard
class BudgetStop(RuntimeError):pass
def save():
 (ROOT/'http-budget-receipt.json').write_text(json.dumps({'elapsed_seconds':time.monotonic()-started,'max_requests':20,'max_candle_pages':8,'max_seconds':900,'retry_allowed':False,'requests':events},indent=2)+'\n')
def guard(exchange):
 original_guard(exchange)
 exchange.options['maxRetriesOnFailure']=0
 for adapter in exchange.session.adapters.values():
  if adapter.max_retries.total not in (0,False):raise BudgetStop('HTTP adapter retries are not zero')
 request=exchange.session.request
 def counted(method,url,*args,**kwargs):
  global pages
  if time.monotonic()-started>=900 or len(events)>=20:raise BudgetStop('total acquisition budget exhausted')
  if url in seen:raise BudgetStop('duplicate HTTP URL blocked; retry forbidden')
  is_candle='/api/v5/market/history-candles?' in url
  if is_candle and pages>=8:raise BudgetStop('candle page budget exhausted')
  seen.add(url);pages+=int(is_candle)
  e={'sequence':len(events)+1,'method':method,'url':url,'status':'STARTED'};events.append(e);save()
  try:
   resp=request(method,url,*args,**kwargs);e['http_status']=resp.status_code;e['status']='RETURNED';return resp
  except BaseException as exc:e['status']='FAILED';e['error_type']=type(exc).__name__;raise
  finally:save()
 exchange.session.request=counted
p.install_request_guard=guard
def alarm(*_):raise BudgetStop('900 second acquisition wall limit')
signal.signal(signal.SIGALRM,alarm);signal.alarm(900)
sys.argv=['fetch_okx_profile_data.py','--output-root',str(ROOT/'source-acquisition'),'--window-spec',str(ROOT/'window-spec.json'),'--profile-database',str(ROOT/'lab.sqlite'),'--profile-id','issue87-trx-spot-1d','--pre-roll-candles','10','--economic-gate',str(ROOT/'economic-gate.json'),'--single-baseline',str(ROOT/'single-baseline.json')]
try:
 p.main()
 status={'status':'SOURCE_PRODUCER_SUCCEEDED','http_requests':len(events),'candle_pages':pages}
except BaseException as exc:
 status={'status':'BLOCKED_DATA','error_type':type(exc).__name__,'message':str(exc)[:500],'http_requests':len(events),'candle_pages':pages,'retry_allowed':False}
 (ROOT/'acquisition-status.json').write_text(json.dumps(status,indent=2)+'\n');print(json.dumps(status));raise SystemExit(2)
finally:signal.alarm(0);save()
(ROOT/'acquisition-status.json').write_text(json.dumps(status,indent=2)+'\n');print(json.dumps(status))
