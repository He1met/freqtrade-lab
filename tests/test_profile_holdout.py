"""Profile Holdout boundaries, using synthetic inputs only."""
import json

import pytest

from lab import bounded_research as pilot
from lab import holdout_run
from lab.codex_generation import load_profile_snapshot
from lab.database import get_connection
from scripts.run_freqtrade_backtest import OfflineBacktestError, _verify_profile_runtime_contract
from tests.test_holdout_run import _eligible_run
from tests.test_spot_research import spot_profile


def _runtime(tmp_path):
    _, profile = spot_profile(tmp_path)
    profile.update(timeframe="1d", taker_fee_rate=.001, stress_fee_multiplier=2., min_profit_factor=1.)
    normalized = pilot.validate_profile_runtime_contract(profile)
    config = pilot.profile_search_config(profile)
    config.update(config_files=["/synthetic/config.json"], datadir="/synthetic/data", export="trades",
                  exportdirectory="/synthetic/output", strategy_path="/synthetic/strategies",
                  timerange="20240101-20240201", user_data_dir="/synthetic/user")
    source = dict(schema="freqtrade-lab-profile-holdout-source-v1", action="AUTHORIZE_HOLDOUT_SOURCE",
                  profile_snapshot=profile, profile_snapshot_sha256=normalized["profile_snapshot_sha256"],
                  holdout_timerange="20240101-20240201", pre_roll_candles=20,
                  data_start_utc="2023-12-12T00:00:00+00:00", end_exclusive_utc="2024-02-01T00:00:00+00:00")
    provenance = {"contract": {"profile_snapshot": profile,
                   "profile_snapshot_sha256": normalized["profile_snapshot_sha256"],
                   "holdout_timerange": "20240101-20240201", "holdout_source": source}}
    return config, provenance


@pytest.mark.parametrize("scenario,fee,valid", [
    ("HOLDOUT", .001, True), ("HOLDOUT_STRESS", .002, True),
    ("HOLDOUT", .002, False), ("HOLDOUT_STRESS", .001, False),
    ("HOLDOUT_STRESS", .003, False), ("DEVELOPMENT", .002, False), ("SEARCH", .001, False),
])
def test_stage_bound_profile_fee(tmp_path, scenario, fee, valid):
    config, provenance = _runtime(tmp_path)
    config["fee"] = fee
    if valid:
        _verify_profile_runtime_contract(provenance, config, scenario=scenario)
    else:
        with pytest.raises(OfflineBacktestError):
            _verify_profile_runtime_contract(provenance, config, scenario=scenario)


@pytest.mark.parametrize("value", [None, [], 3, "bad", {}, {"schema": []}])
def test_untrusted_holdout_source_controlled_failure(tmp_path, value):
    config, provenance = _runtime(tmp_path)
    config["fee"] = .002
    provenance["contract"]["holdout_source"] = value
    with pytest.raises(OfflineBacktestError):
        _verify_profile_runtime_contract(provenance, config, scenario="HOLDOUT_STRESS")


def test_profile_pf_one_eligible_and_frozen_gate_tamper_rejected(tmp_path, monkeypatch):
    database, run_id, _directory, _capability, _parsed = _eligible_run(tmp_path, monkeypatch)
    with get_connection(database) as connection:
        row = connection.execute("SELECT research_profile_id,input_snapshot_json FROM research_runs WHERE id=?", (run_id,)).fetchone()
        connection.execute("UPDATE research_profiles SET min_profit_factor=1.0,min_development_trades=6,max_drawdown_pct=20 WHERE id=?", (row["research_profile_id"],))
        profile = load_profile_snapshot(connection, row["research_profile_id"])
        normalized = pilot.validate_profile_runtime_contract(profile)
        snapshot = json.loads(row["input_snapshot_json"])
        snapshot.update(normalized_profile_contract=normalized, gate=normalized["finalist_gate"])
        connection.execute("UPDATE research_runs SET input_snapshot_json=? WHERE id=?", (json.dumps(snapshot), run_id))
        connection.execute("UPDATE backtest_executions SET total_trades=6,profit_factor=1.0 WHERE research_run_id=?", (run_id,))
        connection.commit()
        holdout_run._eligible_row(connection, run_id, parse_artifact=False)
        snapshot["gate"]["minimum_profit_factor"] = .9
        connection.execute("UPDATE research_runs SET input_snapshot_json=? WHERE id=?", (json.dumps(snapshot), run_id))
        with pytest.raises(holdout_run.HoldoutRunError, match="frozen Gate"):
            holdout_run._eligible_row(connection, run_id, parse_artifact=False)


