import json,re,sys,urllib.request,urllib.error
from pathlib import Path
ROOT=Path(__file__).resolve().parent
BASE="http://127.0.0.1:49469"
def request(path,payload=None,label=None):
 headers={}
 if payload is not None:
  html=urllib.request.urlopen(BASE+"/console").read().decode()
  token=re.search(r'<meta name="csrf-token" content="([^"]+)"',html).group(1)
  headers={"Origin":BASE,"X-CSRF-Token":token,"Content-Type":"application/json"}
 data=None if payload is None else json.dumps(payload).encode()
 req=urllib.request.Request(BASE+path,data=data,headers=headers)
 try:
  with urllib.request.urlopen(req,timeout=30) as response: status=response.status;raw=response.read()
 except urllib.error.HTTPError as response: status=response.code;raw=response.read()
 value=json.loads(raw)
 if label:
  p=ROOT/"http-evidence"/(label+".json")
  if p.exists(): raise RuntimeError("Evidence name already exists")
  p.write_text(json.dumps({"http_status":status,"path":path,"request":payload,"response":value},indent=2)+"\n")
 return status,value
if __name__=="__main__":
 status,value=request(sys.argv[1],None if len(sys.argv)<4 else json.loads(sys.argv[3]),sys.argv[2])
 print(json.dumps({"http_status":status,"response":value},ensure_ascii=False))
