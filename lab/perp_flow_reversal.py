"""Frozen price-shock reversal controls using aggregate taker volume, offline only."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import math
import time

import numpy as np

from lab.perp_baseline import PerpBaseline
from lab.perp_baseline_runner import PAIRS, REPO, sha, write

VARIANTS = ('shock_rebound', 'flow_turn')
PROTOCOL = REPO / 'docs/protocols/perp-flow-reversal-v1.json'
SOURCE_ROOT = Path('/Users/shenjianpeng/Documents/freqtrade-lab-local/perp-autonomous-v1/data/first-capture-v1')


class FlowAuditFailure(BaseException):
    """Causal failures must escape Freqtrade's Exception fallback to default stake."""


def flow_features(frame):
    """Prior shock/pressure ends at t-1; current rebound/pressure uses closed t."""
    out = frame.copy()
    returns = np.log(out.close / out.close.shift(1))
    out['source_return'] = returns
    sigma = returns.shift(1).rolling(168).std(ddof=0)
    out['shock_z'] = returns.shift(1).rolling(6).sum() / (sigma.replace(0, np.nan) * math.sqrt(6))
    prior_volume = out.volume.shift(1).rolling(6).sum()
    prior_buy = out.taker_buy_base_volume.shift(1).rolling(6).sum()
    out['pressure_prior'] = (2 * prior_buy - prior_volume) / prior_volume.replace(0, np.nan)
    out['pressure_current'] = (2 * out.taker_buy_base_volume - out.volume) / out.volume.replace(0, np.nan)
    out['flow_valid'] = (
        np.isfinite(out.shock_z) & np.isfinite(out.source_return) &
        np.isfinite(out.pressure_prior) & np.isfinite(out.pressure_current) &
        (out.volume > 0) & (out.taker_buy_base_volume >= 0) &
        (out.taker_buy_base_volume <= out.volume) &
        (out.flow_available_at <= out.date + timedelta(hours=1, seconds=60)))
    return out


def flow_masks(frame, variant):
    if variant not in VARIANTS:
        raise ValueError('unregistered flow reversal variant')
    long = frame.flow_valid & (frame.shock_z <= -2.) & (frame.source_return > 0.)
    short = frame.flow_valid & (frame.shock_z >= 2.) & (frame.source_return < 0.)
    if variant == 'flow_turn':
        long &= (frame.pressure_prior < 0.) & (frame.pressure_current > 0.)
        short &= (frame.pressure_prior > 0.) & (frame.pressure_current < 0.)
    return long, short


def load_flow_source(source_root, frames):
    """Validate only the preregistered exposed OHLCV; do not evaluate a signal."""
    import pandas as pd
    root = Path(source_root).resolve()
    protocol = json.loads(PROTOCOL.read_bytes())
    if root != SOURCE_ROOT.resolve() or root != Path(protocol['source_root']).resolve():
        raise ValueError('flow development accepts only frozen first-capture-v1')
    receipt_path = root / 'receipt.json'
    if sha(receipt_path) != protocol['source_receipt_sha256']:
        raise ValueError('flow source receipt SHA mismatch')
    receipt = json.loads(receipt_path.read_bytes())
    if (receipt['historical_use'] != 'EXPOSED_DEVELOPMENT_NO_INDEPENDENT_CONFIRMATION' or
            receipt['window_start'] != protocol['source_start'] or
            receipt['window_end_exclusive'] != protocol['score_end_exclusive']):
        raise ValueError('flow source is not the exposed registered development window')
    expected = pd.date_range(protocol['source_start'], protocol['score_end_exclusive'], freq='1h', inclusive='left')
    if set(frames) != set(PAIRS):
        raise ValueError('flow input pairs differ')
    factors = {}
    binding = {'flow_receipt': dict(path=str(receipt_path), sha256=sha(receipt_path), rows=None)}
    for pair in PAIRS:
        name = pair.split('/')[0] + 'USDT-ohlcv'
        item = receipt['datasets'][name]
        path = (root / item['path']).resolve()
        if path.parent != root or sha(path) != item['sha256'] or item['sha256'] != protocol['ohlcv_sha256'][name]:
            raise ValueError('flow OHLCV source path/SHA mismatch: ' + name)
        rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        if len(rows) != item['rows'] or len(rows) != len(expected):
            raise ValueError('flow OHLCV count mismatch: ' + name)
        if any(r['quality'] != 'HISTORICAL_CLOSED_BAR_CONSERVATIVE_60S_LAG' for r in rows):
            raise ValueError('flow source does not retain historical lag provenance')
        at = pd.DatetimeIndex(pd.to_datetime([r['event_time'] for r in rows], utc=True, format='mixed'))
        available = pd.DatetimeIndex(pd.to_datetime([r['available_at'] for r in rows], utc=True, format='mixed'))
        fetched = pd.DatetimeIndex(pd.to_datetime([r['fetched_at'] for r in rows], utc=True, format='mixed'))
        if not at.equals(expected) or not at.equals(pd.DatetimeIndex(frames[pair].date)):
            raise ValueError('flow hourly duplicate/gap/extra or native frame differs')
        if not available.equals(at + pd.Timedelta(hours=1, seconds=60)) or fetched.isna().any() or not (fetched >= available).all():
            raise ValueError('flow historical availability or actual fetched provenance invalid')
        for column in ('open', 'high', 'low', 'close', 'volume'):
            values = np.array([float(r[column]) for r in rows])
            if not np.isfinite(values).all() or not (values > 0.).all():
                raise ValueError('flow nonfinite/nonpositive OHLCV: ' + column)
            if not np.array_equal(values, frames[pair][column].to_numpy()):
                raise ValueError('flow/native frame OHLCV mismatch: ' + column)
        buy = np.array([float(r['taker_buy_base_volume']) for r in rows])
        volume = frames[pair].volume.to_numpy()
        if not np.isfinite(buy).all() or not ((buy >= 0.) & (buy <= volume)).all():
            raise ValueError('flow taker buy volume outside total base volume')
        factors[pair] = pd.DataFrame(dict(date=at, taker_buy_base_volume=buy, flow_available_at=available))
        binding[name] = dict(path=str(path), sha256=sha(path), rows=len(rows))
    return factors, binding


