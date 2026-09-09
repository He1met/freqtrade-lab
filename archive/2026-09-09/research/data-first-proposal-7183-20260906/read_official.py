"""Bounded official documentation reads only, no market endpoints."""
import importlib.util
import json
from pathlib import Path
import requests

root=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('existing_budget','/Users/shenjianpeng/.codex/runs/freqtrade-lab/issue-90-xlm-sma90-v1/acquire_with_budget.py')
b=importlib.util.module_from_spec(spec); spec.loader.exec_module(b)
url='https://raw.githubusercontent.com/binance/binance-public-data/master/README.md'
with (root/'requests.jsonl').open('xb') as log, requests.Session() as session:
    assert session.get_adapter(url).max_retries.total==0
    b.persist(log,{'event':'ATTEMPT_BEFORE_NETWORK','attempt':1,'url':url})
    try:
        r=session.get(url,allow_redirects=False,timeout=30)
        b.persist(log,{'event':'ATTEMPT_RETURNED','attempt':1,'status_code':r.status_code})
        r.raise_for_status(); assert r.status_code==200
        (root/'binance-public-data-readme.md').write_bytes(r.content)
        print(json.dumps({'url':url,'sha256':b.hashlib.sha256(r.content).hexdigest(),'bytes':len(r.content)}))
        print('\n'.join(line for line in r.text.splitlines() if any(k in line.lower() for k in ['monthly','daily','checksum','2025','data.binance','s3','kline'])))
    except BaseException:
        b.persist(log,{'event':'ATTEMPT_FAILED','attempt':1}); raise
