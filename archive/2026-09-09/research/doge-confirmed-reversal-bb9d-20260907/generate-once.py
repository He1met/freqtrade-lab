import json, re, urllib.request
from pathlib import Path

r = Path(__file__).parent
receipt = r / 'generation-created.json'
assert not receipt.exists(), 'One generation only'
base = 'http://127.0.0.1:8798'
html = urllib.request.urlopen(base + '/console').read().decode()
token = re.search(r'name="csrf-token" content="([^"]+)"', html).group(1)
code = (r / 'DogeConfirmedShockReversal3D-v2.py').read_text()
idea = 'Return the following frozen strategy as code_text EXACTLY, byte-for-byte including trailing newline. Do not change or optimize it. Use no tools. Explain limitations separately.\n' + code
assert len(idea) <= 4096
payload = dict(profile_id='issue98-doge-confirmed-reversal-v1', idea=idea,
               strategy_family='doge_confirmed_shock_reversal_3d_v1',
               expected_failure_mode='Known short-horizon reversal family improvement; may fail after costs, sparse signals, regime dependence, or stoploss. Frozen single baseline only.')
request_path = r / 'generation-request.json'
assert not request_path.exists(), 'Request already attempted; inspect, never repeat'
request_path.write_text(json.dumps(payload, ensure_ascii=False) + '\n')
req = urllib.request.Request(base + '/api/generations', data=json.dumps(payload).encode(),
    headers={'Content-Type':'application/json','Origin':base,'X-CSRF-Token':token}, method='POST')
with urllib.request.urlopen(req, timeout=60) as response:
    result = response.read()
receipt.write_bytes(result)
print(result.decode())
