"""One metadata request using the existing execution budget guard."""
import importlib.util
import json
from pathlib import Path
from datetime import datetime, timezone
import requests

root = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('existing_budget', '/Users/shenjianpeng/.codex/runs/freqtrade-lab/issue-90-xlm-sma90-v1/acquire_with_budget.py')
budget = importlib.util.module_from_spec(spec)
spec.loader.exec_module(budget)
budget.MAX_ATTEMPTS = 16
with (root / 'requests.jsonl').open('xb') as log, requests.Session() as session:
    with budget.bounded_requests(log, seconds=45) as state:
        response = session.get('https://www.okx.com/api/v5/public/instruments', params={'instType':'SWAP','instId':'ATOM-USDT-SWAP'}, headers={'User-Agent':'freqtrade-lab-contract-metadata-v1','Accept':'application/json'}, allow_redirects=False, timeout=30)
        response.raise_for_status()
        value = response.json()
        assert value['code'] == '0' and len(value['data']) == 1
        fields = ('instId','instType','instFamily','state','listTime','contTdSwTime','expTime','settleCcy','ctType')
        record = {k:value['data'][0].get(k) for k in fields}
        assert record['instId'] == 'ATOM-USDT-SWAP'
        record['response_sha256'] = budget.hashlib.sha256(response.content).hexdigest()
        record['retrieved_at'] = datetime.now(timezone.utc).isoformat()
        (root/'instrument-metadata.json').write_text(json.dumps(record, indent=2)+'\n')
        print(json.dumps(record))
