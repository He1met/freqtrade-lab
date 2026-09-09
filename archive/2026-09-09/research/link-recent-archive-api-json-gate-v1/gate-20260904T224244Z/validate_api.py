"""Validate time first; never print sampled prices or sizes."""
import json,pathlib,hashlib,datetime
from decimal import Decimal
ROOT=pathlib.Path(__file__).resolve().parent
raw=(ROOT/'api.raw').read_bytes(); x=json.loads(raw)
receipt={'status':'FAILED_STOP','request_count':1,'raw_sha256':hashlib.sha256(raw).hexdigest()}
try:
    assert x['code']=='0','API_CODE_NON_SUCCESS'
    rows=x['data']; assert isinstance(rows,list) and len(rows)==100,'API_ROW_COUNT'
    times=[]
    for row in rows:
        ts=row['ts']; assert isinstance(ts,str) and ts.isdecimal() and len(ts)==13,'API_TIME_FORMAT'
        ts=int(ts); assert 1780848000000<=ts<1780934400000 and ts<1780905600000,'API_TIME_OUT_OF_FROZEN_RANGE'
        times.append(ts)
    ids=set(); sides=set(); normalized=[]
    for row in rows:
        assert row['instId']=='LINK-USDT-SWAP','API_INSTRUMENT'
        ident=row['tradeId']; assert isinstance(ident,str) and ident.isdecimal() and ident not in ids,'API_ID'
        ids.add(ident)
        assert row['side'] in ['buy','sell'],'API_SIDE'
        sides.add(row['side'])
        for field in ['px','sz']:
            d=Decimal(row[field]); assert d.is_finite() and d>0,'API_NONPOSITIVE_OR_NONFINITE'
        normalized.append({'instrument':row['instId'],'id':ident,'timestamp':int(row['ts']),
            'side':row['side'],'price':row['px'],'contracts_size':row['sz']})
    assert sides=={'buy','sell'},'API_BOTH_SIDES_REQUIRED'
    target=ROOT/'api-normalized.json'; target.write_text(json.dumps(normalized,indent=2)+'\n')
    receipt.update(status='PASS_FORMAT_ONLY',rows=100,unique_ids=100,sides=['buy','sell'],
                   actual_utc_min=datetime.datetime.fromtimestamp(min(times)/1000,datetime.timezone.utc).isoformat(),
                   actual_utc_max_inclusive=datetime.datetime.fromtimestamp(max(times)/1000,datetime.timezone.utc).isoformat(),
                   normalized_sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
                   real_price_or_size_statistics='NOT_COMPUTED')
except Exception as e:
    receipt['error_type']=type(e).__name__; receipt['error']=str(e)
    raise
finally:
    (ROOT/'api-validation.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps(receipt,indent=2))
