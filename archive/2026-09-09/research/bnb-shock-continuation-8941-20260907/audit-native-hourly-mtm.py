"""S-only risk projection of existing native trades; no strategy or backtest invocation."""
import hashlib
import json
import math
import zipfile
from pathlib import Path
import pandas as pd
from lab.futures_costs import validate_events, timestamp, HOUR_MS

R = Path(__file__).resolve().parent
review = json.loads((R/'search-protocol-review.json').read_bytes())
archive = Path(review['archive'])
assert hashlib.sha256(archive.read_bytes()).hexdigest() == review['archive_sha256']
with zipfile.ZipFile(archive) as z:
    name = next(n for n in z.namelist() if n.endswith('.json') and not n.endswith('_config.json'))
    trades = json.loads(z.read(name))['strategy']['BnbDailyShockContinuation48H']['trades']
source = R/'search-campaign/acquisition'
provenance = json.loads((source/'retained-data-provenance.json').read_bytes())
mark_path = source/'data/binance/futures/BNB_USDT_USDT-1h-mark.feather'
df = pd.read_feather(mark_path)
marks = [[int(row.date.timestamp()*1000), row.open, row.high, row.low, row.close] for row in df.itertuples()]
lo = int(pd.Timestamp('2023-11-06',tz='UTC').timestamp()*1000)
hi = int(pd.Timestamp('2024-11-04',tz='UTC').timestamp()*1000)
funding, candles = validate_events(provenance['source']['funding_events'], marks, symbol='BNBUSDT', start_ms=lo, end_ms=hi)
wallet = peak = 1000.0
dd = 0.0
observations = 0
for t in trades:
    opened, closed = timestamp(t['open_date']), timestamp(t['close_date'])
    side = -1 if t['is_short'] else 1
    amount, price = t['amount'], t['open_rate']
    flows = [(e['native_time_ms'], -side*e['rate']*e['native_mark']*amount)
             for e in funding if opened <= e['native_time_ms'] <= closed]
    if opened == closed and t['funding_fees'] == 0:
        flows = []
    assert math.isclose(sum(v for _, v in flows), t['funding_fees'], abs_tol=1e-7)
    entry_cash = wallet - amount*price*t['fee_open']
    dd = max(dd, (peak-entry_cash)/peak)
    for hour in range(opened//HOUR_MS*HOUR_MS, closed, HOUR_MS):
        point = min(hour+HOUR_MS, closed)
        if hour >= opened and point < closed:
            cash = entry_cash + math.fsum(v for at, v in flows if at <= point)
            mark = candles[hour][3]
            equity = cash + side*(mark-price)*amount - mark*amount*t['fee_close']
            peak = max(peak,equity)
            dd = max(dd,(peak-equity)/peak)
            observations += 1
    wallet += t['profit_abs']
    peak = max(peak,wallet)
    dd = max(dd,(peak-wallet)/peak)
assert math.isclose(wallet-1000, review['cost_decomposition']['native_net_usdt'], abs_tol=1e-7)
out = {'scope':'S_EXISTING_NATIVE_TRADES_HOURLY_CLOSE_RISK_AUDIT_ONLY',
    'native_hourly_close_mtm_drawdown_pct':dd*100,
    'conservative_hourly_close_mtm_drawdown_pct':review['conservative_audit']['conservative_mtm_drawdown_pct'],
    'native_report_drawdown_pct':review['native_metrics']['max_drawdown_pct'],
    'native_hourly_gate':{'maximum_pct':10,'passed':dd*100<=10},
    'native_final_wallet':wallet,'full_hour_observations':observations,
    'risk_model':'Same full-hour-close/entry-fee/native-exit observations as existing audit; native funding only, no conservative deduction. Excludes partial-bar close observations and is not continuous MTM.',
    'archive_sha256':review['archive_sha256'], 'mark_sha256':hashlib.sha256(mark_path.read_bytes()).hexdigest(),
    'source_provenance_sha256':hashlib.sha256((source/'retained-data-provenance.json').read_bytes()).hexdigest(),
    'strategy_invocations':0,'native_invocations':0,'D_H_read':False,
    'full_protocol_verdict':'FAILED_UNCHANGED_BLOCK_GATES'}
with (R/'native-hourly-mtm.json').open('x') as f:json.dump(out,f,indent=2)
print(json.dumps(out))
