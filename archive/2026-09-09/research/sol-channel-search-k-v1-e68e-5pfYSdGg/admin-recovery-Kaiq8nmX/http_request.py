"""Record real loopback Research Console requests; no database bypass."""
import json,re,sys,urllib.request,urllib.error
from pathlib import Path
ROOT=Path(__file__).resolve().parent
def base():
    return re.search(r'Research Console: (http://127\.0\.0\.1:\d+)/console',(ROOT/'console.log').read_text()).group(1)
def request(path,payload=None,label=None):
    origin=base(); headers={}
    if payload is not None:
        html=urllib.request.urlopen(origin+'/console').read().decode()
        token=re.search(r'<meta name="csrf-token" content="([^"]+)"',html).group(1)
        headers={'Origin':origin,'X-CSRF-Token':token,'Content-Type':'application/json'}
    data=None if payload is None else json.dumps(payload).encode()
    req=urllib.request.Request(origin+path,data=data,headers=headers)
    try:
        with urllib.request.urlopen(req,timeout=30) as response: status=response.status;raw=response.read()
    except urllib.error.HTTPError as response: status=response.code;raw=response.read()
    value=json.loads(raw)
    if label:
        target=ROOT/'http-evidence'/(label+'.json');target.parent.mkdir(exist_ok=True,mode=0o700)
        assert not target.exists()
        target.write_text(json.dumps({'http_status':status,'path':path,'request':payload,'response':value},indent=2)+'\n')
    return status,value
if __name__=='__main__':
    status,value=request(sys.argv[1],None if len(sys.argv)<4 else json.loads(sys.argv[3]),sys.argv[2])
    print(json.dumps({'http_status':status,'response':value},ensure_ascii=False))
