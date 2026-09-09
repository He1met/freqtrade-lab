"""One official documentation request; persist only lifecycle/rule excerpts."""
import importlib.util
import json
from pathlib import Path
from html.parser import HTMLParser
import requests

root = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('existing_budget', '/Users/shenjianpeng/.codex/runs/freqtrade-lab/issue-90-xlm-sma90-v1/acquire_with_budget.py')
b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b)
attempt = sum(json.loads(l)['event'] == 'ATTEMPT_BEFORE_NETWORK' for l in (root/'requests.jsonl').read_text().splitlines()) + 1
assert attempt <= 16
url = 'https://app.okx.com/docs-v5/en/'
with (root/'requests.jsonl').open('ab') as log, requests.Session() as session:
    assert session.get_adapter(url).max_retries.total == 0
    b.persist(log, {'event':'ATTEMPT_BEFORE_NETWORK','attempt':attempt,'method':'GET','endpoint':url})
    try:
        response = session.get(url, allow_redirects=False, timeout=30)
        b.persist(log, {'event':'ATTEMPT_RETURNED','attempt':attempt,'status_code':response.status_code})
        response.raise_for_status()
        assert response.status_code == 200
        class Text(HTMLParser):
            def __init__(self): super().__init__(); self.parts=[]; self.skip=0
            def handle_starttag(self,t,a):
                if t in ('pre','script','style'): self.skip+=1
            def handle_endtag(self,t):
                if t in ('pre','script','style'): self.skip=max(0,self.skip-1)
            def handle_data(self,d):
                if not self.skip and d.strip(): self.parts.append(d.strip())
        p=Text(); p.feed(response.text); text='\n'.join(p.parts)
        excerpts=[]
        for key in ('contTdSwTime','realizedRate','fundingTime','collection frequency'):
            start=0
            for _ in range(2):
                i=text.find(key,start)
                if i<0: break
                excerpts.append({'term':key,'text':text[max(0,i-60):i+700]}); start=i+len(key)
        result={'url':url,'sha256':b.hashlib.sha256(response.content).hexdigest(),'excerpts':excerpts}
        (root/'official-doc-excerpts.json').write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps(result,indent=2))
    except BaseException:
        b.persist(log, {'event':'ATTEMPT_FAILED','attempt':attempt})
        raise
