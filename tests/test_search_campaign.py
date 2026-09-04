"""T0 contracts for the thin Console-to-screen_search adapter."""

from __future__ import annotations

import fcntl
import json
from dataclasses import replace
from pathlib import Path

import pytest

from lab import search_campaign
from lab.bounded_strategy import analyze_bounded_causal_strategy
from lab.database import get_connection
from lab import bounded_research as pilot
from tests.test_development_run import BOUNDED_SOURCE, _approved_candidate_database


def _frozen_capability(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    database: Path,
    candidate_id: str,
    economic_gate: dict[str, object] | None = None,
) -> search_campaign.FrozenSearchCapability:
    with get_connection(database, read_only=True) as connection:
        connection.execute("BEGIN")
        profile = search_campaign.load_approved_candidate_snapshot(
            connection, candidate_id
        ).profile
    root = tmp_path / "search-root"
    (root / "acquisition").mkdir(parents=True)
    root.chmod(0o700)
    python = tmp_path / "freqtrade-python"
    python.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    python.chmod(0o700)
    source = tmp_path / "freqtrade-source"
    source.mkdir()
    python_info = python.stat()
    source_info = source.stat()
    acquisition = {
        "search_timerange": "20260103-20260205",
        "data_provenance_sha256": "a" * 64,
        "source_acquisition_sha256": "b" * 64,
        "pair": profile["pairs"][0],
        "timeframe": profile["timeframe"],
        "base_fee": profile["taker_fee_rate"],
        "profile_snapshot": profile,
        "profile_snapshot_sha256": pilot.digest(pilot.canonical(profile)),
        "development_timerange": "20260205-20260307",
        "pre_roll_candles": 20,
    }
    if economic_gate is not None:
        acquisition["economic_gate"] = dict(economic_gate)
    freqtrade = {
        "freqtrade_python": python,
        "freqtrade_source": source,
        "python_identity": (
            python_info.st_dev,
            python_info.st_ino,
            python_info.st_size,
            python_info.st_mtime_ns,
        ),
        "source_identity": (source_info.st_dev, source_info.st_ino),
    }
    monkeypatch.setattr(
        search_campaign,
        "_acquisition_snapshot",
        lambda _root, _database: dict(acquisition),
    )
    monkeypatch.setattr(
        search_campaign,
        "_freqtrade_snapshot",
        lambda _python, _source: freqtrade,
    )
    monkeypatch.setattr(
        pilot, "verify_data", lambda *_args, **_kwargs: {"status": "DATA_READY"}
    )
    capability = search_campaign.freeze_search_capability(
        database, root, python, source
    )
    assert capability.status == "READY"
    return capability


def _profile_id(capability: search_campaign.FrozenSearchCapability) -> str:
    assert capability.profile_snapshot is not None
    return str(capability.profile_snapshot["id"])


def _economic_search_trial(**overrides: object) -> dict[str, object]:
    metrics: dict[str, object] = {
        "total_trades": 3,
        "net_profit_after_base_fees_pct": 0.5,
        "max_drawdown_pct": 15.0,
        "profit_factor": 1.1,
        "gross_profit_before_fees_pct": 0.6,
        "configured_fee_cost_pct": 0.1,
        "average_holding_period_minutes": 4320.0,
        "roi_exit_count": 0,
        "direction_concentration": 1.0,
        "market_state_concentration": 0.5,
        "market_state_definition": pilot.MARKET_STATE_DEFINITION,
        "market_state_lookback_candles": 21,
    }
    metrics.update(overrides)
    return {
        "candidate_id": "economic-candidate",
        "class_name": "EconomicCandidate",
        "mechanism": "trend",
        "strategy_sha256": "a" * 64,
        "round": 2,
        "attempt_number": 2,
        "technical_status": "VALID",
        "search_metrics": metrics,
    }


