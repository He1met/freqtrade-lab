from pathlib import Path
import json,hashlib,sqlite3,zipfile,sys,threading,http.client,fcntl,os
from datetime import datetime,timezone
from lab.research_console import create_research_console_server
r=Path(__file__).parent;h=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
def put(n,v):
 with (r/n).open('x') as f:json.dump(v,f,indent=2,sort_keys=True)
 return h(r/n)
a=json.loads((r/'s-economic-audit.json').read_bytes());p=Path(a['archive_path']);assert h(p)==a['archive_sha256']
with zipfile.ZipFile(p) as z:
 name=next(n for n in z.namelist() if n.endswith('.json') and not n.endswith('.meta.json') and '_config' not in n);n=json.loads(z.read(name))['strategy']['XrpWeeklyPersistentDirection']
assert n['starting_balance']==1000 and n['stake_amount']==250 and n['max_open_trades_setting']==1
assert all(t['leverage']==1 and not t['is_open'] for t in n['trades'])
wallet=dict(starting_balance=n['starting_balance'],configured_stake_amount=n['stake_amount'],actual_stake_min=min(t['stake_amount'] for t in n['trades']),actual_stake_max=max(t['stake_amount'] for t in n['trades']),actual_stake_note='Native lot-size rounding retained; no added capital',net_percentage_denominator=1000,trade_long=sum(not t['is_short'] for t in n['trades']),trade_short=sum(t['is_short'] for t in n['trades']),rejected_signals=n['rejected_signals'],final_balance=n['final_balance'])
c=sqlite3.connect('file:'+str(r/'lab.sqlite')+'?mode=ro',uri=True);c.row_factory=sqlite3.Row
tables=[v[0] for v in c.execute("select name from sqlite_master where type='table' and name not like 'sqlite_%'")];counts={t:c.execute('SELECT COUNT(*) FROM "'+t+'"').fetchone()[0] for t in tables};assert len(tables)==6
row=c.execute('select * from generation_runs where id=?',(a['campaign_id'],)).fetchone();response=json.loads(row['response_json']);assert response['status']=='SEARCH_TERMINATED_NO_FINALIST'
metadata=json.loads(c.execute('select metadata_json from candidates where id=?',(a['candidate_id'],)).fetchone()[0]);c.close()
server=create_research_console_server(r/'lab.sqlite',r/'s-console-runtime',r/'s-empty-development-context',port=0,artifact_root=r/'artifacts',search_root=r/'search-campaign',check_data_python=Path(sys.executable),freqtrade_python=Path(sys.executable),freqtrade_source=Path('/Users/shenjianpeng/.codex/runs/freqtrade-lab/issue-43-profile-driven-v1/freqtrade'),task_timeout_seconds=300)
try:
 threading.Thread(target=server.serve_forever,daemon=True).start();summaries=[]
 for path in ['/api/search-campaigns/'+a['campaign_id'],'/api/generations/'+a['campaign_id'],'/api/generations/c02a5545-9a0c-4217-8849-fe0ab6da4ef9']:
  co=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=30);co.request('GET',path);res=co.getresponse();body=json.loads(res.read());co.close()
  summaries.append(dict(path=path,http_status=res.status,status=body.get('status'),response_sha256=hashlib.sha256(json.dumps(body,sort_keys=True,separators=(',',':')).encode()).hexdigest()))
finally:server.research_console_controller.shutdown();server.shutdown();server.server_close()
record=dict(status='S_REJECTED_NO_FURTHER_EXECUTION',campaign_id=a['campaign_id'],candidate_id=a['candidate_id'],database_counts=counts,database_search_source=row['source'],database_search_status=row['status'],database_search_verdict=response['status'],console_http=summaries,wallet_and_positions=wallet,primary_market_calls=1,benchmark_calls=0,D_H_STRESS_calls=0,archive_sha256=h(p),search_terminal_sha256=h(r/'search-campaign/search-terminal.json'),source_sha256=a['source_sha256'],protocol_sha256=a['protocol_sha256'],economic_audit_sha256=h(r/'s-economic-audit.json'),capacity_attached=False,comparison_attached='cost_comparisons' in metadata,comparison_reason='Skipped benchmark after core failure; existing comparison importer requires finalist and both archives',D_accident_restriction='D market values exposed; not unseen validation data',H_source_acquired=False,remaining_open_items=['Capacity receipt is external only','Outer episode/block audit is external only','Comparison skipped by negative-terminal gate','No Development/Holdout/Stress or qualified strategy demonstrated','Issue107 remains OPEN pending supervisor acceptance'],recorded_at_utc=datetime.now(timezone.utc).isoformat())
receiptsha=put('s-final-delivery-receipt.json',record)
l=Path('/Users/shenjianpeng/Documents/freqtrade-lab-local/search-research-supervision-20260902/global-research-ledger.jsonl')
with Path(str(l)+'.lock').open('r+') as lock:
 fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);before=l.read_bytes();bs=hashlib.sha256(before).hexdigest()
 rec={**record,'record_type':'S_REJECTED_FINAL_DELIVERY','cohort_id':r.name,'receipt_sha256':receiptsha,'receipt_path':str(r/'s-final-delivery-receipt.json'),'previous_prefix_sha256':bs,'search_window_consumed':True,'no_replay':True}
 with l.open('ab') as f:
  if before and not before.endswith(b'\n'):f.write(b'\n')
  f.write(json.dumps(rec,sort_keys=True,separators=(',',':')).encode()+b'\n');f.flush();os.fsync(f.fileno())
 after=l.read_bytes();assert after.startswith(before);ledgerh=hashlib.sha256(after).hexdigest()
 put('s-final-ledger-receipt.json',dict(before_sha256=bs,after_sha256=ledgerh,old_prefix_preserved=True))
print(json.dumps(dict(wallet=wallet,database_counts=counts,console=summaries,receipt_sha256=receiptsha,ledger_sha256=ledgerh),sort_keys=True))
