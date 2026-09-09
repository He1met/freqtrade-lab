"""Single selected historical catalog group; no archive download or retry."""
import importlib.util
import json
from pathlib import Path
from scripts import fetch_okx_profile_data as producer

root=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('existing_budget','/Users/shenjianpeng/.codex/runs/freqtrade-lab/issue-90-xlm-sma90-v1/acquire_with_budget.py')
b=importlib.util.module_from_spec(spec); spec.loader.exec_module(b)
attempt=sum(json.loads(l)['event']=='ATTEMPT_BEFORE_NETWORK' for l in (root/'requests.jsonl').read_text().splitlines())+1
assert attempt <=16
months=[(2021,m) for m in range(1,7)]
payload={'dateQuery':{'begin':str(producer._archive_month_bounds(*months[0])[0]),'dateAggrType':'monthly','end':str(producer._archive_month_bounds(*months[-1])[1])},'instQueryParam':{'instFamilyList':['ATOM-USDT']},'instType':'SWAP','module':'3'}
with (root/'requests.jsonl').open('ab') as log:
    b.persist(log, {'event':'ATTEMPT_BEFORE_NETWORK','attempt':attempt,'method':'POST','endpoint':producer.ARCHIVE_CATALOG_URL,'payload':payload})
    try:
        raw,headers=producer.archive_http_request('POST',producer.ARCHIVE_CATALOG_URL,body=producer.canonical_bytes(payload))
        b.persist(log, {'event':'ATTEMPT_RETURNED','attempt':attempt,'status_code':200})
        value=producer._strict_catalog_response(raw)
        result={'requested_months':months,'response_sha256':producer.sha256(raw),'catalog':value,'zip_downloads':0}
        (root/'catalog-202101-202106.json').write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps(result,indent=2))
    except BaseException as error:
        b.persist(log, {'event':'ATTEMPT_FAILED','attempt':attempt,'error_type':type(error).__name__})
        print(json.dumps({'status':'CATALOG_REQUEST_FAILED','error_type':type(error).__name__,'message':str(error)[:180],'automatic_retry':False}))