def test_t1_search_finalist_requires_profile_and_all_economic_gate_boundaries() -> None:
    profile_gate = {
        "name": pilot.PROFILE_SEARCH_GATE,
        "minimum_trades": 3,
        "minimum_profit_factor": 1.1,
        "maximum_drawdown_pct": 15.0,
        "net_profit_after_fees": "STRICTLY_POSITIVE",
    }
    economic_gate = {
        "name": pilot.PROFILE_ECONOMIC_GATE,
        "version": 1,
        "minimum_net_profit_after_base_fees_pct": 0.5,
        "minimum_average_holding_period_minutes": 4320.0,
        "maximum_roi_exit_count": 0,
    }
    passing = _economic_search_trial()
    assert pilot._search_finalist([passing], profile_gate, economic_gate) == (
        pilot._search_parent(passing)
    )

    for overrides in (
        {"net_profit_after_base_fees_pct": 0.49, "gross_profit_before_fees_pct": 0.59},
        {"average_holding_period_minutes": 4319.0},
        {"roi_exit_count": 1},
        {"roi_exit_count": None},
    ):
        assert pilot._search_finalist(
            [_economic_search_trial(**overrides)], profile_gate, economic_gate
        ) is None
    with pytest.raises(pilot.PilotError):
        pilot._search_finalist(
            [_economic_search_trial(average_holding_period_minutes=None)],
            profile_gate,
            economic_gate,
        )


def test_t1_negative_valid_search_result_remains_a_parent_not_a_finalist() -> None:
    trial = _economic_search_trial(
        net_profit_after_base_fees_pct=-0.2,
        gross_profit_before_fees_pct=-0.1,
    )
    ranked = pilot._rank_search_results([trial])
    assert pilot._search_parent(ranked[0])["search_metrics"][
        "net_profit_after_base_fees_pct"
    ] == -0.2
    assert pilot._search_finalist(
        ranked,
        {
            "minimum_trades": 3,
            "minimum_profit_factor": 1.1,
            "maximum_drawdown_pct": 15.0,
        },
        {
            "name": pilot.PROFILE_ECONOMIC_GATE,
            "version": 1,
            "minimum_net_profit_after_base_fees_pct": 0.5,
            "minimum_average_holding_period_minutes": 4320.0,
            "maximum_roi_exit_count": 0,
        },
    ) is None


def test_t1_search_plan_freezes_gate_and_drift_fails_before_side_effects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database, candidate_id = _approved_candidate_database(tmp_path)
    gate = {
        "name": pilot.PROFILE_ECONOMIC_GATE,
        "version": 1,
        "minimum_net_profit_after_base_fees_pct": 0.5,
        "minimum_average_holding_period_minutes": 4320.0,
        "maximum_roi_exit_count": 0,
    }
    capability = _frozen_capability(
        tmp_path, monkeypatch, database, candidate_id, gate
    )
    try:
        before = search_campaign.business_table_digest(database)
        drifted = replace(
            capability,
            economic_gate={
                **gate,
                "minimum_net_profit_after_base_fees_pct": 0.6,
            },
        )
        with pytest.raises(search_campaign.SearchCampaignError) as raised:
            _prepare_round_one(
                database,
                drifted,
                [candidate_id],
                campaign_id="economic-gate-drift",
            )
        assert raised.value.code == "BLOCKED_DATA"
        assert search_campaign.business_table_digest(database) == before
        assert capability.search_root is not None
        assert not (capability.search_root / pilot.SEARCH_CAMPAIGN).exists()

        prepared = _prepare_round_one(
            database,
            capability,
            [candidate_id],
            campaign_id="economic-gate-bound",
        )
        plan = pilot.load_plan(capability.search_root, pilot.SEARCH_CAMPAIGN)
        assert prepared.campaign_id == "economic-gate-bound"
        assert plan["economic_gate"] == gate
    finally:
        capability.close()


def _prepare_round_one(
    database: Path,
    capability: search_campaign.FrozenSearchCapability,
    candidate_ids: list[str],
    *,
    campaign_id: str,
) -> search_campaign.PreparedSearchRound:
    return search_campaign.prepare_round_one(
        database,
        capability,
        candidate_ids,
        campaign_id=campaign_id,
        profile_id=_profile_id(capability),
    )


def _append_records(root: Path, records: list[dict[str, object]]) -> bytes:
    body = b"".join(pilot.canonical(item) for item in records)
    (root / pilot.SEARCH_TRIALS).write_bytes(body)
    return body


