"""Two causal, preregistered sign gates over the unchanged persistence parent."""
from pathlib import Path
import json
import math

from lab.perp_baseline import PerpBaseline, features
from lab.perp_baseline_runner import PAIRS, sha, write

VARIANTS = ('carry_nonpaying', 'carry_premium_agree')


def align_factors(dates, funding, premium):
    """Historical decision time is source close+60s; no forward/back fill."""
    import pandas as pd
    left = pd.DataFrame({'date': pd.to_datetime(dates, utc=True)})
    left['decision_at'] = left.date + pd.Timedelta(hours=1, seconds=60)
    right = funding.copy().sort_values('funding_available_at')
    joined = pd.merge_asof(left, right, left_on='decision_at',
                           right_on='funding_available_at', direction='backward')
    joined = joined.merge(premium, on='date', how='left', validate='one_to_one')
    joined['factor_valid'] = (
        joined.funding_rate.notna() & joined.premium_close.notna() &
        (joined.funding_available_at <= joined.decision_at) &
        (joined.premium_available_at <= joined.decision_at) &
        (joined.funding_event_at <= joined.decision_at) &
        (joined.decision_at - joined.funding_event_at <= pd.Timedelta(hours=12)))
    return joined


def load_factor_source(root, frames, score_start, score_end):
    """Read only after preregistration; verify public data without choosing gates."""
    import pandas as pd
    root = Path(root)
    receipt = json.loads((root/'receipt.json').read_text())
    inputs, binding = {}, {}
    for pair in PAIRS:
        symbol = pair.split('/')[0]+'USDT'; datasets = {}
        for kind in ('funding', 'premium'):
            name = symbol+'-'+kind; item = receipt['datasets'][name]; path = root/item['path']
            if sha(path) != item['sha256']:
                raise ValueError('factor source SHA mismatch: '+name)
            rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
            if len(rows) != item['rows'] or not rows:
                raise ValueError('factor row count/empty mismatch: '+name)
            if any('FIRST_OBSERVATION_FLOOR' in r['quality'] for r in rows):
                raise ValueError('historical runner cannot replay observed forward vintages')
            at = pd.to_datetime([r['event_time'] for r in rows], utc=True, format='mixed')
            available = pd.to_datetime([r['available_at'] for r in rows], utc=True, format='mixed')
            if at.has_duplicates or not at.is_monotonic_increasing or not available.is_monotonic_increasing:
                raise ValueError('duplicate/disordered factor time: '+name)
            values = [float(r['rate' if kind=='funding' else 'close']) for r in rows]
            if not all(math.isfinite(v) for v in values):
                raise ValueError('nonfinite factor: '+name)
            lag = pd.Timedelta(hours=1, seconds=60 if kind=='premium' else 0)
            if not (available >= at+lag).all():
                raise ValueError('factor availability precedes conservative publication lag')
            if kind == 'funding':
                datasets[kind] = pd.DataFrame(dict(funding_event_at=at,
                    funding_available_at=available, funding_rate=values))
            else:
                if not at.equals(pd.DatetimeIndex(frames[pair].date)):
                    raise ValueError('premium has a missing, duplicate or extra hour')
                datasets[kind] = pd.DataFrame(dict(date=at, premium_available_at=available,
                    premium_close=values))
            binding[name] = dict(path=str(path), sha256=sha(path), rows=len(rows))
        aligned = align_factors(frames[pair].date, datasets['funding'], datasets['premium'])
        scored = (aligned.date+pd.Timedelta(hours=2) >= score_start) & (aligned.date+pd.Timedelta(hours=2) < score_end)
        if not aligned.loc[scored, 'factor_valid'].all():
            raise ValueError('BLOCKED_DATA: unavailable/stale factor in scored decision window: '+pair)
        inputs[pair] = aligned
    return inputs, binding


def gate_masks(frame, variant):
    if variant not in VARIANTS:
        raise ValueError('unregistered funding/premium variant')
    long = frame.factor_valid & (frame.funding_rate <= 0)
    short = frame.factor_valid & (frame.funding_rate >= 0)
    if variant == 'carry_premium_agree':
        long &= frame.premium_close <= 0
        short &= frame.premium_close >= 0
    return long, short


