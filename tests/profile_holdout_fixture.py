"""Artificial daily source and approved Candidate for the Profile continuation tests.

The upstream Search handoff alone is a stub: no Search or economic evidence is
claimed. D preparation/materialization and D/H native execution are production.
"""
import hashlib
import json
import threading
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from lab import bounded_research as pilot, development_run, holdout_run
from lab.codex_generation import load_profile_snapshot
from lab.database import get_connection
from tests.test_development_run import _approved_candidate_database, _frozen_capability_fixture


SOURCE = '''import talib.abstract as ta
from pandas import DataFrame
from technical import qtpylib
from freqtrade.strategy import IStrategy

class BoundedCandidate(IStrategy):
    INTERFACE_VERSION = 3
    timeframe = "1d"
    can_short = False
    startup_candle_count = 20
    process_only_new_candles = True
    minimal_roi = {}
    stoploss = -0.20

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[dataframe["date"].dt.tz_convert("UTC").dt.dayofweek == 0, "enter_long"] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[dataframe["date"].dt.tz_convert("UTC").dt.dayofweek == 3, "exit_long"] = 1
        return dataframe
'''


def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def record(path):
    raw = path.read_bytes()
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def artificial_market():
    return dict(id="ADA-USDT", symbol="ADA/USDT", base="ADA", quote="USDT", settle=None,
                baseId="ADA", quoteId="USDT", active=True, contract=False, swap=False,
                spot=True, future=False, option=False, linear=None, inverse=None, type="spot",
                contractSize=None, expiry=None, precision={"amount": .01, "price": .001},
                limits={"amount": {"min": .01, "max": 1000000}, "price": {"min": .001, "max": None},
                        "cost": {"min": 1., "max": None}, "leverage": {"min": None, "max": None}},
                maker=.0005, taker=.0005, info={"synthetic": True})


def write_artificial_source(root, start, stop):
    import pandas as pd
    import pyarrow.feather as feather
    data = root / "data" / "okx"
    data.mkdir(parents=True, exist_ok=True)
    dates = pd.date_range(start, stop, freq="1D", inclusive="left", tz="UTC")
    prices = [100. + item.dayofweek * 3 for item in dates]
    frame = pd.DataFrame(dict(date=dates, open=prices, high=[v+2 for v in prices],
                              low=[v-1 for v in prices], close=[v+1 for v in prices], volume=10000.))
    # One small losing Friday in each stage gives a finite native profit factor.
    for day in ("2026-03-06", "2026-05-08"):
        mask = frame.date.eq(pd.Timestamp(day, tz="UTC"))
        frame.loc[mask, ["open", "high", "low", "close"]] = [101., 103., 100., 102.]
    feather.write_feather(frame, data / "ADA_USDT-1d.feather", compression="uncompressed")
    (root / "market_snapshot.json").write_bytes(canonical(artificial_market()))
    (root / "isolated_tiers_snapshot.json").write_bytes(canonical({"status": "NOT_APPLICABLE", "trading_mode": "spot"}))
    return {str(path.relative_to(root)): record(path) for path in (
        data / "ADA_USDT-1d.feather", root / "market_snapshot.json", root / "isolated_tiers_snapshot.json")}