def _round_one_no_parent_receipts(
    capability: search_campaign.FrozenSearchCapability,
) -> str:
    assert capability.search_root is not None
    root = capability.search_root
    plan = pilot.load_plan(root, pilot.SEARCH_CAMPAIGN)
    candidate = plan["candidates"][0]
    started = {
        "schema": pilot.SEARCH_TRIAL_SCHEMA,
        "record_type": "ROUND_STARTED",
        "campaign_id": plan["campaign_id"],
        "campaign_sha256": plan["_sha256"],
        "round": 1,
        "attempt_numbers": [1],
    }
    trial = {
        "schema": pilot.SEARCH_TRIAL_SCHEMA,
        "record_type": "TRIAL",
        "campaign_id": plan["campaign_id"],
        "round": 1,
        "attempt_number": 1,
        "candidate_id": candidate["candidate_id"],
        "class_name": candidate["class_name"],
        "mechanism": candidate["mechanism"],
        "strategy_sha256": candidate["strategy_sha256"],
        "relationship": "MECHANISM_SEED",
        "changed_factor": None,
        "technical_status": "INVALID",
        "failure_reason": "bounded failure",
        "search_metrics": None,
    }
    current_result = {
        key: value
        for key, value in trial.items()
        if key
        not in {
            "schema",
            "record_type",
            "campaign_id",
            "round",
            "attempt_number",
        }
    }
    brief, status, finalist = pilot._search_round_outcome(
        plan, [trial], [current_result], 0
    )
    assert status == "SEARCH_TERMINATED_NO_PARENT"
    assert finalist is None
    receipt = {
        "schema": pilot.SEARCH_TRIAL_SCHEMA,
        "record_type": "ROUND_RECEIPT",
        "campaign_id": plan["campaign_id"],
        "campaign_sha256": plan["_sha256"],
        "contract_sha256": plan["_contract_sha256"],
        "round": 1,
        "status": "SEARCH_TERMINATED_NO_PARENT",
        "ledger_prefix_sha256": pilot.digest(
            pilot.canonical(started) + pilot.canonical(trial)
        ),
        "brief": brief,
        "created_at_utc": "2026-09-01T00:00:00.000Z",
    }
    ledger = _append_records(root, [started, trial, receipt])
    terminal = {
        "schema": pilot.SEARCH_TERMINAL_SCHEMA,
        "campaign_id": plan["campaign_id"],
        "campaign_sha256": plan["_sha256"],
        "contract_sha256": plan["_contract_sha256"],
        "round": 1,
        "status": "SEARCH_TERMINATED_NO_PARENT",
        "finalist_gate": plan["finalist_gate"],
        "search_finalist": None,
        "round_receipt_sha256": pilot.digest(pilot.canonical(receipt)),
        "trials_sha256": pilot.digest(ledger),
        "brief": brief,
        "created_at_utc": "2026-09-01T00:00:00.000Z",
    }
    (root / pilot.SEARCH_TERMINAL).write_bytes(pilot.canonical(terminal))
    return str(plan["campaign_id"])


def test_t0_missing_root_and_unbound_later_phase_file_are_blocked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    database, candidate_id = _approved_candidate_database(tmp_path)
    missing = search_campaign.freeze_search_capability(
        database, None, None, None
    )
    assert missing.status == "BLOCKED_DATA"

    with get_connection(database, read_only=True) as connection:
        connection.execute("BEGIN")
        profile = search_campaign.load_approved_candidate_snapshot(
            connection, candidate_id
        ).profile
    contract = pilot.profile_search_contract(
        profile,
        "20260103-20260205",
        "20260205-20260307",
        20,
    )
    assert contract["search_timerange"] == "20260103-20260205"

    acquisition = tmp_path / "root" / "acquisition"
    acquisition.mkdir(parents=True)
    provenance = {
        "schema": "freqtrade-lab-retained-search-data-v2",
        "source": {},
        "freqtrade": {},
        "contract": contract,
        "files": {},
        "local_only_files": {},
    }
    (acquisition / "retained-data-provenance.json").write_bytes(
        pilot.canonical(provenance)
    )
    (acquisition / "holdout-receipt.json").write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(
        pilot,
        "_verify_search_data",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            pilot.PilotError("later-phase file is forbidden")
        ),
    )
    with pytest.raises(search_campaign.SearchCampaignError) as raised:
        search_campaign._acquisition_snapshot(acquisition.parent, database)
    assert raised.value.code == "BLOCKED_DATA"


