"""G1 format-only inspection; excluded rows: timestamp only. No OHLCV or signals."""
import csv
import hashlib
import json
import re
import zipfile
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import ccxt
from pandas.testing import assert_frame_equal
from freqtrade.data.converter.trade_converter import trades_dict_to_list, trades_list_to_df
from freqtrade.data.history import get_datahandler
from freqtrade.enums import TradingMode

ROOT = Path(__file__).parent
contract = json.loads((ROOT / 'g1-contract.json').read_text())
source = contract['source']
archive = ROOT / source['filename']
lo, hi = [int(datetime.fromisoformat(s.replace('Z', '+00:00')).timestamp() * 1000) for s in source['selected_utc']]
stamp = lambda n: datetime.fromtimestamp(n / 1000, timezone.utc).isoformat()
record = {'label': 'REAL_SELECTED_FORMAT_ONLY_NOT_ORDERFLOW_OR_ECONOMIC_EVIDENCE',
          'archive_sha256': hashlib.file_digest(archive.open('rb'), 'sha256').hexdigest(),
          'compressed_bytes': archive.stat().st_size,
          'selected_authorized_interval': source['selected_utc'],
          'archive_side_taker_semantics': 'UNKNOWN_NO_ARCHIVE_SPECIFIC_OFFICIAL_BRIDGE',
          'archive_size_unit': 'UNKNOWN_NO_ARCHIVE_SPECIFIC_OFFICIAL_BRIDGE',
          'historical_contract_size_2024': 'UNKNOWN',
          'mapping_status': 'CONDITIONAL_FORMAT_ONLY_RAW_SIZE_UNSCALED_NOT_UNIT_VERIFIED'}
assert record['compressed_bytes'] <= source['compressed_limit_bytes']
rows = []; seen = set(); seen_keys = set(); total = 0; selected = 0
low = None; high = None; previous = None; reversed_steps = 0; cumulative = 0
selected_low = None; selected_high = None
api = ccxt.okx()
# Identity metadata only. No assumed contractSize: raw size is tested as an unscaled numeric field.
market = {'id': source['instrument'], 'symbol': source['pair'], 'base': 'LINK', 'quote': 'USDT', 'settle': 'USDT', 'spot': False, 'swap': True, 'contract': True, 'linear': True, 'inverse': False}
try:
    with zipfile.ZipFile(archive) as z:
        members = z.infolist()
        assert len(members) == 1 and members[0].filename == 'LINK-USDT-SWAP-trades-2024-01.csv'
        info = members[0]
        assert info.file_size <= source['uncompressed_csv_stream_limit_bytes']
        record['member'] = {'name': info.filename, 'declared_bytes': info.file_size, 'crc': info.CRC}
        with z.open(info) as stream:
            raw = stream.readline(4097); cumulative += len(raw)
            header = next(csv.reader([raw.decode('utf-8-sig').strip()]))
            assert header == ['instrument_name', 'trade_id', 'side', 'price', 'size', 'created_time']
            record['header'] = header
            while True:
                raw = stream.readline(4097)
                if not raw:
                    break
                cumulative += len(raw)
                assert cumulative <= source['uncompressed_csv_stream_limit_bytes']
                assert len(raw) <= 4096, 'Overlong row'
                # The six-column CSV is tokenized, but only its final timestamp is interpreted here.
                fields = next(csv.reader([raw.decode('utf-8').strip()]))
                assert len(fields) == 6, 'Unexpected column count'
                token = fields[5]
                assert re.fullmatch(r'[0-9]{13}', token), 'Not exact Unix milliseconds'
                ts = int(token)
                total += 1
                low = ts if low is None else min(low, ts); high = ts if high is None else max(high, ts)
                if previous is not None and ts < previous:
                    reversed_steps += 1
                previous = ts
                if not lo <= ts < hi:
                    continue
                # Semantic/format inspection starts only inside the authorized half-open interval.
                instrument, ident, side, price, size, _ = fields
                assert instrument == source['instrument'], 'Selected instrument mismatch'
                assert ident and ident not in seen, 'Selected duplicate or empty trade ID'
                assert (ts, ident) not in seen_keys, 'Selected duplicate native key'
                seen.add(ident); seen_keys.add((ts, ident))
                assert side in {'buy', 'sell'}, 'Unknown selected side spelling'
                for value in (price, size):
                    dec = Decimal(value)
                    assert dec.is_finite() and dec > 0, 'Invalid selected numeric value'
                parsed = api.parse_trade({'instId': instrument, 'tradeId': ident, 'side': side, 'px': price, 'sz': size, 'ts': token}, market)
                assert parsed['id'] == ident and parsed['timestamp'] == ts and parsed['side'] == side
                assert parsed['amount'] == float(size) and parsed['price'] == float(price)
                rows.append(parsed)
                selected += 1
                selected_low = ts if selected_low is None else min(selected_low, ts)
                selected_high = ts if selected_high is None else max(selected_high, ts)
        assert cumulative == info.file_size
    assert selected > 0, 'Selected interval empty'
    df = trades_list_to_df(trades_dict_to_list(rows))
    assert len(df) == selected
    assert str(df['date'].dt.tz) == 'UTC'
    assert df['timestamp'].ge(lo).all() and df['timestamp'].lt(hi).all()
    target = ROOT / 'conditional-selected-native-format'
    handler = get_datahandler(target, 'feather')
    handler.trades_store(source['pair'], df, TradingMode.FUTURES)
    restored = handler.trades_load(source['pair'], TradingMode.FUTURES)
    assert_frame_equal(df.reset_index(drop=True), restored.reset_index(drop=True))
    record['native_roundtrip'] = {'status': 'PASS_CONDITIONAL_FORMAT_ONLY', 'rows': selected, 'exact_dataframe_equality': True,
        'files': [{'path': str(p.relative_to(ROOT)), 'bytes': p.stat().st_size, 'sha256': hashlib.file_digest(p.open('rb'), 'sha256').hexdigest()} for p in sorted(target.rglob('*.feather'))]}
    record['status'] = 'FORMAT_PASS_SEMANTIC_GATE_UNRESOLVED'
except Exception as exc:
    record['status'] = 'FAILED_STOP'
    record['error'] = {'type': type(exc).__name__, 'message': str(exc)}
    raise
finally:
    record.update({'actual_uncompressed_bytes_read': cumulative, 'timestamp_only_total_rows': total,
        'full_archive_actual_timestamp_min_utc': stamp(low) if low is not None else None,
        'full_archive_actual_timestamp_max_utc_inclusive': stamp(high) if high is not None else None,
        'global_timestamp_reverse_steps': reversed_steps, 'selected_rows': selected,
        'selected_actual_min_utc': stamp(selected_low) if selected_low is not None else None,
        'selected_actual_max_utc_inclusive': stamp(selected_high) if selected_high is not None else None,
        'selected_duplicate_ids': selected - len(seen), 'excluded_non_time_values_interpreted': False,
        'real_price_or_return_summary': False, 'real_ohlcv_or_flow_aggregation': False})
    (ROOT / 'selected-format-receipt.json').write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps(record, indent=2))
