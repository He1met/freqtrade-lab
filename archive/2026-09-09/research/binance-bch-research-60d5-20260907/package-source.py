"""Transparent retained-response packaging; calls existing source compiler only."""
from pathlib import Path
import sys,json,hashlib
sys.path.insert(0,'/Users/shenjianpeng/.codex/worktrees/60d5/freqtrade-lab')
from lab.binance_source import retained_responses,compile_source
from lab.bounded_research import canonical
r=Path(__file__).parent
old=Path('/Users/shenjianpeng/.codex/runs/freqtrade-lab/native-futures-01a0777f-20260907')
assert (r/'d-capture-complete.json').exists()
agg=r/'aggregated-retained';agg.mkdir(mode=0o700);raw=agg/'raw';raw.mkdir(mode=0o700)
sha=lambda b:hashlib.sha256(b).hexdigest()
allrows=[];mappings=[];batch=[];market={}
for label,receiptpath,rawpath in [('S',old/'native-full-s-http-receipts.jsonl',old/'native-full-s-raw'),('D',r/'d-capture/http-receipts.jsonl',r/'d-capture/raw')]:
 rb=receiptpath.read_bytes();records=[json.loads(l) for l in rb.splitlines()]
 for rec in records:
  name=rec['body_file'];assert Path(name).name==name
  data=(rawpath/name).read_bytes();assert len(data)==rec['bytes'] and sha(data)==rec['sha256'] and rec.get('error_class') is None
  newname=label+'-'+name
  with (raw/newname).open('xb') as f:f.write(data)
  copied=dict(rec,body_file=newname);allrows.append(copied)
  mappings.append({'batch':label,'original_receipts':str(receiptpath),'original_receipts_sha256':sha(rb),'original_body_file':name,'packaged_body_file':newname,'unchanged_body_sha256':sha(data),'unchanged_request_url':rec['url']})
  if '/exchangeInfo' in rec['url']:
   obj=json.loads(data);selected=[m for m in obj['symbols'] if m['symbol']=='BCHUSDT'];assert len(selected)==1;market[label]=selected[0]
 batch.append({'batch':label,'receipt_sha256':sha(rb),'responses':len(records),'decoded_bytes':sum(x['bytes'] for x in records)})
receipts=agg/'http-receipts.jsonl';receipts.write_bytes(b''.join(canonical(x)+b'\n' for x in allrows))
manifest={'classification':'TRANSPARENT_TWO_CAPTURE_BATCHES_ONE_FROZEN_SOURCE','protocol_sha256':sha((r/'frozen-protocol.md').read_bytes()),'batches':batch,'mappings':mappings,'aggregated_receipts_sha256':sha(receipts.read_bytes()),'market_snapshot_binding':'D newest observed metadata, no silent mixing','historical_market_precision_and_tiers':'UNKNOWN','S_BCH_market_sha256':sha(canonical(market['S'])),'D_BCH_market_sha256':sha(canonical(market['D'])),'market_changed_keys':[k for k in sorted(set(market['S'])|set(market['D'])) if market['S'].get(k)!=market['D'].get(k)]}
(agg/'aggregation-manifest.json').write_bytes(canonical(manifest))
# Existing verifier enforces identical duplicated records; no value selection.
rows,latest=retained_responses(receipts,raw);assert latest==market['D']
(r/'source-aggregation-qc.json').write_bytes(canonical({'classification':'IDENTITY_CONTINUITY_SOURCE_QC_ONLY','duplicate_conflicts':'NONE','batches':batch,'market_changed_keys':manifest['market_changed_keys'],'bound_market':'D','historical_applicability':'UNKNOWN','aggregation_manifest_sha256':sha((agg/'aggregation-manifest.json').read_bytes())}))
result=compile_source(r/'complete-source',receipts,raw,json.loads((r/'frozen-source-contract.json').read_bytes()))
(r/'source-publication.json').write_bytes(canonical(result));print(json.dumps(result))
