"""Timestamp-first boundary selector authorized by Issue 58 supervisor.

Never invokes the producer's full CSV rate parser on the boundary archive.
Only selected pre-cutoff rates are indexed, converted, or validated.
"""
import audit as a
import csv
import io
import json
import zipfile
from decimal import Decimal

def select(csv_raw, cutoff, rate_parser=Decimal):
    reader=csv.reader(io.StringIO(csv_raw.decode('utf8','strict')),strict=True)
    assert next(reader)==a.ARCHIVE_CSV_HEADER
    selected=[]
    skipped=0
    for line,fields in enumerate(reader,2):
        assert len(fields)==3
        assert fields[0]==a.INSTRUMENT_ID
        raw_timestamp=fields[2]
        assert raw_timestamp.isascii() and raw_timestamp.isdigit()
        timestamp=int(raw_timestamp)
        if timestamp>=cutoff:
            skipped+=1
            continue
        assert timestamp>=cutoff-a.FUNDING_INTERVAL_MS
        rate=rate_parser(fields[1])
        assert rate.is_finite()
        selected.append({'csv_line':line,'raw_timestamp':raw_timestamp,
                         'raw_utc':a.utc(timestamp),'offset_ms':timestamp%a.FUNDING_INTERVAL_MS,
                         'floor_utc':a.utc(timestamp-timestamp%a.FUNDING_INTERVAL_MS),
                         'rate_finite':True})
    return selected,skipped

def verify_isolation():
    # Poison protected rates: selector must never pass any to its conversion hook.
    cutoff=a.DATA_END_MS
    rows=['instrument_name,funding_rate,funding_time',
          f'{a.INSTRUMENT_ID},0.0001,{cutoff-a.FUNDING_INTERVAL_MS+4000}']
    rows += [f'{a.INSTRUMENT_ID},{rate},{cutoff+i*a.FUNDING_INTERVAL_MS}'
             for i,rate in enumerate(['DO_NOT_PARSE','NaN','Infinity','-Infinity',''])]
    calls=[]
    def parse(value):
        calls.append(value)
        return Decimal(value)
    selected,skipped=select(('\n'.join(rows)+'\n').encode(),cutoff,parse)
    assert len(selected)==1 and skipped==5 and calls==['0.0001']
    for malformed in ('wrong,DO_NOT_PARSE,'+str(cutoff),a.INSTRUMENT_ID+',DO_NOT_PARSE,invalid'):
        try:
            select(('instrument_name,funding_rate,funding_time\n'+malformed+'\n').encode(),cutoff,parse)
        except AssertionError:
            pass
        else:
            raise AssertionError('identity/timestamp validation failed open')
    assert calls==['0.0001']
    return {'poison_rates_skipped':5,'selected_rate_conversion_calls':1,
            'invalid_identity_or_timestamp_rejected_before_rate':2,'status':'PASS'}

if __name__=='__main__':
    checks=verify_isolation()
    a.save('boundary-isolation-checks.json',a.canonical_bytes(checks))
    # The isolation checks above finish before any boundary network request.
    requests=[]
    original=a.archive_http_request
    catalog_raw=[]
    def capture(method,url,*,body=None):
        raw,headers=original(method,url,body=body)
        if method=='POST':
            catalog_raw.append({'request':a.save('boundary-catalog-request.json',body),
                                'response':a.save('boundary-catalog-response.json',raw)})
        return raw,headers
    a.archive_http_request=capture
    entry=a._archive_catalog_group([(2024,1)],requests)[0]
    year,month,url,archive_name,csv_name=entry
    raw,headers=original('GET',url)
    record=a.save(archive_name,raw)
    assert headers.get('content-type','').lower().startswith('application/zip')
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        members=archive.infolist()
        assert len(members)==1 and members[0].filename==csv_name
        m=members[0]
        assert not m.is_dir() and not m.flag_bits&1
        assert 0<m.file_size<=a.MAX_ARCHIVE_CSV_BYTES
        with archive.open(m) as f:
            csv_raw=f.read(a.MAX_ARCHIVE_CSV_BYTES+1)
        assert len(csv_raw)==m.file_size
    selected,skipped=select(csv_raw,a.DATA_END_MS)
    assert len(selected)==1
    assert selected[0]['floor_utc']==a.utc(a.DATA_END_MS-a.FUNDING_INTERVAL_MS)
    result={'month':'2024-01','scope':'only necessary pre-Holdout boundary row',
      'url':url,'retrieved_at_utc':a.datetime.now(a.UTC).isoformat(),'raw':record,'headers':headers,
      'member_count':1,'csv_filename':csv_name,'csv_bytes':len(csv_raw),'csv_sha256':a.sha256(csv_raw),
      'timestamp_rows_seen':len(selected)+skipped,'protected_rate_rows_skipped':skipped,
      'protected_rates_converted_validated_or_reported':False,
      'protected_rate_finiteness':'UNKNOWN / SEALED_UNREAD',
      'selected':selected,'selected_duplicates':0,'selected_missing':0,
      'selected_current_drift_rule':'REJECT' if selected[0]['offset_ms']>2000 else 'PASS',
      'requests':requests,'catalog_raw':catalog_raw,'isolation_checks':checks}
    a.save('2024-01-boundary.json',a.canonical_bytes(result))
    print(json.dumps(result),flush=True)
