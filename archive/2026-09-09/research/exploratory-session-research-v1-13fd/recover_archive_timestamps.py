"""One-shot recovery of six hash-pinned originals; inspect timestamp fields only."""
import csv
import hashlib
import io
import json
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, '/Users/shenjianpeng/.codex/worktrees/13fd/freqtrade-lab')
from scripts import fetch_okx_profile_data as producer

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / 'source-acquisition'
AUDIT = ROOT / 'audit-recovery'
SHA = lambda data: hashlib.sha256(data).hexdigest()
UTC = timezone.utc
def iso(ms):
    return datetime.fromtimestamp(ms / 1000, UTC).isoformat()
def event(value):
    with (AUDIT / 'requests.jsonl').open('a') as stream:
        stream.write(json.dumps(value, sort_keys=True) + '\n')

def main():
    receipt_bytes = (SOURCE / 'retrieval_receipt.json').read_bytes()
    assert SHA(receipt_bytes) == 'e588ec6c14d83d275c4c42dfe9c74587c9ed88b57f51a959cea8e57aa72e0ac5'
    records = [r for r in json.loads(receipt_bytes)['requests'] if r.get('archive_filename')]
    assert [r['archive_filename'] for r in records] == [f'LINK-USDT-SWAP-fundingrates-2024-{m:02d}.zip' for m in range(2, 8)]
    assert SHA((SOURCE/'producer/fetch_okx_profile_data.py').read_bytes()) == SHA(Path(producer.__file__).read_bytes())
    AUDIT.mkdir(mode=0o700)
    producer.INSTRUMENT_ID = 'LINK-USDT-SWAP'
    raw_start, raw_stop = 1706716800000, 1722441600000
    semantic_start, semantic_stop = 1706745600000, 1722384000000
    interval = 8*60*60*1000
    all_times, selected, outside, summaries = [], [], [], []
    try:
        for number, original in enumerate(records, 1):
            event({'number':number,'status':'REQUEST_STARTED','url':original['url'],'method':'GET','at':datetime.now(UTC).isoformat()})
            raw, headers = producer.archive_http_request('GET', original['url'])
            (AUDIT / original['archive_filename']).write_bytes(raw)
            event({'number':number,'status':'RECEIVED','sha256':SHA(raw),'bytes':len(raw),'headers':headers})
            assert SHA(raw) == original['archive_sha256'], 'ZIP identity changed; parsing forbidden'
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                members = archive.infolist()
                assert len(members) == 1 and members[0].filename == original['csv_filename']
                member = members[0]
                assert not member.is_dir() and not member.flag_bits & 1
                assert 0 < member.file_size <= producer.MAX_ARCHIVE_CSV_BYTES
                with archive.open(member) as stream:
                    csv_bytes = stream.read(producer.MAX_ARCHIVE_CSV_BYTES + 1)
                assert len(csv_bytes) == member.file_size
            assert SHA(csv_bytes) == original['csv_sha256'], 'CSV identity changed; parsing forbidden'
            (AUDIT / original['csv_filename']).write_bytes(csv_bytes)
            reader = csv.reader(io.StringIO(csv_bytes.decode('utf-8', 'strict')), strict=True)
            assert next(reader) == producer.ARCHIVE_CSV_HEADER
            times = []
            for fields in reader:
                assert len(fields) == 3 and fields[0] == producer.INSTRUMENT_ID
                timestamp = fields[2]
                assert len(timestamp) == 13 and timestamp.isascii() and timestamp.isdigit()
                value = int(timestamp)
                times.append(value)
                assert raw_start <= value < raw_stop, 'Raw timestamp outside authorized envelope'
                floored = value - value % interval
                if semantic_start <= value < semantic_stop and semantic_start <= floored < semantic_stop:
                    assert value % interval <= producer.MAX_FUNDING_ARCHIVE_TIMESTAMP_DRIFT_MS
                    selected.append(floored)
                else:
                    outside.append(value)
            assert len(times) == original['csv_rows']
            all_times.extend(times)
            summaries.append({'archive':original['archive_filename'],'zip_sha256':SHA(raw),'csv_sha256':SHA(csv_bytes),'rows':len(times),'min_timestamp_ms':min(times),'max_timestamp_ms':max(times),'min_utc':iso(min(times)),'max_utc':iso(max(times))})
        assert len(all_times) == 546 and len(outside) == 3
        assert sorted(selected) == list(range(semantic_start,semantic_stop,interval))
        result = {'status':'VERIFIED_SAME_BYTES_RAW_TIMESTAMPS','recovery_requests':6,'new_catalog_requests':0,'original_source_receipt_sha256':SHA(receipt_bytes),'timestamp_unit':'milliseconds since Unix epoch','raw_envelope':[iso(raw_start),iso(raw_stop)],'raw_end_exclusive':True,'raw_rows':len(all_times),'selected_rows':len(selected),'raw_min_utc':iso(min(all_times)),'raw_max_utc':iso(max(all_times)),'outside_semantic_timestamps_ms':sorted(outside),'outside_semantic_utc':[iso(t) for t in sorted(outside)],'archives':summaries,'rate_analysis_performed':False,'real_backtests':0}
        (AUDIT/'timestamp-audit.json').write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps(result,indent=2))
    except BaseException as exc:
        (AUDIT/'failure.json').write_text(json.dumps({'status':'BLOCKED_RECOVERY','error_type':type(exc).__name__,'message':str(exc),'retry_allowed':False})+'\n')
        raise

if __name__ == '__main__':
    main()