@pytest.mark.parametrize("unsafe", ("mode", "git"))
def test_t0_search_root_is_exact_0700_and_outside_every_git_worktree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, unsafe: str
) -> None:
    parent = tmp_path / "sibling-repository"
    root = parent / "search-root"
    (root / pilot.ACQUISITION).mkdir(parents=True)
    root.chmod(0o500 if unsafe == "mode" else 0o700)
    if unsafe == "git":
        (parent / ".git").mkdir()
    monkeypatch.setattr(
        search_campaign,
        "_acquisition_snapshot",
        lambda _root, _database: pytest.fail(
            "unsafe root must be rejected before data reads"
        ),
    )

    capability = search_campaign.freeze_search_capability(
        tmp_path / "missing.sqlite", root, None, None
    )

    assert capability.status == "BLOCKED_DATA"


def test_t0_fresh_root_rejects_every_non_acquisition_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database, candidate_id = _approved_candidate_database(tmp_path)
    capability = _frozen_capability(
        tmp_path, monkeypatch, database, candidate_id
    )
    try:
        assert capability.search_root is not None
        (capability.search_root / "unbound-extra.bin").write_bytes(b"unbound")

        context = search_campaign.load_search_context(database, capability)

        assert context["capability"]["status"] == "BLOCKED_DATA"
        assert context["state"]["status"] == "BLOCKED_DATA"
    finally:
        capability.close()

def test_t0_round_one_binds_candidate_and_keeps_six_tables_byte_equal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database, candidate_id = _approved_candidate_database(tmp_path)
    capability = _frozen_capability(
        tmp_path, monkeypatch, database, candidate_id
    )
    try:
        before = search_campaign.business_table_digest(database)
        prepared = _prepare_round_one(
            database, capability, [candidate_id], campaign_id="search-t0"
        )
        after = search_campaign.business_table_digest(database)

        assert before == after
        assert prepared.argv[0] == str(capability.freqtrade_python)
        assert "--campaign-root" in prepared.argv
        assert str(database) not in prepared.argv
        assert capability.search_root is not None
        plan = pilot.load_plan(capability.search_root, pilot.SEARCH_CAMPAIGN)
        assert plan["round"] == 1
        assert plan["active_attempt_limit"] == 3
        assert plan["budget"] == {"maximum_attempts": 6}
        assert len(plan["candidates"]) <= 2
        assert plan["candidates"][0]["mechanism"] == "trend"
        assert plan["candidates"][0]["parent_strategy_sha256"] is None
        round_one_path = capability.search_root / search_campaign.ROUND_ONE_CAMPAIGN
        assert round_one_path.read_bytes() == (
            capability.search_root / pilot.SEARCH_CAMPAIGN
        ).read_bytes()
        round_two_view = {**plan, "round": 2}
        assert search_campaign._round_one_plan(
            capability, round_two_view
        ) == plan
        with get_connection(database, read_only=True) as connection:
            assert connection.execute(
                "SELECT COUNT(*) FROM generation_runs WHERE id=?",
                (prepared.campaign_id,),
            ).fetchone()[0] == 0

        with pytest.raises(search_campaign.SearchCampaignError) as raised:
            search_campaign.prepare_round_two(
                database,
                capability,
                prepared.campaign_id,
                [
                    {"candidate_id": candidate_id, "changed_factor": "stoploss"},
                    {"candidate_id": candidate_id, "changed_factor": "minimal_roi"},
                ],
            )
        assert raised.value.code == "invalid_search_request"
    finally:
        capability.close()