@pytest.mark.parametrize('binance_pair', ['BCH/USDT:USDT', 'ADA/USDT:USDT', 'BNB/USDT:USDT'])
def test_binance_missing_associated_mark_fails_before_continuation_write(tmp_path,monkeypatch,binance_pair):
    pytest.importorskip('pyarrow')
    from tests.profile_holdout_fixture import passed_profile_development_stub,authorized_artificial_holdout,canonical,record
    database,run_id,directory,development=passed_profile_development_stub(tmp_path,monkeypatch,binance=True,binance_pair=binance_pair)
    source=authorized_artificial_holdout(database,run_id,binance=True)
    path=source/'funding-events.json'
    events=json.loads(path.read_bytes());events[0]['markPrice']=''
    path.write_bytes(canonical(events))
    provenance=json.loads((source/'retained-data-provenance.json').read_bytes())
    provenance['source']['funding_events_receipt']=record(path)
    (source/'retained-data-provenance.json').write_bytes(canonical(provenance))
    capability=holdout_run.freeze_profile_holdout_capability(database,run_id,development)
    assert capability.status=='READY'  # metadata-only readiness does not read values
    with get_connection(database,read_only=True) as connection:
        before=[tuple(row) for row in connection.execute('SELECT status,stage,input_snapshot_json FROM research_runs WHERE id=?',(run_id,))]
    with pytest.raises(holdout_run.HoldoutRunError,match='funding source is incomplete'):
        holdout_run.prepare_holdout_continuation(database,directory,run_id,capability)
    with get_connection(database,read_only=True) as connection:
        assert [tuple(row) for row in connection.execute('SELECT status,stage,input_snapshot_json FROM research_runs WHERE id=?',(run_id,))]==before
        assert connection.execute('SELECT COUNT(*) FROM backtest_executions WHERE research_run_id=?',(run_id,)).fetchone()[0]==1
    assert not (directory/'holdout-input').exists()
    assert not (directory/'.holdout-input-preparing').exists()


def test_spot_daily_development_preparation_keeps_holdout_unopened(tmp_path, monkeypatch):
    pytest.importorskip("pyarrow")
    from tests.profile_holdout_fixture import prepared_profile_development
    database, run_id, directory, capability = prepared_profile_development(tmp_path, monkeypatch)
    assert not (directory / "holdout-source").exists()
    assert not (directory / "holdout-source-authorization.json").exists()
    with pytest.raises(holdout_run.HoldoutRunError) as error:
        holdout_run.authorize_profile_holdout_source(database, run_id)
    assert error.value.code == "run_not_eligible"
    assert not (directory / "holdout-source-authorization.json").exists()
    assert capability.timeframe == "1d"


