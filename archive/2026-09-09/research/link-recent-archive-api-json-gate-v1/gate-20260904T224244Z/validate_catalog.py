import pathlib,json,hashlib,urllib.parse
from decimal import Decimal
ROOT=pathlib.Path(__file__).resolve().parent
raw=(ROOT/'catalog.raw').read_bytes(); x=json.loads(raw)
assert x['code']=='0' and len(x['data'])==1
data=x['data'][0]; assert data['dateAggrType']=='daily' and len(data['details'])==1
detail=data['details'][0]
assert detail['instFamily']=='LINK-USDT' and detail['instType']=='SWAP'
assert detail['dateRangeStart']==detail['dateRangeEnd']=='1780848000000'
assert len(detail['groupDetails'])==1
g=detail['groupDetails'][0]; assert g['dateTs']=='1780848000000'
assert g['filename']=='LINK-USDT-SWAP-trades-2026-06-08.zip'
u=urllib.parse.urlsplit(g['url'])
assert u.scheme=='https' and u.hostname=='static.okx.com' and u.port in [None,443]
assert not u.username and not u.password and not u.fragment
assert pathlib.PurePosixPath(u.path).name==g['filename']
assert '/trades/daily/20260608/' in u.path
size=Decimal(g['sizeMB']); assert size.is_finite() and size>0 and size*1048576<=16777216
result={'status':'PASS_CATALOG_METADATA_ONLY','url':g['url'],'filename':g['filename'],'sizeMB':g['sizeMB'],
        'size_upper_bound_bytes_conservative_MiB':str(size*1048576),'catalog_response_sha256':hashlib.sha256(raw).hexdigest(),
        'instrument':'LINK-USDT-SWAP','directory_day_UTC_plus_8':'2026-06-08','request_count':1}
(ROOT/'catalog-target.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
