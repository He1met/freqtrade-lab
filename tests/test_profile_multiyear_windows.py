"""Daily Profile resource bounds; all prices synthetic, no native invocation."""
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from lab import bounded_research as pilot, development_run, holdout_run
from lab.database import get_connection
from tests.test_spot_research import spot_profile


@pytest.mark.parametrize("mode,timeframe,days,pre_roll,valid", [
    ("spot", "1d", 366, 90, True), ("spot", "1d", 367, 90, True),
    ("spot", "1d", 1830, 512, True), ("spot", "1d", 1831, 90, False),
    ("spot", "1d", 1830, 513, False), ("spot", "5m", 367, 90, False),
    ("futures", "5m", 366, 90, True), ("futures", "5m", 367, 90, False),
    ("futures", "1d", 366, 90, True), ("futures", "1d", 367, 90, False),
])
def test_daily_calendar_and_source_row_bounds(mode, timeframe, days, pre_roll, valid):
    start = datetime(2020, 1, 1, tzinfo=timezone.utc)
    window = f"{start:%Y%m%d}-{start + timedelta(days=days):%Y%m%d}"
    if not valid:
        with pytest.raises(pilot.PilotError):
            pilot._profile_window_contract(window, phase="Search", timeframe=timeframe,
                                            trading_mode=mode, pre_roll_candles=pre_roll)
        return
    parsed = pilot._profile_window_contract(window, phase="Search", timeframe=timeframe,
                                            trading_mode=mode, pre_roll_candles=pre_roll)
    if mode == "spot" and timeframe == "1d":
        assert parsed["rows"] == {"spot_1d": days + pre_roll}
        assert parsed["rows"]["spot_1d"] <= 2342


def test_validated_profile_checks_resource_limit_before_data(tmp_path):
    _, profile = spot_profile(tmp_path)
    profile["timeframe"] = "1d"
    profile["history_start_date"] = "2019-01-01"
    contract = pilot.profile_search_contract(profile, "20200101-20220101", "20220101-20230702", 90)
    assert contract["holdout"] == "SEALED_UNREAD"
    with pytest.raises(pilot.PilotError, match="bounded duration"):
        pilot.profile_search_contract(profile, "20200101-20260101", "20260101-20260301", 90)
    with pytest.raises(development_run.DevelopmentRunError, match="366"):
        development_run._development_window("20220101-20230702")
    assert development_run._development_window("20220101-20230702", profile_contract=contract)[2] == "2023-07-02T00:00:00Z"


def test_547_day_development_freeze_snapshot_and_materialization(tmp_path, monkeypatch):
    from tests.profile_holdout_fixture import prepared_profile_development
    database, run_id, directory, capability = prepared_profile_development(
        tmp_path, monkeypatch, development_stop="2027-08-30")
    assert capability.status == "READY"
    with get_connection(database, read_only=True) as connection:
        snapshot = json.loads(connection.execute("SELECT input_snapshot_json FROM research_runs WHERE id=?", (run_id,)).fetchone()[0])
        execution = connection.execute("SELECT timerange_start,timerange_end FROM backtest_executions WHERE research_run_id=?", (run_id,)).fetchone()
    assert snapshot["exclusive_stop_utc"] == "2027-08-30T00:00:00Z"
    assert tuple(execution) == ("2026-03-01T00:00:00Z", "2027-08-29T00:00:00Z")
    assert (directory / "development-input/manifest.json").is_file()


@pytest.mark.parametrize("holdout_days,lookback,valid", [(699, 20, True), (1831, 20, False), (699, 513, False)])
def test_holdout_actual_authorization_checks_resources_before_writes(tmp_path, monkeypatch, holdout_days, lookback, valid):
    from lab import bounded_strategy
    from tests.profile_holdout_fixture import passed_profile_development_stub
    database, run_id, directory, _ = passed_profile_development_stub(tmp_path, monkeypatch, holdout_days=holdout_days)
    class ClosedWindowClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2035, 1, 1, tzinfo=timezone.utc)
    monkeypatch.setattr(holdout_run, "datetime", ClosedWindowClock)
    if lookback > 512:
        monkeypatch.setattr(bounded_strategy, "analyze_bounded_causal_strategy", lambda *args, **kwargs: SimpleNamespace(startup_candle_count=lookback))
    with get_connection(database, read_only=True) as connection:
        before = list(connection.iterdump())
    if valid:
        output, authorization = holdout_run.authorize_profile_holdout_source(database, run_id)
        assert output == directory / "holdout-source"
        assert authorization["profile_snapshot"]["holdout_days"] == holdout_days
        assert (directory / "holdout-source-authorization.json").is_file()
    else:
        with pytest.raises(holdout_run.HoldoutRunError) as error:
            holdout_run.authorize_profile_holdout_source(database, run_id)
        assert error.value.code == "run_not_eligible"
        assert not (directory / "holdout-source-authorization.json").exists()
    assert not (directory / "holdout-source").exists()
    with get_connection(database, read_only=True) as connection:
        assert list(connection.iterdump()) == before