@pytest.mark.parametrize('binance,binance_pair',[(False,'BCH/USDT:USDT'),(True,'BCH/USDT:USDT'),(True,'DOGE/USDT:USDT'),(True,'ADA/USDT:USDT'),(True,'BNB/USDT:USDT')])
def test_profile_holdout_source_and_preparation_preserve_development(tmp_path, monkeypatch, binance, binance_pair):
    pytest.importorskip("pyarrow")
    from tests.profile_holdout_fixture import passed_profile_development_stub, authorized_artificial_holdout
    database, run_id, directory, development = passed_profile_development_stub(tmp_path, monkeypatch,binance=binance,binance_pair=binance_pair)
    with get_connection(database, read_only=True) as connection:
        before = json.loads(connection.execute("SELECT input_snapshot_json FROM research_runs WHERE id=?", (run_id,)).fetchone()[0])
    source = authorized_artificial_holdout(database, run_id,binance=binance)
    original = holdout_run._read_regular
    def metadata_only(path, *args, **kwargs):
        assert not str(path).endswith((".feather", "market_snapshot.json", "isolated_tiers_snapshot.json", "funding-events.json"))
        return original(path, *args, **kwargs)
    with monkeypatch.context() as unread:
        unread.setattr(holdout_run, "_read_regular", metadata_only)
        capability = holdout_run.freeze_profile_holdout_capability(database, run_id, development)
    assert capability.status == "READY", capability.reason
    holdout_run.prepare_holdout_continuation(database, directory, run_id, capability)
    with get_connection(database, read_only=True) as connection:
        after = json.loads(connection.execute("SELECT input_snapshot_json FROM research_runs WHERE id=?", (run_id,)).fetchone()[0])
        executions = connection.execute("SELECT scenario,timeframe,fee_rate FROM backtest_executions WHERE research_run_id=? ORDER BY sequence", (run_id,)).fetchall()
        ends = connection.execute("SELECT timerange_end FROM backtest_executions WHERE research_run_id=? ORDER BY sequence", (run_id,)).fetchall()
    assert {key: after[key] for key in before} == before
    assert [tuple(row) for row in executions] == [("DEVELOPMENT", "1d", .0005), ("HOLDOUT", "1d", .0005), ("HOLDOUT_STRESS", "1d", .001)]
    assert source == directory / "holdout-source"
    assert [row[0] for row in ends] == ["2026-04-30T00:00:00Z", "2026-06-30T00:00:00Z", "2026-06-30T00:00:00Z"]


@pytest.mark.parametrize('binance,binance_pair',[(False,'BCH/USDT:USDT'),(True,'BCH/USDT:USDT'),(True,'DOGE/USDT:USDT'),(True,'ADA/USDT:USDT'),(True,'BNB/USDT:USDT')])
def test_profile_actual_http_entry_authorizes_same_run_and_keeps_release_sealed(tmp_path, monkeypatch, binance, binance_pair):
    pytest.importorskip("pyarrow")
    import subprocess
    from tests.profile_holdout_fixture import passed_profile_development_stub, authorized_artificial_holdout, profile_console
    from tests.test_development_console_http import _post
    from tests.test_research_console import _request
    database, run_id, run_dir, development = passed_profile_development_stub(tmp_path, monkeypatch,binance=binance,binance_pair=binance_pair)
    authorized_artificial_holdout(database, run_id,binance=binance)
    original_popen = subprocess.Popen
    workers = []
    def stub_worker(argv, **kwargs):
        if len(argv) > 1 and str(argv[1]).endswith("run_holdout_continuation.py"):
            workers.append(tuple(argv))
            return original_popen(["/bin/sleep", "30"], **kwargs)
        return original_popen(argv, **kwargs)
    monkeypatch.setattr(subprocess, "Popen", stub_worker)
    with profile_console(database, run_id, run_dir, development, monkeypatch) as server:
        status, _, _, initial = _request(server, f"/api/research-runs/{run_id}")
        assert status == 200, initial
        assert initial["authorization"]["can_authorize"] is True, initial
        status, _, _, public = _post(server, f"/api/research-runs/{run_id}/actions", {"action": "AUTHORIZE_HOLDOUT"})
        assert status == 202, public
        assert len(workers) == 1
        assert [item["scenario"] for item in public["executions"]] == ["DEVELOPMENT", "HOLDOUT", "HOLDOUT_STRESS"]
        assert public["manual_review"]["can_pass_and_create_release"] is False
        status, _, _, _ = _post(server, f"/api/research-runs/{run_id}/actions", {"action": "AUTHORIZE_HOLDOUT"})
        assert status == 409