class PerpFlowReversal(PerpBaseline):
    startup_candle_count = 176

    def bot_start(self, **kwargs):
        super().bot_start(**kwargs)
        if self.config['perp_variant'] != 'persistence' or self.config.get('perp_flow_variant') not in VARIANTS:
            raise ValueError('frozen fixed-stake flow configuration required')
        import pandas as pd
        self.flow_tables = {}
        for pair in PAIRS:
            item = self.config['perp_flow_files'][pair]
            if sha(item['path']) != item['sha256']:
                raise ValueError('prepared flow table SHA mismatch')
            self.flow_tables[pair] = pd.read_json(item['path'], orient='table')

    def populate_indicators(self, dataframe, metadata):
        merged = dataframe.merge(self.flow_tables[metadata['pair']], on='date', how='left', validate='one_to_one')
        return flow_features(merged)

    def populate_entry_trend(self, dataframe, metadata):
        long, short = flow_masks(dataframe, self.config['perp_flow_variant'])
        # Source t is published t+1h+60s. This extra shift plus native next-bar
        # execution places the earliest fill at t+2h; no open-at-close fiction.
        dataframe['enter_long'] = long.shift(1, fill_value=False).astype(int)
        dataframe['enter_short'] = short.shift(1, fill_value=False).astype(int)
        dataframe['enter_tag'] = self.config['perp_flow_variant']
        return dataframe

    def populate_exit_trend(self, dataframe, metadata):
        dataframe['exit_long'] = 0
        dataframe['exit_short'] = 0
        return dataframe

    def custom_exit(self, pair, trade, current_time, current_rate, current_profit, **kwargs):
        if current_time - trade.open_date_utc >= timedelta(hours=12):
            return 'holding_12h'
        return None

    def custom_stake_amount(self, pair, current_time, **kwargs):
        frame, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if len(frame) >= 2:
            row = frame.iloc[-2]
            if (not bool(row.flow_valid) or row.flow_available_at > current_time or
                    row.date + timedelta(hours=2) != current_time):
                raise FlowAuditFailure('flow entry uses unavailable or misaligned source')
            long, short = flow_masks(frame.iloc[[-2]], self.config['perp_flow_variant'])
            if not bool((short if kwargs['side'] == 'short' else long).iloc[0]):
                raise FlowAuditFailure('native flow entry does not match its frozen source condition')
        accepted = super().custom_stake_amount(pair=pair, current_time=current_time, **kwargs)
        if len(frame) >= 2 and self.entry_audit:
            self.entry_audit[-1].update(flow_available_at=row.flow_available_at.isoformat(),
                shock_z=float(row.shock_z), source_return=float(row.source_return),
                pressure_prior=float(row.pressure_prior), pressure_current=float(row.pressure_current),
                side=kwargs['side'], variant=self.config['perp_flow_variant'])
        return accepted


