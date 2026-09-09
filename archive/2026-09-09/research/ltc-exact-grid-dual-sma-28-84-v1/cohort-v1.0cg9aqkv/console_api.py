import json, re, sys, urllib.request, urllib.error
from pathlib import Path
r=Path(__file__).resolve().parent
base=re.search(r'Research Console: (http://127\.0\.0\.1:\d+)/console',(r/'console.log').read_text()).group(1)
def call(method,path,data=None):
    headers={}
    body=None
    if method=='POST':
        page=urllib.request.urlopen(base+'/console').read().decode()
        token=re.search(r'<meta name="csrf-token" content="([^"]+)"',page).group(1)
        headers={'Content-Type':'application/json','Origin':base,'X-CSRF-Token':token}
        body=json.dumps(data).encode()
    req=urllib.request.Request(base+path,data=body,headers=headers,method=method)
    try:
        with urllib.request.urlopen(req,timeout=60) as response:status,raw=response.status,response.read()
    except urllib.error.HTTPError as exc:status,raw=exc.code,exc.read()
    try:value=json.loads(raw)
    except ValueError:value=raw.decode()
    return {'http_status':status,'body':value}
if __name__=='__main__':
    method,path,label=sys.argv[1:4]
    data=json.loads(Path(sys.argv[4]).read_text()) if len(sys.argv)>4 else None
    result=call(method,path,data)
    (r/(label+'.json')).write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n')
    print(json.dumps(result,ensure_ascii=False))