TSMOM_SOURCE = '''import talib.abstract as ta
from pandas import DataFrame
from technical import qtpylib
from freqtrade.strategy import IStrategy

class EthTsmom28(IStrategy):
    INTERFACE_VERSION = 3
    timeframe = "1d"
    can_short = True
    startup_candle_count = 90
    process_only_new_candles = True
    minimal_roi = {}
    stoploss = -0.20

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["close_28"] = dataframe["close"].shift(28)
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[dataframe["close"] > dataframe["close_28"], "enter_long"] = 1
        dataframe.loc[dataframe["close"] < dataframe["close_28"], "enter_short"] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[dataframe["close"] < dataframe["close_28"], "exit_long"] = 1
        dataframe.loc[dataframe["close"] > dataframe["close_28"], "exit_short"] = 1
        return dataframe
'''


TSMOM_SMA_FILTER_SOURCE = TSMOM_SOURCE.replace(
    '        return dataframe\n\n    def populate_entry_trend',
    '        dataframe["entry_sma_84"] = dataframe["close"].rolling(84).mean()\n'
    '        return dataframe\n\n    def populate_entry_trend',
).replace(
    'dataframe.loc[dataframe["close"] > dataframe["close_28"], "enter_long"]',
    'dataframe.loc[(dataframe["close"] > dataframe["close_28"]) & '
    '(dataframe["close"] > dataframe["entry_sma_84"]), "enter_long"]',
).replace(
    'dataframe.loc[dataframe["close"] < dataframe["close_28"], "enter_short"]',
    'dataframe.loc[(dataframe["close"] < dataframe["close_28"]) & '
    '(dataframe["close"] < dataframe["entry_sma_84"]), "enter_short"]',
).replace("class EthTsmom28", "class EthTsmom28Sma84")


def _tsmom_snapshots(tmp_path: Path) -> tuple[object, object]:
    database, candidate_id = _approved_candidate_database(tmp_path)
    with get_connection(database, read_only=True) as connection:
        connection.execute("BEGIN")
        parent = search_campaign.load_approved_candidate_snapshot(
            connection, candidate_id
        )
    parent = replace(
        parent,
        class_name="EthTsmom28",
        code_text=TSMOM_SOURCE,
    )
    child = replace(
        parent,
        candidate_id="tsmom-sma-filter-child",
        class_name="EthTsmom28Sma84",
        parent_candidate_id=parent.candidate_id,
        code_text=TSMOM_SMA_FILTER_SOURCE,
    )
    return parent, child


def test_t0_round_two_accepts_only_frozen_sma84_entry_filter(
    tmp_path: Path,
) -> None:
    parent, child = _tsmom_snapshots(tmp_path)

    assert analyze_bounded_causal_strategy(
        parent.code_text, parent.class_name, expected_timeframe="1d"
    ).max_lookback == 29
    assert analyze_bounded_causal_strategy(
        child.code_text, child.class_name, expected_timeframe="1d"
    ).max_lookback == 84
    assert search_campaign._single_factor_change(
        parent, child, search_campaign.ENTRY_SMA_FILTER_84_V1
    )


@pytest.mark.parametrize(
    "source",
    (
        TSMOM_SMA_FILTER_SOURCE.replace("rolling(84)", "rolling(83)"),
        TSMOM_SMA_FILTER_SOURCE.replace(
            '& (dataframe["close"] < dataframe["entry_sma_84"])', ""
        ),
        TSMOM_SMA_FILTER_SOURCE.replace(
            'dataframe["close"] < dataframe["entry_sma_84"]',
            'dataframe["close"] > dataframe["entry_sma_84"]',
            1,
        ),
        TSMOM_SMA_FILTER_SOURCE.replace("stoploss = -0.20", "stoploss = -0.12"),
        TSMOM_SMA_FILTER_SOURCE.replace(
            'dataframe["close"] < dataframe["close_28"], "exit_long"',
            'dataframe["close"] <= dataframe["close_28"], "exit_long"',
        ),
    ),
    ids=("wrong-window", "one-sided", "wrong-direction", "extra-field", "exit-change"),
)
def test_t0_sma84_entry_filter_rejects_any_extra_or_incomplete_change(
    tmp_path: Path, source: str
) -> None:
    parent, child = _tsmom_snapshots(tmp_path)
    child = replace(child, code_text=source)

    assert not search_campaign._single_factor_change(
        parent, child, search_campaign.ENTRY_SMA_FILTER_84_V1
    )


