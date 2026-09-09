"""One-shot frozen funding audit using unchanged official producer helpers."""
import csv, io, json, os, zipfile, hashlib
from pathlib import Path
from datetime import datetime, UTC
from scripts import fetch_okx_profile_data as p

os.umask(0o077)
ROOT=Path(__file__).resolve().parent
def write(name,data):
    (ROOT/name).write_text(json.dumps(data,indent=2,allow_nan=False)+'\n')
def sha(raw):return hashlib.sha256(raw).hexdigest()
freeze=json.loads((ROOT/'issue-live-freeze.json').read_text())
assert freeze['state']=='OPEN' and freeze['number']==63
assert freeze['body'].strip()==(ROOT/'issue-frozen.md').read_text().strip()
assert not (ROOT/'funding-precheck-terminal.json').exists(), 'one-shot precheck already terminal'
runtime=p.validate_runtime()
p.DATA_START=datetime(2023,10,4,tzinfo=UTC)
p.SEARCH_START=datetime(2024,2,1,tzinfo=UTC)
p.DEVELOPMENT_START=datetime(2025,2,1,tzinfo=UTC)
p.DATA_END=datetime(2026,2,1,tzinfo=UTC)
p.DATA_START_MS=int(p.DATA_START.timestamp()*1000)
p.DATA_END_MS=int(p.DATA_END.timestamp()*1000)
p.MARK_START_MS=int(p.SEARCH_START.timestamp()*1000)
p.SYMBOL='LTC/USDT:USDT';p.INSTRUMENT_ID='LTC-USDT-SWAP';p.PAIR_FAMILY='LTC-USDT';p.FUTURES_TIMEFRAME='1d'
p.PROFILE_ACQUISITION={'scope':'FUNDING_ONLY_PREFLIGHT','issue':63,'pair':p.SYMBOL,'timeframe':'1d'}
first=int(p.SEARCH_START.timestamp()*1000)
expected=list(range(first,p.DATA_END_MS,p.FUNDING_INTERVAL_MS))
assert len(expected)==2193
rawdir=ROOT/'raw';rawdir.mkdir(mode=0o700)
requests=[];months=[];all_rows=[];current=None
terminal={'issue':63,'runtime':runtime,'phase':'FUNDING_ONLY_RAW_EXACT_GRID_PRECHECK','source_code_sha':'dc82c61fe8a27a654977344755c088412518d858','profile_id':None,'generation_ids':[],'candidate_ids':[],'campaign_id':None,'research_run_id':None,'search_attempts':0,'holdout_status':'SEALED_UNREAD','stress_status':'SEALED_UNREAD','expected_events':len(expected),'slippage':'UNKNOWN'}
try:
    exchange=p.transport.ccxt.okx({'enableRateLimit':True,'timeout':30000,'options':{'defaultType':'swap'}})
    p.install_request_guard(exchange)
    response=p.assert_okx_response(exchange.public_get_public_instruments({'instType':'SWAP','instId':p.INSTRUMENT_ID}),'instrument')
    requests.append(p.request_receipt(exchange,'instrument'))
    assert len(response['data'])==1,'instrument must be unique'
    instrument=response['data'][0]
    assert instrument.get('instId')==p.INSTRUMENT_ID and instrument.get('instType')=='SWAP' and instrument.get('settleCcy')=='USDT' and instrument.get('state')=='live','instrument identity mismatch'
    market=exchange.parse_market(instrument)
    assert market.get('symbol')==p.SYMBOL and market.get('id')==p.INSTRUMENT_ID and market.get('swap') is True and market.get('linear') is True,'parsed instrument mismatch'
    assert int(instrument['listTime'])<=p.DATA_START_MS,'instrument not listed before frozen source window'
    write('instrument-metadata.json',response)
    for year,month in p._archive_months():
        current=f'{year:04d}-{month:02d}'
        entries=p._archive_catalog_group([(year,month)],requests)
        year,month,url,archive_name,csv_name=entries[0]
        raw,headers=p.archive_http_request('GET',url)
        (rawdir/archive_name).write_bytes(raw)
        receipt={'label':current,'url':url,'response_headers':headers,'archive_sha256':sha(raw),'archive_bytes':len(raw),'fetched_at_utc':datetime.now(UTC).isoformat()}
        requests.append(receipt)
        assert headers.get('content-type','').lower().startswith('application/zip'),'archive Content-Type is not ZIP'
        # Read original timestamps before calling the existing floor-capable parser.
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            members=z.infolist()
            assert len(members)==1 and members[0].filename==csv_name,'ZIP member mismatch'
            member=members[0]
            assert not member.is_dir() and not member.flag_bits & 1 and 0<member.file_size<=p.MAX_ARCHIVE_CSV_BYTES,'invalid ZIP member'
            with z.open(member) as stream:csvraw=stream.read(p.MAX_ARCHIVE_CSV_BYTES+1)
            assert len(csvraw)==member.file_size,'CSV size mismatch'
        receipt['csv_sha256']=sha(csvraw)
        reader=csv.reader(io.StringIO(csvraw.decode('utf-8','strict')),strict=True)
        assert next(reader)==p.ARCHIVE_CSV_HEADER,'CSV header mismatch'
        selected=[]
        for number,fields in enumerate(reader,2):
            assert len(fields)==3,'CSV row shape mismatch'
            assert fields[0]==p.INSTRUMENT_ID,'CSV instrument mismatch'
            rawts=fields[2]
            assert len(rawts)==13 and rawts.isascii() and rawts.isdigit(),'invalid raw timestamp'
            ts=int(rawts)
            if not first<=ts<p.DATA_END_MS:continue
            offset=ts%p.FUNDING_INTERVAL_MS
            if offset:
                terminal['first_failure']={'archive':archive_name,'csv':csv_name,'csv_record':number,'raw_timestamp_ms':ts,'raw_timestamp_utc':datetime.fromtimestamp(ts/1000,UTC).isoformat(),'offset_ms':offset,'rate_interpreted':False,'archive_sha256':sha(raw),'csv_sha256':sha(csvraw)}
                raise RuntimeError('RAW_FUNDING_TIMESTAMP_NOT_EXACT_8H_GRID')
            assert ts not in selected,'duplicate raw timestamp'
            selected.append(ts)
        local_start=datetime(year,month,1,tzinfo=p.ARCHIVE_TIMEZONE)
        ny,nm=p._month_after((year,month));local_end=datetime(ny,nm,1,tzinfo=p.ARCHIVE_TIMEZONE)
        month_expected=[ts for ts in expected if int(local_start.timestamp()*1000)<=ts<int(local_end.timestamp()*1000)]
        assert sorted(selected)==month_expected,'raw monthly UTC+8 intersection missing/extra timestamps'
        rows,parser_receipt=p._parse_funding_archive(raw,archive_name=archive_name,csv_name=csv_name,year=year,month=month,start_ms=first,end_exclusive_ms=p.DATA_END_MS)
        assert sorted(int(row['timestamp']) for row in rows)==sorted(selected),'parser timestamp mismatch'
        receipt['producer_parser']=parser_receipt
        months.append({'month':current,'status':'PASS','selected_raw_events':len(selected),'expected_events':len(month_expected),'maximum_raw_offset_ms':0})
        all_rows.extend(rows)
        write('funding-precheck-progress.json',{'months':months,'requests':requests})
        print(json.dumps(months[-1]),flush=True)
    p.validate_funding_history(all_rows)
    assert sorted(int(row['timestamp']) for row in all_rows)==expected
    terminal.update(status='FUNDING_RAW_EXACT_GRID_PASS',selected_events=len(all_rows))
except Exception as exc:
    terminal.update(status='BLOCKED_DATA',failed_month=current,error_type=type(exc).__name__,error=str(exc))
finally:
    terminal['months_passed']=months
    terminal['requests']=requests
    terminal['finished_at_utc']=datetime.now(UTC).isoformat()
    write('funding-precheck-terminal.json',terminal)
    print(json.dumps(terminal,allow_nan=False),flush=True)