def run_native_flow(root, frames, events, metadata, factors, variant, start, end):
    """Reuse native fills, shared wallet, precision, stops and exact funding events."""
    import pandas as pd
    from freqtrade.commands.optimize_commands import setup_optimize_configuration
    from freqtrade.enums import RunMode, CandleType
    from freqtrade.exchange.binance import Binance
    from freqtrade.optimize.backtesting import Backtesting
    from freqtrade.data.history.datahandlers import get_datahandler
    from lab.perp_baseline_runner import native_config, assembly
    from lab.portfolio_native_export import read_strategy_export
    if variant not in VARIANTS:
        raise ValueError('unregistered flow variant')
    root = Path(root)
    for name in ('user', 'exports', 'data', 'factors'):
        (root / name).mkdir(parents=True)
    handler = get_datahandler(root / 'data', 'feather')
    factor_files = {}
    for pair, frame in frames.items():
        handler.ohlcv_store(pair, '1h', frame, CandleType.FUTURES)
        path = root / 'factors' / (pair.split('/')[0] + '.json')
        factors[pair].to_json(path, orient='table', date_format='iso', date_unit='ms')
        factor_files[pair] = dict(path=str(path), sha256=sha(path))
    value = native_config('persistence', 1.)
    value.update(strategy='PerpFlowReversal', perp_flow_variant=variant, perp_flow_files=factor_files)
    path = root / 'config.json'
    write(path, value)
    config = setup_optimize_configuration(dict(command='backtesting', config=[str(path)],
        datadir=str(root / 'data'), user_data_dir=str(root / 'user'), strategy_path=str(REPO / 'lab'),
        strategy='PerpFlowReversal', timerange=f'{int(start.timestamp())}-{int(end.timestamp())}', fee=.0008,
        export='trades', exportdirectory=str(root / 'exports'), dataformat_ohlcv='feather',
        disableparamexport=True, backtest_cache='none'), RunMode.BACKTEST)

    class EventBacktesting(Backtesting):
        def _load_bt_data_detail(self):
            if self.timeframe_detail:
                raise ValueError('flow intrahour extension forbidden')
            self.detail_data = {}
            self.futures_data = events
            self.funding_fee_timeframe_secs = 3600

    class EventBinance(Binance):
        def calculate_funding_fees(self, df, amount, is_short, open_date, close_date):
            return super().calculate_funding_fees(df.loc[df.date > pd.Timestamp(open_date)],
                amount=amount, is_short=is_short, open_date=open_date, close_date=close_date)

    exchange = EventBinance(config, validate=False, load_leverage_tiers=False)
    def deny(*a, **k):
        raise RuntimeError('flow native worker cannot request exchange')
    exchange._api.fetch = deny
    exchange._api_async.fetch = deny
    markets, tiers = assembly(metadata)
    exchange._api.set_markets(markets, {})
    exchange._api_async.set_markets(markets, {})
    exchange._markets = exchange._api.markets
    exchange._leverage_tiers = tiers
    engine = None
    try:
        engine = EventBacktesting(config, exchange=exchange)
        if len(engine.strategylist) != 1 or set(engine.pairlists.whitelist) != set(PAIRS):
            raise ValueError('flow native wallet/pair mismatch')
        began = time.monotonic()
        write(root / 'native-started.json', dict(status='ENGINE_START_RESERVED',
            reserved_at=datetime.now(timezone.utc).isoformat(), variant=variant,
            native_execution_completion='UNKNOWN', economic_qualification=False))
        engine.start()
        write(root / 'native-completed.json', dict(status='ENGINE_COMPLETED',
            completed_at=datetime.now(timezone.utc).isoformat(), variant=variant,
            actual_engine_completed=True, engine_seconds=time.monotonic() - began,
            economic_qualification=False))
        archives = list((root / 'exports').glob('*.zip'))
        if len(archives) != 1:
            raise ValueError('expected one flow native archive')
        result = read_strategy_export(archives[0], 'PerpFlowReversal')
        write(root / 'native-result.json', result)
        write(root / 'entry-audit.json', engine.strategylist[0].entry_audit)
        return result, {p.name: sha(p) for p in archives}
    finally:
        if engine is not None:
            engine.cleanup()
        exchange.close()
