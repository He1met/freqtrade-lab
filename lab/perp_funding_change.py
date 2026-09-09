"""Two fixed settled-funding controls; native hourly execution, no price factor."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import math
import time

from lab.perp_baseline import PerpBaseline
from lab.perp_baseline_runner import PAIRS, REPO, sha, write

VARIANTS = ('level_contrarian', 'change_contrarian')
CARD = REPO / 'docs/discovery/perp-funding-change-review-v1.json'


class FundingChangeFailure(BaseException):
    """Never let native callback recovery turn a causal rejection into a trade."""


def build_event_schedule(dates, funding):
    """No return labels: shared adjacent 8h-slot events and strict availability."""
    import pandas as pd
    dates = pd.DatetimeIndex(pd.to_datetime(dates, utc=True))
    expected = pd.date_range(dates[0], dates[-1], freq='1h')
    if len(dates) != len(expected) or not (dates == expected).all():
        raise ValueError('funding schedule requires complete unique hourly carrier dates')
    events = funding.copy()
    for key in ('event_at', 'available_at'):
        events[key] = pd.to_datetime(events[key], utc=True)
    if len(events) < 2 or events.event_at.duplicated().any() or not events.event_at.is_monotonic_increasing:
        raise ValueError('two or more strictly ordered settled events required')
    slots = events.event_at.dt.floor('8h')
    if not (slots.diff().iloc[1:] == pd.Timedelta(hours=8)).all():
        raise ValueError('gap or changed funding interval; only consecutive equal 8h UTC slots')
    if not all(math.isfinite(float(v)) for v in events.rate):
        raise ValueError('nonfinite settled rate')
    if events.available_at.isna().any() or not (events.available_at >= events.event_at + pd.Timedelta(hours=1)).all():
        raise ValueError('settled funding declared before conservative publication lag')
    events['previous_event_at'] = events.event_at.shift(1)
    events['previous_available_at'] = events.available_at.shift(1)
    events['previous_rate'] = events.rate.shift(1)
    events = events.iloc[1:].copy()
    events['delta'] = events.rate - events.previous_rate
    maximum = events[['available_at', 'previous_available_at']].max(axis=1)
    # floor+one, not ceil: an exactly-hourly available_at must wait another hour.
    events['execution_at'] = maximum.dt.floor('1h') + pd.Timedelta(hours=1)
    events['date'] = events.execution_at - pd.Timedelta(hours=1)
    events['event_id'] = events.event_at.map(lambda value: value.isoformat())
    for field, name in (('rate', 'level_direction'), ('delta', 'change_direction')):
        events[name] = events[field].map(lambda value: -1 if value > 0 else 1 if value < 0 else 0)
    if events.execution_at.duplicated().any():
        raise ValueError('multiple settled events map to one native entry hour')
    return events.loc[events.date.isin(dates), ['date', 'event_id', 'event_at', 'previous_event_at',
        'rate', 'previous_rate', 'delta', 'available_at', 'previous_available_at', 'execution_at',
        'level_direction', 'change_direction']].reset_index(drop=True)


def filter_schedule(schedule, start, end):
    """Exclude unfinished terminal holds before native runs, identically for both controls."""
    import pandas as pd
    return schedule.loc[(schedule.execution_at >= start) &
        (schedule.execution_at + pd.Timedelta(hours=8) <= end - pd.Timedelta(hours=1))].copy()


def load_change_source(root, frames):
    """Only registered exposed funding; hashes, provenance and time, no PnL input."""
    import pandas as pd
    root = Path(root).resolve()
    scope = json.loads(CARD.read_bytes())['data_scope']
    if root != Path(scope['root']).resolve():
        raise ValueError('only the registered first-capture development source is admitted')
    receipt_path = root / 'receipt.json'
    if sha(receipt_path) != scope['receipt_sha256']:
        raise ValueError('funding change receipt SHA mismatch')
    receipt = json.loads(receipt_path.read_bytes())
    if receipt['historical_use'] != 'EXPOSED_DEVELOPMENT_NO_INDEPENDENT_CONFIRMATION':
        raise ValueError('funding change is development-only')
    expected = pd.date_range(scope['window_start'], scope['window_end_exclusive'], freq='1h', inclusive='left')
    schedules = {}
    binding = {'change_receipt': dict(path=str(receipt_path), sha256=sha(receipt_path), rows=None)}
    for pair in PAIRS:
        if pair not in frames or len(frames[pair]) != len(expected) or not (pd.DatetimeIndex(frames[pair].date) == expected).all():
            raise ValueError('native frame date coverage differs from funding development source')
        symbol = pair.split('/')[0] + 'USDT'
        fixed = next(item for item in scope['datasets'] if item['symbol'] == symbol)
        item = receipt['datasets'][symbol + '-funding']
        path = (root / item['path']).resolve()
        if path.parent != root or sha(path) != fixed['sha256'] or item['sha256'] != fixed['sha256']:
            raise ValueError('settled funding path/SHA mismatch')
        rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        if len(rows) != item['rows'] or len(rows) != fixed['rows']:
            raise ValueError('settled funding row count mismatch')
        if any('FIRST_OBSERVATION_FLOOR' in r['quality'] for r in rows):
            raise ValueError('forward vintages cannot be replayed as historical funding')
        event = pd.to_datetime([r['event_time'] for r in rows], utc=True, format='mixed')
        cost = pd.to_datetime([r['cost_time'] for r in rows], utc=True, format='mixed')
        available = pd.to_datetime([r['available_at'] for r in rows], utc=True, format='mixed')
        fetched = pd.to_datetime([r['fetched_at'] for r in rows], utc=True, format='mixed')
        if not (cost == event).all() or not (available == event + pd.Timedelta(hours=1)).all() or not (fetched >= available).all():
            raise ValueError('actual cost timestamp / historical availability / fetched provenance differs')
        if not all(math.isfinite(float(r['mark_price'])) and float(r['mark_price']) > 0 for r in rows):
            raise ValueError('missing actual funding settlement mark')
        funding = pd.DataFrame(dict(event_at=event, available_at=available, rate=[float(r['rate']) for r in rows]))
        schedules[pair] = build_event_schedule(frames[pair].date, funding)
        binding[symbol + '-funding'] = dict(path=str(path), sha256=sha(path), rows=len(rows))
    return schedules, binding


class PerpFundingChange(PerpBaseline):
    """Event bookkeeping observes native open trades; it does not match or close them."""

    def bot_start(self, **kwargs):
        super().bot_start(**kwargs)
        import pandas as pd
        if self.config['perp_variant'] != 'persistence' or self.config.get('perp_change_variant') not in VARIANTS:
            raise FundingChangeFailure('frozen funding change configuration required')
        self.change_tables = {}
        self.event_lookup = {}
        self.pending_events = {}
        self.consumed_events = set()
        self.event_audit = []
        for pair in PAIRS:
            item = self.config['perp_change_files'][pair]
            if sha(item['path']) != item['sha256']:
                raise FundingChangeFailure('prepared funding schedule SHA mismatch')
            table = pd.read_json(item['path'], orient='table')
            self.change_tables[pair] = table
            self.event_lookup[pair] = {r.execution_at: r._asdict() for r in table.itertuples(index=False)}

    def populate_indicators(self, dataframe, metadata):
        return dataframe.merge(self.change_tables[metadata['pair']], on='date', how='left', validate='one_to_one')

    def populate_entry_trend(self, dataframe, metadata):
        field = 'level_direction' if self.config['perp_change_variant'] == 'level_contrarian' else 'change_direction'
        # Only native next-bar shift. No price-derived features or close+60s delay.
        dataframe['enter_long'] = (dataframe[field] == 1).astype(int)
        dataframe['enter_short'] = (dataframe[field] == -1).astype(int)
        dataframe['enter_tag'] = self.config['perp_change_variant']
        return dataframe

    def populate_exit_trend(self, dataframe, metadata):
        dataframe['exit_long'] = 0
        dataframe['exit_short'] = 0
        return dataframe

    def custom_exit(self, pair, trade, current_time, current_rate, current_profit, **kwargs):
        return 'holding_8h' if current_time - trade.open_date_utc >= timedelta(hours=8) else None

    def _consume(self, pair, row, status, at):
        key = (pair, row['event_id'])
        self.consumed_events.add(key)
        self.pending_events.pop(key, None)
        self.event_audit.append(dict(pair=pair, event_id=row['event_id'], execution_at=row['execution_at'].isoformat(),
            at=at.isoformat(), status=status, variant=self.config['perp_change_variant']))

    def bot_loop_start(self, current_time, **kwargs):
        from freqtrade.persistence import LocalTrade
        for (pair, _), row in list(self.pending_events.items()):
            if row['execution_at'] < current_time:
                self._consume(pair, row, 'EXPIRED_NO_ENTRY', current_time)
        for pair in PAIRS:
            row = self.event_lookup[pair].get(current_time)
            if row is None or (pair, row['event_id']) in self.consumed_events:
                continue
            field = 'level_direction' if self.config['perp_change_variant'] == 'level_contrarian' else 'change_direction'
            if row[field] == 0:
                self._consume(pair, row, 'FLAT_ZERO', current_time)
            elif LocalTrade.bt_trades_open_pp.get(pair):
                # Observe BEFORE native exits: its optional second pass must not
                # resurrect an overlapping event after a same-hour reversal exit.
                self._consume(pair, row, 'SKIPPED_OPEN', current_time)
            elif (pair, row['event_id']) not in self.pending_events:
                self.pending_events[(pair, row['event_id'])] = row
                self.event_audit.append(dict(pair=pair, event_id=row['event_id'],
                    execution_at=current_time.isoformat(), at=current_time.isoformat(),
                    status='READY', variant=self.config['perp_change_variant']))

    def _entry_event(self, pair, current_time, entry_tag, side):
        row = self.event_lookup.get(pair, {}).get(current_time)
        if row is None or entry_tag != self.config['perp_change_variant']:
            raise FundingChangeFailure('native entry absent from its frozen funding event')
        key = (pair, row['event_id'])
        if key in self.consumed_events:
            return None
        field = 'level_direction' if entry_tag == 'level_contrarian' else 'change_direction'
        if (key not in self.pending_events or row[field] != (1 if side == 'long' else -1 if side == 'short' else 0) or
                not max(row['available_at'], row['previous_available_at']) < current_time or
                row['date'] + timedelta(hours=1) != current_time):
            raise FundingChangeFailure('native funding entry violates strict availability, direction or loop reservation')
        return row

    def custom_stake_amount(self, pair, current_time, current_rate, proposed_stake, min_stake,
                            max_stake, leverage, entry_tag, side, **kwargs):
        row = self._entry_event(pair, current_time, entry_tag, side)
        if row is None:
            return 0.
        if leverage != 1:
            raise FundingChangeFailure('funding event must use 1x')
        desired = min(self.wallets.get_total_stake_amount() * .4, max_stake)
        accepted = desired if math.isfinite(desired) and desired >= (min_stake or 0.) else 0.
        audit = {key: value.isoformat() if hasattr(value, 'isoformat') else value for key, value in row.items()}
        audit.update(pair=pair, at=current_time.isoformat(), signal_candle=row['date'].isoformat(),
            side=side, variant=entry_tag, multiplier=1., desired_stake=desired,
            accepted_stake=accepted, native_minimum=min_stake, entry_confirmed=False)
        self.entry_audit.append(audit)
        if accepted <= 0:
            self._consume(pair, row, 'SKIPPED_STAKE', current_time)
        return accepted

    def confirm_trade_entry(self, pair, order_type, amount, rate, time_in_force, current_time,
                            entry_tag, side, **kwargs):
        row = self._entry_event(pair, current_time, entry_tag, side)
        if row is None:
            return False
        matches = [r for r in self.entry_audit if r['pair'] == pair and r['event_id'] == row['event_id'] and r['accepted_stake'] > 0]
        if len(matches) != 1:
            raise FundingChangeFailure('native funding entry lacks exactly one accepted stake audit')
        matches[0].update(entry_confirmed=True, native_amount=amount, native_rate=rate)
        self._consume(pair, row, 'ENTRY_CONFIRMED', current_time)
        return True


def run_native_change(root, frames, events, metadata, schedules, variant, start, end):
    """Only strategy/schedule changes; reuse the frozen native wallet/cost assembly."""
    import pandas as pd
    from freqtrade.commands.optimize_commands import setup_optimize_configuration
    from freqtrade.enums import RunMode, CandleType
    from freqtrade.exchange.binance import Binance
    from freqtrade.optimize.backtesting import Backtesting
    from freqtrade.data.history.datahandlers import get_datahandler
    from lab.perp_baseline_runner import native_config, assembly
    from lab.portfolio_native_export import read_strategy_export
    if variant not in VARIANTS:
        raise ValueError('unregistered settled funding variant')
    root = Path(root)
    for name in ('user', 'exports', 'data', 'factors'):
        (root / name).mkdir(parents=True)
    handler = get_datahandler(root / 'data', 'feather')
    files = {}
    for pair, frame in frames.items():
        handler.ohlcv_store(pair, '1h', frame, CandleType.FUTURES)
        path = root / 'factors' / (pair.split('/')[0] + '.json')
        filter_schedule(schedules[pair], start, end).to_json(path, orient='table', date_format='iso', date_unit='us')
        files[pair] = dict(path=str(path), sha256=sha(path))
    value = native_config('persistence', 1.)
    value.update(strategy='PerpFundingChange', perp_change_variant=variant, perp_change_files=files)
    path = root / 'config.json'; write(path, value)
    config = setup_optimize_configuration(dict(command='backtesting', config=[str(path)],
        datadir=str(root / 'data'), user_data_dir=str(root / 'user'), strategy_path=str(REPO / 'lab'),
        strategy='PerpFundingChange', timerange=f'{int(start.timestamp())}-{int(end.timestamp())}', fee=.0008,
        export='trades', exportdirectory=str(root / 'exports'), dataformat_ohlcv='feather',
        disableparamexport=True, backtest_cache='none'), RunMode.BACKTEST)

    class EventBacktesting(Backtesting):
        def _load_bt_data_detail(self):
            if self.timeframe_detail:
                raise FundingChangeFailure('funding change intrahour extension forbidden')
            self.detail_data = {}; self.futures_data = events; self.funding_fee_timeframe_secs = 3600

    class EventBinance(Binance):
        def calculate_funding_fees(self, df, amount, is_short, open_date, close_date):
            return super().calculate_funding_fees(df.loc[df.date > pd.Timestamp(open_date)],
                amount=amount, is_short=is_short, open_date=open_date, close_date=close_date)

    exchange = EventBinance(config, validate=False, load_leverage_tiers=False)
    def deny(*a, **k):
        raise FundingChangeFailure('funding change native worker cannot request exchange')
    exchange._api.fetch = deny; exchange._api_async.fetch = deny
    markets, tiers = assembly(metadata)
    exchange._api.set_markets(markets, {}); exchange._api_async.set_markets(markets, {})
    exchange._markets = exchange._api.markets; exchange._leverage_tiers = tiers
    engine = None
    try:
        engine = EventBacktesting(config, exchange=exchange)
        if len(engine.strategylist) != 1 or set(engine.pairlists.whitelist) != set(PAIRS):
            raise FundingChangeFailure('funding change wallet/pair mismatch')
        began = time.monotonic()
        write(root / 'native-started.json', dict(status='ENGINE_START_RESERVED',
            reserved_at=datetime.now(timezone.utc).isoformat(), variant=variant, native_execution_completion='UNKNOWN'))
        engine.start()
        write(root / 'native-completed.json', dict(status='ENGINE_COMPLETED',
            completed_at=datetime.now(timezone.utc).isoformat(), variant=variant,
            actual_engine_completed=True, engine_seconds=time.monotonic()-began))
        archives = list((root / 'exports').glob('*.zip'))
        if len(archives) != 1:
            raise ValueError('expected one funding change native archive')
        result = read_strategy_export(archives[0], 'PerpFundingChange')
        write(root / 'native-result.json', result)
        write(root / 'entry-audit.json', engine.strategylist[0].entry_audit)
        write(root / 'event-audit.json', engine.strategylist[0].event_audit)
        return result, {p.name: sha(p) for p in archives}
    finally:
        if engine is not None: engine.cleanup()
        exchange.close()
