"""One-shot bounded public HTTP acquisition, no retries or redirects."""
import datetime,hashlib,json,os,pathlib,sys,time,urllib.request,urllib.error
ROOT=pathlib.Path(__file__).resolve().parent
os.umask(0o077)
CATALOG='https://www.okx.com/api/v5/public/market-data-history?module=1&instType=SWAP&instFamilyList=LINK-USDT&dateAggrType=daily&begin=1780848000000&end=1780848000000'
API='https://www.okx.com/api/v5/market/history-trades?instId=LINK-USDT-SWAP&type=2&after=1780905600000&limit=100'
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        raise RuntimeError('REDIRECT_FORBIDDEN')
name=sys.argv[1]
assert json.loads((ROOT/'freeze-readback.json').read_text())['body_equal'] is True
if name=='catalog':
    url,limit,seconds=CATALOG,65536,30
elif name=='api':
    assert json.loads((ROOT/'catalog-freeze-readback.json').read_text())['body_equal'] is True
    url,limit,seconds=API,262144,30
elif name=='zip':
    assert json.loads((ROOT/'api-validation.json').read_text())['status']=='PASS_FORMAT_ONLY'
    url=json.loads((ROOT/'catalog-target.json').read_text())['url']
    limit,seconds=16777216,300
else: raise ValueError('unknown request')
assert time.time()<datetime.datetime(2026,9,5,0,42,44,tzinfo=datetime.timezone.utc).timestamp()
record={'request':name,'url':url,'max_bytes':limit,'timeout_seconds':seconds,'actual_attempts':1,'redirects':0,'automatic_retries':0,
        'started_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'status':'ATTEMPTED'}
with (ROOT/(name+'-request.json')).open('x') as f: json.dump(record,f,indent=2)
target=ROOT/(name+'.raw')
began=time.monotonic()
try:
    opener=urllib.request.build_opener(NoRedirect())
    with opener.open(urllib.request.Request(url,headers={'User-Agent':'bounded-public-data-gate/1','Accept-Encoding':'identity'}),timeout=seconds) as response:
        record['http_status']=response.status
        assert response.status==200,'HTTP_NON_SUCCESS'
        record['headers']=dict(response.headers.items())
        length=response.headers.get('Content-Length')
        if length is not None: assert int(length)<=limit,'DECLARED_BYTES_LIMIT'
        count=0
        with target.open('xb') as f:
            while True:
                assert time.monotonic()-began<seconds,'HTTP_TOTAL_TIME_LIMIT'
                part=response.read(min(65536,limit-count+1))
                if not part: break
                count+=len(part)
                assert count<=limit,'ACTUAL_BYTES_LIMIT'
                f.write(part)
            f.flush(); os.fsync(f.fileno())
        record.update(status='RECEIVED',bytes=count,sha256=hashlib.sha256(target.read_bytes()).hexdigest())
except Exception as e:
    record.update(status='FAILED_STOP',error_type=type(e).__name__,error=str(e))
    raise
finally:
    record['elapsed_seconds']=time.monotonic()-began
    record['finished_at_utc']=datetime.datetime.now(datetime.timezone.utc).isoformat()
    (ROOT/(name+'-request.json')).write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps({k:v for k,v in record.items() if k not in ['headers','url']}))