def write_artificial_binance_source(root, start, stop, scoring_start, pair='BCH/USDT:USDT'):
    """Synthetic constants only; no exchange data or backtest execution."""
    import pandas as pd
    from lab.futures_costs import binance_identity
    identity=binance_identity(pair)
    start,stop,scoring_start=(pd.to_datetime(value,utc=True) for value in (start,stop,scoring_start))
    data=root/'data/binance/futures';data.mkdir(parents=True,exist_ok=True)
    placeholder=data/f"{identity['base']}-1d.feather"
    if placeholder.exists():
        assert placeholder.read_bytes()==b'development-only\n'
        placeholder.unlink()
    for tf,kind,freq,lower in [('1d','futures','1D',start),('1h','mark','1h',start),
                              ('1h','funding_rate','8h',scoring_start)]:
        dates=pd.date_range(lower,stop,freq=freq,inclusive='left',tz='UTC')
        value=.001 if kind=='funding_rate' else 100.
        pd.DataFrame(dict(date=dates,open=value,high=value,low=value,close=value,volume=0.)).to_feather(data/f"{identity['file_stem']}-{tf}-{kind}.feather")
    market=artificial_market()
    market.update(id=identity['instrument_id'],symbol=pair,base=identity['base'],baseId=identity['base'],settle='USDT',
                  contract=True,swap=True,spot=False,linear=True,inverse=False,type='swap',contractSize=1.)
    (root/'market_snapshot.json').write_bytes(canonical(market))
    (root/'isolated_tiers_snapshot.json').write_bytes(canonical([{'symbol':pair}]))
    events=[{'symbol':identity['instrument_id'],'fundingTime':int(date.value//1_000_000),'fundingRate':'0.001','markPrice':'100'}
            for date in pd.date_range(scoring_start,stop,freq='8h',inclusive='left',tz='UTC')]
    local={str(path.relative_to(root)):record(path) for path in (*data.iterdir(),root/'market_snapshot.json',root/'isolated_tiers_snapshot.json')}
    return local,events


def prepared_profile_development(root, monkeypatch, *, python=None, native_source=None,
                                 development_stop="2026-05-01", holdout_days=61, binance=False, binance_pair='BCH/USDT:USDT'):
    from lab.futures_costs import binance_identity
    identity=binance_identity(binance_pair)
    root.mkdir(parents=True, exist_ok=True)
    database, candidate_id = _approved_candidate_database(
        root, pair=binance_pair if binance else "ADA/USDT", timeframe="1d", spot=not binance,
        source_text=SOURCE.replace('can_short = False','can_short = True') if binance else SOURCE,
        exchange='binance' if binance else 'okx',
        min_development_trades=1, holdout_days=holdout_days,
    )
    with get_connection(database, read_only=True) as connection:
        profile_id = connection.execute("SELECT research_profile_id FROM generation_runs").fetchone()[0]
        profile = load_profile_snapshot(connection, profile_id)
    contract = pilot.profile_search_contract(profile, "20260125-20260301", "20260301-" + development_stop.replace("-", ""), 20)
    # The old compact helper patches only runtime identity. Real native runs
    # restore those patches before freezing the actual pinned runtime.
    with monkeypatch.context() as fixture_patch:
        pilot_root, fake_python, fake_source = _frozen_capability_fixture(
            root / "capability", fixture_patch, pair=binance_pair if binance else "ADA/USDT", instrument_id=identity['instrument_id'] if binance else "ADA-USDT",
            timeframe="1d", profile_contract=contract,
        )
    isolation = pilot_root / "development-isolation"
    if binance:
        local,events=write_artificial_binance_source(isolation,'2026-02-09',development_stop,'2026-03-01',pair=binance_pair)
    else:
        local = write_artificial_source(isolation, "2026-02-09", development_stop)
    acquisition = pilot_root / "acquisition"
    for name in ("market_snapshot.json", "isolated_tiers_snapshot.json"):
        (acquisition / name).write_bytes((isolation / name).read_bytes())
    provenance_path = isolation / "retained-data-provenance.json"
    provenance = json.loads(provenance_path.read_bytes())
    provenance["local_only_files"] = local
    if binance:
        from lab.futures_costs import CONTRACT
        provenance['source'].update(funding_model=CONTRACT,funding_events=events)
    provenance_path.write_bytes(canonical(provenance))
    if python is None:
        python, native_source = fake_python, fake_source
        monkeypatch.setattr(development_run, "_verify_python", lambda _: None)
        def git_value(_source, *args):
            return {("rev-parse", "HEAD"): development_run.SUPPORTED_FREQTRADE_COMMIT,
                    ("rev-parse", "HEAD^{tree}"): development_run.SUPPORTED_FREQTRADE_TREE,
                    ("describe", "--exact-match", "--tags", "HEAD"): "2026.7",
                    ("status", "--porcelain=v1", "--untracked-files=all"): ""}[args]
        monkeypatch.setattr(development_run, "_git_value", git_value)
    capability = development_run.freeze_development_capability(pilot_root, python, native_source, profile_contract=contract)
    assert capability.status == "READY", capability.reason
    run_id = str(uuid4())
    run_dir = root / "runtime" / "campaigns" / run_id
    run_dir.mkdir(parents=True)
    with monkeypatch.context() as handoff_stub:
        from lab import search_campaign
        handoff_stub.setattr(search_campaign, "verify_persisted_finalist_projection", lambda *args: {})
        handoff_stub.setattr(development_run, "_verified_search_finalist_binding", lambda *args: None)
        development_run.prepare_development_run(database, run_dir, candidate_id, capability,
                                                research_run_id=run_id, search_finalist_binding={})
    return database, run_id, run_dir, capability


def authorized_artificial_holdout(database, run_id, *, binance=False):
    if binance:
        from lab.futures_costs import CONTRACT, binance_identity
        output,auth=holdout_run.authorize_profile_holdout_source(database,run_id)
        identity=binance_identity(auth['profile_snapshot']['pairs'][0])
        output.mkdir()
        local,events=write_artificial_binance_source(output,auth['data_start_utc'],auth['end_exclusive_utc'],
                                                    auth['holdout_timerange'].split('-')[0],pair=identity['pair'])
        (output/'funding-events.json').write_bytes(canonical(events))
        (output/'config.json').write_bytes(canonical(pilot.profile_search_config(auth['profile_snapshot'])))
        (output/'retained-data-provenance.json').write_bytes(canonical({
            'contract':{'holdout_source':auth},'local_only_files':local,
            'source':{'host':'fapi.binance.com','authentication':'none','exchange':'binance',
                      **{k:identity[k] for k in ('pair','instrument_id','pair_family')},'funding_model':CONTRACT,
                      'funding_events_receipt':record(output/'funding-events.json')}}))
        return output
    from scripts import fetch_okx_profile_data as producer
    output = producer.configure_holdout_acquisition(database, run_id)
    output.mkdir()
    auth = producer.PROFILE_ACQUISITION["holdout_source"]
    write_artificial_source(output, auth["data_start_utc"], auth["end_exclusive_utc"])
    receipt = output / "retrieval_receipt.json"
    receipt.write_bytes(canonical({"TEST_ONLY_SYNTHETIC": True, "market_requests": 0, "holdout_source": auth}))
    producer.write_profile_provenance(output, receipt, {
        "freqtrade_tag": "2026.7", "freqtrade_commit": producer.EXPECTED_FREQTRADE_COMMIT,
        "versions": producer.EXPECTED_VERSIONS,
    })
    return output


def passed_profile_development_stub(root, monkeypatch, *, holdout_days=61, binance=False, binance_pair='BCH/USDT:USDT'):
    """Only the imported D artifact is a stub; preparation and gates are real."""
    from dataclasses import replace
    from lab.backtest_artifact import execution_result_values
    from tests.test_holdout_run import _eligible_run
    legacy_root = root / "legacy-parser-seed"
    legacy_root.mkdir(parents=True)
    _, _, _, _, template = _eligible_run(legacy_root, monkeypatch)
    database, run_id, run_dir, capability = prepared_profile_development(root / "profile", monkeypatch, holdout_days=holdout_days,binance=binance,binance_pair=binance_pair)
    evidence = run_dir / "development-evidence"
    evidence.mkdir()
    archive = evidence / "development-01.zip"
    archive.write_bytes(b"TEST_ONLY_SYNTHETIC profile D artifact\n")
    parsed = replace(template, archive_path=archive, archive_sha256=record(archive)["sha256"],
                     strategy_source=SOURCE, strategy_sha256=hashlib.sha256(SOURCE.encode()).hexdigest(),
                     trading_mode="spot", margin_mode="", pairs=("ADA/USDT",), timeframe="1d",
                     backtest_start="2026-03-01T00:00:00Z", backtest_end="2026-04-30T00:00:00Z",
                     total_trades=8, profit_pct=1., net_profit_after_base_fees_pct=1., profit_factor=2.,
                     max_drawdown_pct=1., wins=7, losses=1, roi_exit_count=0,
                     average_holding_period_minutes=4320.)
    if binance:
        from lab.futures_costs import CONTRACT
        source=SOURCE.replace('can_short = False','can_short = True')
        adjustments=[{'native_profit_abs':2.,'funding_deduction_abs':0.,'conservative_profit_abs':2.} for _ in range(7)]
        adjustments.append({'native_profit_abs':-4.,'funding_deduction_abs':0.,'conservative_profit_abs':-4.})
        parsed=replace(parsed,exchange='binance',trading_mode='futures',margin_mode='isolated',pairs=(binance_pair,),
                       strategy_source=source,strategy_sha256=hashlib.sha256(source.encode()).hexdigest(),
                       funding_audit={'contract':CONTRACT,'native_artifact_unchanged':True,'funding_deduction_abs':0.,
                            'conservative_net_profit_pct':1.,'conservative_final_balance':1010.,
                            'conservative_mtm_drawdown_pct':1.,'minimum_free_cash':900.,'cash_executable':True,
                            'conservative_profit_factor':3.5,'conservative_loss_count':1,'trade_adjustments':adjustments})
    values = execution_result_values(parsed)
    with get_connection(database) as connection:
        fields = {key: value for key, value in values.items() if key != "result_archive_path"}
        fields.update(result_archive_path=str(archive), status="SUCCEEDED", return_code=0)
        connection.execute("UPDATE backtest_executions SET " + ",".join(key + "=?" for key in fields)
                           + " WHERE research_run_id=?", (*fields.values(), run_id))
        connection.commit()
    development_run.finalize_development_gate(database, run_id)
    monkeypatch.setattr(holdout_run, "parse_backtest_artifact", lambda *args, **kwargs: parsed)
    return database, run_id, run_dir, capability


@contextmanager
def profile_console(database, run_id, run_dir, development, monkeypatch):
    """Real Console startup and HTTP with an explicitly synthetic upstream Search."""
    from lab import research_console, search_campaign
    contract = development.profile_contract
    search_root = run_dir.parent.parent / "synthetic-search"
    search_root.mkdir(exist_ok=True)
    capability = search_campaign.FrozenSearchCapability(
        status="READY", reason="TEST_ONLY_SYNTHETIC upstream Search",
        search_root=search_root, profile_snapshot=contract["profile_snapshot"],
        search_timerange=contract["search_timerange"], development_timerange=contract["development_timerange"],
        pre_roll_candles=contract["pre_roll_candles"], source_acquisition_sha256=development.source_acquisition_sha256,
    )
    with monkeypatch.context() as upstream:
        upstream.setattr(research_console, "freeze_search_capability", lambda *args: capability)
        upstream.setattr(research_console.ResearchConsoleController, "_finalize_search_terminal", lambda *args, **kwargs: None)
        server = research_console.create_research_console_server(
            database, run_dir.parent.parent, development.pilot_root, 0,
            search_root=search_root, holdout_research_run_id=run_id,
            artifact_root=run_dir, codex_binary=run_dir / "missing-codex",
            freqtrade_python=development.freqtrade_python, freqtrade_source=development.freqtrade_source,
            task_timeout_seconds=180,
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield server
        finally:
            server.research_console_controller.shutdown()
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
