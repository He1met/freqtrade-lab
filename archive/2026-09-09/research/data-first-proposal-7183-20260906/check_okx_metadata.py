"""Two official metadata/documentation requests, no market values."""
import importlib.util
import json
from pathlib import Path
from html.parser import HTMLParser
import requests

root=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('existing_budget','/Users/shenjianpeng/.codex/runs/freqtrade-lab/issue-90-xlm-sma90-v1/acquire_with_budget.py')
b=importlib.util.module_from_spec(spec); spec.loader.exec_module(b)
targets=[('instrument','https://www.okx.com/api/v5/public/instruments?instType=SPOT&instId=ATOM-USDT'),('history-doc','https://app.okx.com/docs-v5/en/')]
for label,url in targets:
    attempt=1+sum(json.loads(l)['event']=='ATTEMPT_BEFORE_NETWORK' for l in (root/'requests.jsonl').read_text().splitlines())
    assert attempt<=20
    with (root/'requests.jsonl').open('ab') as log, requests.Session() as session:
        assert session.get_adapter(url).max_retries.total==0
        b.persist(log,{'event':'ATTEMPT_BEFORE_NETWORK','attempt':attempt,'url':url})
        try:
            r=session.get(url,headers={'User-Agent':'freqtrade-lab-metadata-v1'},allow_redirects=False,timeout=30)
            b.persist(log,{'event':'ATTEMPT_RETURNED','attempt':attempt,'status_code':r.status_code})
            r.raise_for_status(); assert r.status_code==200
            if label=='instrument':
                value=r.json(); assert value['code']=='0' and len(value['data'])==1
                fields=('instId','instType','state','listTime','contTdSwTime','baseCcy','quoteCcy','lotSz','minSz','tickSz')
                data={k:value['data'][0].get(k) for k in fields}; assert data['instId']=='ATOM-USDT'
            else:
                class Text(HTMLParser):
                    def __init__(self):super().__init__();self.parts=[];self.skip=0
                    def handle_starttag(self,t,a):
                        if t in ('pre','script','style'):self.skip+=1
                    def handle_endtag(self,t):
                        if t in ('pre','script','style'):self.skip=max(0,self.skip-1)
                    def handle_data(self,d):
                        if not self.skip and d.strip():self.parts.append(d.strip())
                p=Text();p.feed(r.text); text='\n'.join(p.parts)
                i=text.find('GET /api/v5/market/history-candles')
                assert i>=0
                data={'section':text[max(0,i-850):i+2100]}
            result={'url':url,'sha256':b.hashlib.sha256(r.content).hexdigest(),'metadata':data}
            (root/(label+'.json')).write_text(json.dumps(result,indent=2)+'\n')
            print(json.dumps(result,indent=2))
        except BaseException:
            b.persist(log,{'event':'ATTEMPT_FAILED','attempt':attempt});raise