LOOKBACK_SOURCE = '''import talib.abstract as ta
from pandas import DataFrame
from technical import qtpylib
from freqtrade.strategy import IStrategy

class DailyTrend84(IStrategy):
    INTERFACE_VERSION = 3
    timeframe = "1d"
    can_short = False
    startup_candle_count = 84
    process_only_new_candles = True
    minimal_roi = {"0": 0.0}
    stoploss = -0.99

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["trend_84"] = dataframe["close"].rolling(84).mean()
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[dataframe["close"] > dataframe["trend_84"], "enter_long"] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[dataframe["close"] < dataframe["trend_84"], "exit_long"] = 1
        return dataframe
'''


def _lookback_snapshots(tmp_path: Path) -> tuple[object, object]:
    database, candidate_id = _approved_candidate_database(tmp_path)
    with get_connection(database, read_only=True) as connection:
        connection.execute("BEGIN")
        parent = search_campaign.load_approved_candidate_snapshot(
            connection, candidate_id
        )
    parent = replace(
        parent,
        class_name="DailyTrend84",
        code_text=LOOKBACK_SOURCE,
    )
    child = replace(
        parent,
        candidate_id="lookback-child",
        class_name="DailyTrend42",
        parent_candidate_id=parent.candidate_id,
        code_text=(
            LOOKBACK_SOURCE.replace("DailyTrend84", "DailyTrend42")
            .replace("startup_candle_count = 84", "startup_candle_count = 42")
            .replace("rolling(84)", "rolling(42)")
        ),
    )
    return parent, child


def test_t0_startup_candle_count_binds_matching_rolling_lookback(
    tmp_path: Path,
) -> None:
    parent, child = _lookback_snapshots(tmp_path)

    assert search_campaign._single_literal_factor_change(
        parent, child, "startup_candle_count"
    )


@pytest.mark.parametrize(
    "source",
    (
        LOOKBACK_SOURCE.replace("startup_candle_count = 84", "startup_candle_count = 42"),
        LOOKBACK_SOURCE.replace("rolling(84)", "rolling(42)"),
        (
            LOOKBACK_SOURCE.replace("startup_candle_count = 84", "startup_candle_count = 42")
            .replace("rolling(84)", "rolling(42)")
            .replace("stoploss = -0.99", "stoploss = -0.50")
        ),
        (
            LOOKBACK_SOURCE.replace("startup_candle_count = 84", "startup_candle_count = 42")
            .replace("rolling(84)", "rolling(42, 1)")
        ),
        (
            LOOKBACK_SOURCE.replace("startup_candle_count = 84", "startup_candle_count = 42")
            .replace("rolling(84)", "rolling(window=42)")
        ),
        (
            LOOKBACK_SOURCE.replace("startup_candle_count = 84", "startup_candle_count = 0")
            .replace("rolling(84)", "rolling(0)")
        ),
    ),
    ids=(
        "startup-only",
        "rolling-only",
        "extra-ast-change",
        "extra-rolling-argument",
        "rolling-keyword",
        "non-positive-lookback",
    ),
)
def test_t0_startup_candle_count_rejects_unbound_or_extra_changes(
    tmp_path: Path, source: str
) -> None:
    parent, child = _lookback_snapshots(tmp_path)
    child = replace(child, class_name="DailyTrend84", code_text=source)

    assert not search_campaign._single_literal_factor_change(
        parent, child, "startup_candle_count"
    )


def test_t0_profile_and_safe_mechanism_are_server_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database, candidate_id = _approved_candidate_database(tmp_path)
    capability = _frozen_capability(
        tmp_path, monkeypatch, database, candidate_id
    )
    try:
        object.__setattr__(capability, "pair", "BTC/USDT:USDT")
        with pytest.raises(search_campaign.SearchCampaignError) as raised:
            search_campaign.prepare_round_one(
                database,
                capability,
                [candidate_id],
                profile_id=_profile_id(capability),
            )
        assert raised.value.code == "BLOCKED_DATA"
    finally:
        capability.close()


