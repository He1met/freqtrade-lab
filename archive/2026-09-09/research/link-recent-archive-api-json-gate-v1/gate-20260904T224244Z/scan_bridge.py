"""One complete ZIP scan, counted header and rows, sample fields only."""
import csv,datetime,hashlib,io,json,os,pathlib,stat,time,zipfile
from decimal import Decimal
ROOT=pathlib.Path(__file__).resolve().parent
os.umask(0o077)
with (ROOT/'scan-started.json').open('x') as f: json.dump({'scan_count':1,'started_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat()},f)
began=time.monotonic(); limit=134217728
receipt={'status':'FAILED_STOP','scan_count':1,'cumulative_decompressed_bytes':0,'rows_seen':0,
         'api_matched_rows':0,'actual_utc_min':None,'actual_utc_max_inclusive':None}
selected=[]; normalized=[]; lo=None; hi=None; seen=set()
api={r['id']:r for r in json.loads((ROOT/'api-normalized.json').read_text())}
class Counted(io.RawIOBase):
    def __init__(self,source): self.source=source
    def readable(self): return True
    def readinto(self,b):
        assert time.monotonic()-began<300,'SCAN_TIME_LIMIT'
        chunk=self.source.read(min(len(b),limit-receipt['cumulative_decompressed_bytes']+1))
        receipt['cumulative_decompressed_bytes']+=len(chunk)
        assert receipt['cumulative_decompressed_bytes']<=limit,'DECOMPRESSED_BYTES_LIMIT'
        b[:len(chunk)]=chunk
        return len(chunk)
try:
    target=json.loads((ROOT/'catalog-target.json').read_text())
    expected=target['filename'][:-4]+'.csv'
    assert (ROOT/'zip.raw').stat().st_size<=16777216
    with zipfile.ZipFile(ROOT/'zip.raw') as z:
        members=z.infolist(); assert len(members)==1,'ZIP_SINGLE_MEMBER'
        m=members[0]; mode=m.external_attr>>16
        assert not m.is_dir() and stat.S_IFMT(mode) in [0,stat.S_IFREG],'ZIP_REGULAR_MEMBER'
        assert m.filename==expected and '/' not in m.filename and '\\' not in m.filename,'ZIP_MEMBER_NAME'
        assert not m.flag_bits&1,'ZIP_ENCRYPTED'
        assert m.file_size<=limit,'ZIP_DECLARED_EXPANDED_LIMIT'
        receipt.update(member=m.filename,declared_decompressed_bytes=m.file_size)
        with z.open(m,'r') as src:
            text=io.TextIOWrapper(io.BufferedReader(Counted(src),buffer_size=65536),encoding='utf-8-sig',newline='')
            reader=csv.DictReader(text)
            assert reader.fieldnames==['instrument_name','trade_id','side','price','size','created_time'],'CSV_SCHEMA'
            for row in reader:
                ts=row['created_time']; assert ts.isdecimal() and len(ts)==13,'CSV_TIME_FORMAT'
                ts=int(ts); receipt['rows_seen']+=1
                lo=ts if lo is None else min(lo,ts); hi=ts if hi is None else max(hi,ts)
                assert 1780848000000<=ts<1780934400000,'ARCHIVE_TIME_OUT_OF_FROZEN_RANGE'
                ident=row['trade_id']; assert ident.isdecimal() and ident not in seen,'CSV_ID_DUPLICATE_OR_FORMAT'
                seen.add(ident)
                if ident not in api: continue
                a=api[ident]
                assert row['instrument_name']==a['instrument']=='LINK-USDT-SWAP','MATCH_INSTRUMENT'
                assert ts==a['timestamp'],'MATCH_TIMESTAMP'
                assert row['side']==a['side'],'MATCH_SIDE'
                for key,other in [('price','price'),('size','contracts_size')]:
                    d=Decimal(row[key]); assert d.is_finite() and d>0,'MATCH_NUMERIC_FORMAT'
                    assert d==Decimal(a[other]),'MATCH_DECIMAL_'+key
                selected.append(row)
                normalized.append({'instrument':row['instrument_name'],'id':ident,'timestamp':ts,'side':row['side'],
                                   'price':row['price'],'contracts_size':row['size']})
                receipt['api_matched_rows']+=1
        assert receipt['cumulative_decompressed_bytes']==m.file_size,'SCAN_SIZE_MISMATCH'
        receipt['crc_checked_at_eof']=True
    assert len(selected)==100 and {r['id'] for r in normalized}==set(api),'MATCH_MISSING'
    hashes={}
    for name,rows in [('selected-raw.json',selected),('selected-normalized.json',normalized)]:
        p=ROOT/name
        with p.open('x') as f: json.dump(rows,f,indent=2); f.write('\n'); f.flush(); os.fsync(f.fileno())
        hashes[name]=hashlib.sha256(p.read_bytes()).hexdigest()
    receipt.update(status='PASS_SAMPLE_BRIDGE_ONLY',persisted_sha256=hashes,unique_archive_ids=len(seen),
       historical_contractSize='UNKNOWN',base_amount_conversion='UNPROVEN',
       scope='100 same original IDs exact timestamp/taker-side/Decimal price/contracts-quantity correspondence only',
       exposure='Entire ZIP raw obtained; all archive rows timestamp/ID interpreted; only API-matched 100 rows other fields interpreted',
       real_ohlcv_flow_signal_pnl='NOT_GENERATED')
except Exception as e:
    receipt['error_type']=type(e).__name__; receipt['error']=str(e)
    raise
finally:
    for key,value in [('actual_utc_min',lo),('actual_utc_max_inclusive',hi)]:
        if value is not None: receipt[key]=datetime.datetime.fromtimestamp(value/1000,datetime.timezone.utc).isoformat()
    receipt['elapsed_seconds']=time.monotonic()-began
    (ROOT/'bridge-result.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps(receipt,indent=2))
