import json, re, urllib.request
from pathlib import Path

r = Path(__file__).parent
receipt = r / 'generation-created.json'
assert not receipt.exists(), 'One generation only'
base = 'http://127.0.0.1:8801'
html = urllib.request.urlopen(base + '/console').read().decode()
token = re.search(r'name="csrf-token" content="([^"]+)"', html).group(1)
code = (r / 'BnbDailyShockContinuation48H.py').read_text()
idea = 'Return the following frozen strategy as code_text EXACTLY, byte-for-byte including trailing newline. Do not change or optimize it. Use no tools. Explain limitations separately.\n' + code
assert len(idea) <= 4096
payload = dict(profile_id='issue104-bnb-daily-shock-continuation-48h-v1', idea=idea,
               strategy_family='bnb_daily_shock_continuation_48h_v1',
               expected_failure_mode='Known short-horizon shock continuation family test; may fail after costs, sparse signals, regime dependence, or stoploss. Frozen single baseline only.')
request_path = r / 'generation-request.json'
assert not request_path.exists(), 'Request already attempted; inspect, never repeat'
request_path.write_text(json.dumps(payload, ensure_ascii=False) + '\n')
req = urllib.request.Request(base + '/api/generations', data=json.dumps(payload).encode(),
    headers={'Content-Type':'application/json','Origin':base,'X-CSRF-Token':token}, method='POST')
with urllib.request.urlopen(req, timeout=60) as response:
    result = response.read()
receipt.write_bytes(result)
print(result.decode())
