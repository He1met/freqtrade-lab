"""Issue 58 bounded funding-integrity audit; never constructs a research runtime."""
import ast
import base64
import collections
import csv
import hashlib
import http.client
import io
import json
import math
import sys
import time
import zipfile
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
SOURCE = Path('/Users/shenjianpeng/.codex/worktrees/ff25/freqtrade-lab/scripts/fetch_okx_profile_data.py')
source_raw = SOURCE.read_bytes()
source = ast.parse(source_raw)
names = {'ArchiveCatalogRateLimited', '_validate_archive_endpoint', '_receipt_headers',
         'archive_http_request', '_strict_catalog_response', '_month_after',
         '_catalog_group_label', '_catalog_retry_delay', '_catalog_attempt_receipt',
         '_request_archive_catalog', '_archive_catalog_group', '_archive_names',
         '_archive_month_bounds', '_parse_funding_archive', '_configured',
         '_archive_months', '_archive_month_groups', 'fetch_archive_funding_history',
         'validate_funding_history'}
nodes = [n for n in source.body if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name in names]
constants = {'FUNDING_INTERVAL_MS', 'FUNDING_ARCHIVE_TIMESTAMP_NORMALIZATION',
             'MAX_FUNDING_ARCHIVE_TIMESTAMP_DRIFT_MS', 'ARCHIVE_CATALOG_HOST',
             'ARCHIVE_CATALOG_PATH', 'ARCHIVE_CATALOG_URL', 'ARCHIVE_ASSET_HOST',
             'ARCHIVE_ASSET_PREFIX', 'ARCHIVE_QUERY', 'ARCHIVE_TIMEZONE', 'ARCHIVE_CSV_HEADER',
             'MAX_ARCHIVE_CATALOG_BYTES', 'MAX_ARCHIVE_ZIP_BYTES', 'MAX_ARCHIVE_CSV_BYTES',
             'MAX_ARCHIVE_CATALOG_MONTHS', 'ARCHIVE_CATALOG_THROTTLE_SECONDS',
             'ARCHIVE_CATALOG_RETRY_FALLBACK_SECONDS', 'ARCHIVE_CATALOG_RETRY_MAX_SECONDS',
             'RECEIPT_HEADERS'}
assigns = [n for n in source.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id in constants for t in n.targets)]
assert {n.name for n in nodes} == names
canonical_bytes = lambda x: (json.dumps(x, allow_nan=False, sort_keys=True, separators=(',', ':'))+'\n').encode()
sha256 = lambda x: hashlib.sha256(x).hexdigest()
exec(compile(ast.Module(body=assigns+nodes, type_ignores=[]), str(SOURCE), 'exec'))
# In-memory helper context only; no Profile/database/configuration entrypoint invoked.
PROFILE_ACQUISITION = {'audit_only': True}
DATA_START = datetime(2021,11,2,tzinfo=UTC)
SEARCH_START = datetime(2022,1,1,tzinfo=UTC)
DEVELOPMENT_START = datetime(2023,1,1,tzinfo=UTC)
DATA_END = datetime(2024,1,1,tzinfo=UTC)
DATA_START_MS = MARK_START_MS = int(DATA_START.timestamp()*1000)
DATA_END_MS = int(DATA_END.timestamp()*1000)
SYMBOL = 'SOL/USDT:USDT'
INSTRUMENT_ID = 'SOL-USDT-SWAP'
PAIR_FAMILY = 'SOL-USDT'
FUTURES_TIMEFRAME = '1d'

def save(name, data):
    path = ROOT/name
    with path.open('xb') as f:
        f.write(data)
    return {'file':name, 'bytes':len(data), 'sha256':sha256(data)}

def utc(ts):
    return datetime.fromtimestamp(ts/1000,UTC).isoformat(timespec='milliseconds')