class PerpFundingPremiumV1(PerpBaseline):
    def bot_start(self, **kwargs):
        super().bot_start(**kwargs)
        if self.config['perp_variant'] != 'persistence' or self.config.get('perp_factor_variant') not in VARIANTS:
            raise ValueError('frozen persistence factor configuration required')
        self.factor_tables = {}
        for pair in PAIRS:
            item = self.config['perp_factor_files'][pair]
            if sha(item['path']) != item['sha256']:
                raise ValueError('prepared factor table hash differs')
            import pandas as pd
            value = pd.read_json(item['path'], orient='table')
            self.factor_tables[pair] = value

    def populate_indicators(self, dataframe, metadata):
        result = features(dataframe)
        return result.merge(self.factor_tables[metadata['pair']], on='date', how='left', validate='one_to_one')

    def populate_entry_trend(self, dataframe, metadata):
        valid = dataframe.risk_multiplier.notna() & (dataframe.volume > 0)
        long_gate, short_gate = gate_masks(dataframe, self.config['perp_factor_variant'])
        long = dataframe.baseline_long & valid & (dataframe.persistence >= .25) & long_gate
        short = dataframe.baseline_short & valid & (dataframe.persistence <= -.25) & short_gate
        dataframe['enter_long'] = long.shift(1, fill_value=False).astype(int)
        dataframe['enter_short'] = short.shift(1, fill_value=False).astype(int)
        dataframe['enter_tag'] = self.config['perp_factor_variant']
        return dataframe

    def custom_stake_amount(self, pair, current_time, **kwargs):
        frame, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if len(frame) >= 2:
            row = frame.iloc[-2]
            if (not bool(row.factor_valid) or row.decision_at > current_time or
                    row.funding_available_at > row.decision_at or row.premium_available_at > row.decision_at):
                raise ValueError('native factor entry uses unavailable information')
        accepted = super().custom_stake_amount(pair=pair, current_time=current_time, **kwargs)
        if len(frame) >= 2 and self.entry_audit:
            self.entry_audit[-1].update(decision_at=row.decision_at.isoformat(),
                funding_event_at=row.funding_event_at.isoformat(),
                funding_available_at=row.funding_available_at.isoformat(),
                premium_available_at=row.premium_available_at.isoformat(),
                funding_rate=float(row.funding_rate), premium_close=float(row.premium_close))
        return accepted


def run_native_factor(root, frames, events, metadata, factors, variant, start, end):
    """Use unchanged Freqtrade assembly, matching, cash flow and fill auditing."""
    import pandas as pd
    from freqtrade.commands.optimize_commands import setup_optimize_configuration
    from freqtrade.enums import RunMode, CandleType
    from freqtrade.exchange.binance import Binance
    from freqtrade.optimize.backtesting import Backtesting
    from freqtrade.data.history.datahandlers import get_datahandler
    from lab.perp_baseline_runner import REPO, native_config, assembly
    from lab.portfolio_native_export import read_strategy_export
    if variant not in VARIANTS:
        raise ValueError('unregistered factor variant')
    root = Path(root)
    for name in ('user', 'exports', 'data', 'factors'):
        (root/name).mkdir(parents=True)
    handler = get_datahandler(root/'data', 'feather'); factor_files = {}
    for pair, frame in frames.items():
        handler.ohlcv_store(pair, '1h', frame, CandleType.FUTURES)
        path = root/'factors'/(pair.split('/')[0]+'.json')
        factors[pair].to_json(path, orient='table', date_format='iso', date_unit='ms')
        factor_files[pair] = dict(path=str(path), sha256=sha(path))
    value = native_config('persistence', 1.)
    value.update(strategy='PerpFundingPremiumV1', perp_factor_variant=variant, perp_factor_files=factor_files)
    path = root/'config.json'; write(path, value)
    config = setup_optimize_configuration(dict(command='backtesting', config=[str(path)],
        datadir=str(root/'data'), user_data_dir=str(root/'user'), strategy_path=str(REPO/'lab'),
        strategy='PerpFundingPremiumV1', timerange=f'{int(start.timestamp())}-{int(end.timestamp())}', fee=.0008,
        export='trades', exportdirectory=str(root/'exports'), dataformat_ohlcv='feather',
        disableparamexport=True, backtest_cache='none'), RunMode.BACKTEST)

    class EventBacktesting(Backtesting):
        def _load_bt_data_detail(self):
            if self.timeframe_detail:
                raise ValueError('factor intrahour extension forbidden')
            self.detail_data = {}; self.futures_data = events; self.funding_fee_timeframe_secs = 3600

    class EventBinance(Binance):
        def calculate_funding_fees(self, df, amount, is_short, open_date, close_date):
            return super().calculate_funding_fees(df.loc[df.date > pd.Timestamp(open_date)],
                amount=amount, is_short=is_short, open_date=open_date, close_date=close_date)

    exchange = EventBinance(config, validate=False, load_leverage_tiers=False)
    def deny(*a, **k): raise RuntimeError('factor native worker cannot request exchange')
    exchange._api.fetch = deny; exchange._api_async.fetch = deny
    markets, tiers = assembly(metadata)
    exchange._api.set_markets(markets, {}); exchange._api_async.set_markets(markets, {})
    exchange._markets = exchange._api.markets; exchange._leverage_tiers = tiers
    engine = None
    try:
        engine = EventBacktesting(config, exchange=exchange)
        if len(engine.strategylist) != 1 or set(engine.pairlists.whitelist) != set(PAIRS):
            raise ValueError('factor native wallet/pair mismatch')
        engine.start(); archives = list((root/'exports').glob('*.zip'))
        if len(archives) != 1:
            raise ValueError('expected one factor native archive')
        result = read_strategy_export(archives[0], 'PerpFundingPremiumV1')
        write(root/'native-result.json', result); write(root/'entry-audit.json', engine.strategylist[0].entry_audit)
        return result, {p.name: sha(p) for p in archives}
    finally:
        if engine is not None: engine.cleanup()
        exchange.close()