def test_t0_full_round_one_plan_is_validated_before_root_materialization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database, candidate_id = _approved_candidate_database(tmp_path)
    capability = _frozen_capability(
        tmp_path, monkeypatch, database, candidate_id
    )
    try:
        monkeypatch.setattr(
            pilot,
            "_load_search_campaign",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                pilot.PilotError("invalid full Profile Search plan")
            ),
        )
        before = search_campaign.business_table_digest(database)

        with pytest.raises(search_campaign.SearchCampaignError) as raised:
            _prepare_round_one(
                database, capability, [candidate_id], campaign_id="reserved-plan"
            )

        assert raised.value.code == "invalid_search_request"
        assert raised.value.status == 400
        assert not (capability.search_root / search_campaign.STRATEGIES).exists()
        assert not (capability.search_root / pilot.SEARCH_CAMPAIGN).exists()
        assert not (
            capability.search_root / search_campaign.ROUND_ONE_CAMPAIGN
        ).exists()
        assert search_campaign.business_table_digest(database) == before
    finally:
        capability.close()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("domain", "OTHER"),
        ("exchange", "binance"),
        ("trading_mode", "spot"),
        ("margin_mode", "cross"),
    ],
)
def test_t0_profile_market_boundary_is_server_bound(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: str,
) -> None:
    database, candidate_id = _approved_candidate_database(tmp_path)
    capability = _frozen_capability(
        tmp_path, monkeypatch, database, candidate_id
    )
    try:
        with get_connection(database, read_only=True) as connection:
            connection.execute("BEGIN")
            snapshot = search_campaign.load_approved_candidate_snapshot(
                connection, candidate_id
            )
        changed_profile = {**snapshot.profile, field: value}
        monkeypatch.setattr(
            search_campaign,
            "load_approved_candidate_snapshot",
            lambda _connection, _candidate_id: replace(
                snapshot, profile=changed_profile
            ),
        )
        with get_connection(database, read_only=True) as connection:
            connection.execute("BEGIN")
            with pytest.raises(search_campaign.SearchCampaignError) as raised:
                search_campaign._bound_candidate(
                    connection, candidate_id, capability
                )
        assert raised.value.code == "candidate_profile_mismatch"
    finally:
        capability.close()


def test_t0_unprojected_engine_terminal_cannot_be_completed_by_late_cancel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database, candidate_id = _approved_candidate_database(tmp_path)
    capability = _frozen_capability(
        tmp_path, monkeypatch, database, candidate_id
    )
    try:
        _prepare_round_one(
            database, capability, [candidate_id], campaign_id="search-terminal-wins"
        )
        campaign_id = _round_one_no_parent_receipts(capability)
        late = search_campaign.fail_search_campaign(
            database, capability, campaign_id, "LATE_CANCEL"
        )

        state = search_campaign.load_public_search_state(capability)

        assert late["status"] == "INTERRUPTED"
        assert state["status"] == "INTERRUPTED"
        assert state["search_finalist"] is None
        with get_connection(database, read_only=True) as connection:
            assert connection.execute(
                "SELECT COUNT(*) FROM generation_runs WHERE id=?", (campaign_id,)
            ).fetchone()[0] == 0
    finally:
        capability.close()


def test_t0_trial_identity_must_match_its_frozen_plan_candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database, candidate_id = _approved_candidate_database(tmp_path)
    capability = _frozen_capability(
        tmp_path, monkeypatch, database, candidate_id
    )
    try:
        _prepare_round_one(
            database, capability, [candidate_id], campaign_id="search-trial-binding"
        )
        _round_one_no_parent_receipts(capability)
        assert capability.search_root is not None
        root = capability.search_root
        records = [
            json.loads(line) for line in (root / pilot.SEARCH_TRIALS).read_bytes().splitlines()
        ]
        records[1]["candidate_id"] = "injected-candidate"
        records[2]["ledger_prefix_sha256"] = pilot.digest(
            pilot.canonical(records[0]) + pilot.canonical(records[1])
        )
        ledger = _append_records(root, records)
        terminal = json.loads((root / pilot.SEARCH_TERMINAL).read_bytes())
        terminal["round_receipt_sha256"] = pilot.digest(pilot.canonical(records[2]))
        terminal["trials_sha256"] = pilot.digest(ledger)
        (root / pilot.SEARCH_TERMINAL).write_bytes(pilot.canonical(terminal))

        with pytest.raises(search_campaign.SearchCampaignError, match="ledger order/binding"):
            search_campaign.load_public_search_state(capability)
    finally:
        capability.close()


