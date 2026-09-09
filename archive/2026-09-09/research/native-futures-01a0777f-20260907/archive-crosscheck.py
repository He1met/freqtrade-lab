import csv
import hashlib
import io
import json
import urllib.request
import zipfile
from pathlib import Path

root = Path(__file__).resolve().parent
url = 'https://data.binance.vision/data/futures/um/monthly/fundingRate/BCHUSDT/BCHUSDT-fundingRate-2023-08.zip'
receipts = []
for suffix in ['.CHECKSUM','']:
    with urllib.request.urlopen(url+suffix,timeout=30) as r:
        b=r.read(10000001)
        assert len(b)<=10000000
        name='funding-202308'+('.CHECKSUM' if suffix else '.zip')
        (root/name).write_bytes(b)
        receipts.append({'url':r.url,'status':r.status,'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(),'file':name})
(root/'archive-receipts.json').write_text(json.dumps(receipts,indent=2)+'\n')
raw=(root/'funding-202308.zip').read_bytes()
assert hashlib.sha256(raw).hexdigest()==(root/'funding-202308.CHECKSUM').read_text().split()[0]
with zipfile.ZipFile(io.BytesIO(raw)) as z:
    assert len(z.infolist())==1
    info=z.infolist()[0]
    assert info.file_size<20000000 and not info.is_dir()
    rows=list(csv.DictReader(io.TextIOWrapper(z.open(info),encoding='utf-8')))
times=[int(r['calc_time']) for r in rows]
assert all(1690848000000<=t<1693526400000 for t in times)
api=json.loads((root/'native-sample-raw/0002.txt').read_text())
from decimal import Decimal
matches=sum(int(r['calc_time'])==int(a['fundingTime']) and Decimal(r['last_funding_rate'])==Decimal(a['fundingRate']) for r,a in zip(rows,api))
result={'rows':len(rows),'columns':list(rows[0]),'interval_hours':sorted(set(r['funding_interval_hours'] for r in rows)),'exact_time_and_rate_matches':matches,'api_rows':len(api),'checksum_verified':True}
(root/'archive-crosscheck.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result))