def audit(entry, suffix=''):
    year, month, url, archive_name, csv_name = entry
    # An explicit stop before fetching a file containing protected funding values.
    assert (year,month) < (2024,1)
    raw, headers = archive_http_request('GET',url)
    raw_record=save(archive_name+suffix,raw)
    assert headers.get('content-type','').lower().startswith('application/zip')
    rows, parsed_receipt = _parse_funding_archive(raw,archive_name=archive_name,csv_name=csv_name)
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        csv_raw=z.read(csv_name)
    fields=list(csv.reader(io.StringIO(csv_raw.decode('utf8')),strict=True))[1:]
    assert all(Decimal(f[1]).is_finite() for f in fields)
    timestamps=[int(r['timestamp']) for r in rows]
    assert all(t < DATA_END_MS for t in timestamps)
    offsets=[t%FUNDING_INTERVAL_MS for t in timestamps]
    floored=[t-o for t,o in zip(timestamps,offsets)]
    start=_archive_month_bounds(year,month)[0]
    nxt=_month_after((year,month))
    stop=_archive_month_bounds(*nxt)[0]
    expected=list(range(start,stop,FUNDING_INTERVAL_MS))
    outside=[i+2 for i,t in enumerate(timestamps) if not start <= t < stop]
    anomalies=[{'csv_line':i+2,'instrument':fields[i][0],'raw_timestamp':fields[i][2],
                'raw_utc':utc(t),'offset_ms':offsets[i],'floor_utc':utc(floored[i])}
               for i,t in enumerate(timestamps) if offsets[i]>2000 or not start <= t < stop]
    gaps=collections.Counter(b-a for a,b in zip(timestamps,timestamps[1:]))
    selected=[t for t in floored if int(SEARCH_START.timestamp()*1000)<=t<DATA_END_MS]
    result={
      'month':f'{year:04d}-{month:02d}', 'url':url,'retrieved_at_utc':datetime.now(UTC).isoformat(),
      'raw':raw_record,'headers':headers,**parsed_receipt,'member_count':1,
      'instruments':sorted(set(f[0] for f in fields)), 'timestamp_type':'ASCII digit string',
      'timestamp_digits':dict(collections.Counter(len(f[2]) for f in fields)),
      'timestamp_unit':'milliseconds since Unix epoch; yields matching 2022/2023 UTC+08 archive months',
      'offset_distribution_ms':dict(sorted(collections.Counter(offsets).items())),
      'raw_adjacent_delta_distribution_ms':dict(sorted(gaps.items())),
      'raw_duplicates':len(timestamps)-len(set(timestamps)),
      'raw_order':'ascending' if all(a<b for a,b in zip(timestamps,timestamps[1:])) else 'NOT_STRICT_ASCENDING',
      'raw_grid_missing':len(set(expected)-set(timestamps)),
      'raw_grid_extra':len(set(timestamps)-set(expected)),
      'local_month_outside_lines':outside,'all_rates_finite':True,
      'floor_diagnostic_only':{'missing':len(set(expected)-set(floored)),
          'extra':len(set(floored)-set(expected)),'duplicates':len(floored)-len(set(floored)),
          'exact_expected_grid':sorted(floored)==expected,'selected_rows':len(selected)},
      'current_producer_month_verdict':'REJECT_TIMESTAMP_DRIFT' if anomalies else 'PASS_MONTH_CHECKS',
      'first_row':{'csv_line':2,'timestamp':str(timestamps[0]),'utc':utc(timestamps[0])},
      'last_row':{'csv_line':len(rows)+1,'timestamp':str(timestamps[-1]),'utc':utc(timestamps[-1])},
      'anomalies':anomalies,
    }
    save(f'{year:04d}-{month:02d}{suffix}.json',canonical_bytes(result))
    print(json.dumps({k:result[k] for k in ('month','raw','csv_rows','offset_distribution_ms','floor_diagnostic_only','current_producer_month_verdict','anomalies')}),flush=True)
    return result

if __name__=='__main__':
    mode=sys.argv[1]
    receipt=[]
    original=archive_http_request
    catalog_raw=[]
    def captured(method,url,*,body=None):
        data,headers=original(method,url,body=body)
        if method=='POST':
            stamp=f'catalog-{mode}-{len(catalog_raw)+1}'
            catalog_raw.append({'request':save(stamp+'-request.json',body),'response':save(stamp+'-response.json',data)})
        return data,headers
    archive_http_request=captured
    if mode=='march':
        entry=_archive_catalog_group([(2022,3)],receipt)[0]
        a=audit(entry)
        b=audit(entry,'.repeat')
        save('march-retrieval.json',canonical_bytes({'requests':receipt,'catalog_raw':catalog_raw,
          'source_sha256':sha256(source_raw),'helper_names':sorted(names),
          'repeat_identical':a['raw']['sha256']==b['raw']['sha256']}))
    elif mode=='remaining':
        months=[m for m in _archive_months() if m<(2024,1)]
        entries=[e for i in range(0,len(months),6) for e in _archive_catalog_group(months[i:i+6],receipt)]
        save('remaining-catalog.json',canonical_bytes({'requests':receipt,'catalog_raw':catalog_raw,'entries':entries,'required_months':_archive_months()}))
        for e in entries:
            if (e[0],e[1])!=(2022,3):
                audit(e)
    else:
        raise ValueError(mode)
