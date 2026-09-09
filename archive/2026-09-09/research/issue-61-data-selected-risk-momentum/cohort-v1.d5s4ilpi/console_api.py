from pathlib import Path
import json,re,urllib.request,urllib.error,sys
ROOT=Path(__file__).parent
ORIGIN=(ROOT/'console-url.txt').read_text()
def request(path,body=None,save=None):
 headers={}
 if body is not None:
  html=urllib.request.urlopen(ORIGIN+'/console').read().decode()
  token=re.search(r'<meta name="csrf-token" content="([^"]+)"',html).group(1)
  headers={'Origin':ORIGIN,'X-CSRF-Token':token,'Content-Type':'application/json'}
 req=urllib.request.Request(ORIGIN+path,data=None if body is None else json.dumps(body).encode(),headers=headers)
 try:
  with urllib.request.urlopen(req,timeout=60) as resp: status=resp.status; raw=resp.read()
 except urllib.error.HTTPError as e: status=e.code;raw=e.read()
 value=json.loads(raw)
 if save: (ROOT/save).write_text(json.dumps({'http_status':status,'body':value},indent=2))
 if status>=400:raise RuntimeError(json.dumps({'http_status':status,'body':value}))
 return value
if __name__=='__main__':
 value=request(sys.argv[1],None if len(sys.argv)<3 or sys.argv[2]=='-' else json.loads(Path(sys.argv[2]).read_text()),None if len(sys.argv)<4 else sys.argv[3]);print(json.dumps(value,indent=2))