def test_t0_active_partial_ledger_is_running_but_restart_is_interrupted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database, candidate_id = _approved_candidate_database(tmp_path)
    capability = _frozen_capability(
        tmp_path, monkeypatch, database, candidate_id
    )
    try:
        prepared = _prepare_round_one(
            database, capability, [candidate_id], campaign_id="search-partial"
        )
        assert capability.search_root is not None
        plan = pilot.load_plan(capability.search_root, pilot.SEARCH_CAMPAIGN)
        _append_records(
            capability.search_root,
            [
                {
                    "schema": pilot.SEARCH_TRIAL_SCHEMA,
                    "record_type": "ROUND_STARTED",
                    "campaign_id": plan["campaign_id"],
                    "campaign_sha256": plan["_sha256"],
                    "round": 1,
                    "attempt_numbers": [1],
                }
            ],
        )
        before_recovery = search_campaign.business_table_digest(database)

        def expensive_poll_forbidden(*_args: object) -> object:
            raise AssertionError("GET/poll repeated an expensive frozen-input check")

        monkeypatch.setattr(search_campaign, "_acquisition_snapshot", expensive_poll_forbidden)
        monkeypatch.setattr(search_campaign, "_freqtrade_snapshot", expensive_poll_forbidden)

        assert search_campaign.load_public_search_state(
            capability, active=True
        )["status"] == "RUNNING"
        recovered = search_campaign.recover_interrupted_search(
            capability, database
        )
        assert recovered["status"] == "FAILED"
        assert search_campaign.load_public_search_state(capability)["status"] == "FAILED"
        assert (
            search_campaign.business_table_digest(database, prepared.campaign_id)
            == before_recovery
        )
    finally:
        capability.close()


def test_t0_corrupt_search_context_is_locally_blocked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database, candidate_id = _approved_candidate_database(tmp_path)
    capability = _frozen_capability(
        tmp_path, monkeypatch, database, candidate_id
    )
    try:
        _prepare_round_one(
            database, capability, [candidate_id], campaign_id="search-corrupt"
        )
        assert capability.search_root is not None
        (capability.search_root / pilot.SEARCH_TRIALS).write_bytes(b'{"partial":')

        context = search_campaign.load_search_context(database, capability)

        assert context["capability"]["status"] == "BLOCKED_DATA"
        assert context["state"]["status"] == "BLOCKED_DATA"
        assert context["candidates"] == []
        assert context["codex_parent_lock"] is None
        assert str(tmp_path) not in json.dumps(context, sort_keys=True)
    finally:
        capability.close()


def test_t0_engine_blocked_terminal_requires_failed_database_projection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database, candidate_id = _approved_candidate_database(tmp_path)
    capability = _frozen_capability(
        tmp_path, monkeypatch, database, candidate_id
    )
    try:
        prepared = _prepare_round_one(
            database, capability, [candidate_id], campaign_id="search-blocked"
        )
        assert capability.search_root is not None
        plan = pilot.load_plan(capability.search_root, pilot.SEARCH_CAMPAIGN)
        blocked = {
            "schema": pilot.SEARCH_TERMINAL_SCHEMA,
            "campaign_id": prepared.campaign_id,
            "campaign_sha256": plan["_sha256"],
            "contract_sha256": plan["_contract_sha256"],
            "round": 1,
            "status": "SEARCH_BLOCKED",
            "error": "bounded Search execution failure",
            "trials_sha256": pilot.digest(b""),
            "created_at_utc": "2026-09-01T00:00:00.000Z",
        }
        (capability.search_root / pilot.SEARCH_TERMINAL).write_bytes(
            pilot.canonical(blocked)
        )

        pending = search_campaign.load_public_search_state(capability)
        state = search_campaign.recover_interrupted_search(capability, database)

        assert pending["status"] == "INTERRUPTED"
        assert pending["search_finalist"] is None
        assert state["status"] == "FAILED"
        assert state["campaign_id"] == prepared.campaign_id
        assert state["attempts"] == []
        assert state["search_finalist"] is None
        assert "error" not in state
    finally:
        capability.close()
