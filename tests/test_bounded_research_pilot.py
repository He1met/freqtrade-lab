import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "run_bounded_research_pilot.py"
SPEC = importlib.util.spec_from_file_location("bounded_pilot", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
pilot = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pilot)


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(pilot.canonical(value))


def _candidate_source(class_name: str, body: str = "return dataframe") -> bytes:
    return (
        "import talib.abstract as ta\n"
        "from pandas import DataFrame\n"
        "from technical import qtpylib\n\n"
        "from freqtrade.strategy import IStrategy\n\n\n"
        f"class {class_name}(IStrategy):\n"
        "    INTERFACE_VERSION = 3\n"
        '    timeframe = "5m"\n'
        "    can_short = True\n"
        "    startup_candle_count = 20\n"
        "    process_only_new_candles = True\n"
        '    minimal_roi = {"0": 0.0}\n'
        "    stoploss = -0.02\n\n"
        "    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:\n"
        f"        {body}\n\n"
        "    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:\n"
        "        return dataframe\n\n"
        "    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:\n"
        "        return dataframe\n"
    ).encode()


def _plan_root(tmp_path: Path) -> Path:
    root = tmp_path / "pilot"
    candidates = root / "candidates"
    candidates.mkdir(parents=True)
    window = {
        "schema": "freqtrade-lab-okx-window-v1",
        "data_start_utc": "2026-05-31T22:00:00Z",
        "development_start_utc": "2026-06-01T00:00:00Z",
        "holdout_start_utc": "2026-07-31T00:00:00Z",
        "end_exclusive_utc": "2026-08-30T00:00:00Z",
    }
    _write_json(root / pilot.WINDOW, window)
    source = _candidate_source("CandidateOne")
    strategy = candidates / "CandidateOne.py"
    strategy.write_bytes(source)
    research_spec = {
        "schema": "freqtrade-lab-research-spec-v1",
        "profile": {
            "history_start_date": "2026-06-01",
            "holdout_days": 30,
            "stress_fee_multiplier": 2.0,
        },
        "candidate": {
            "class_name": "CandidateOne",
            "metadata": {
                "pilot_id": "test-pilot",
                "economic_evidence": "NOT_EVALUATED",
                "generation": {
                    "source": "CODEX",
                    "model": None,
                    "returned_strategy_count": 1,
                    "source_item_index": 0,
                },
            },
        },
    }
    spec_path = candidates / "CandidateOne-spec.json"
    _write_json(spec_path, research_spec)
    plan = {
        "schema": pilot.SCHEMA,
        "pilot_id": "test-pilot",
        "freqtrade_version": "2026.7",
        "window_spec_sha256": pilot.digest((root / pilot.WINDOW).read_bytes()),
        "development_timerange": "20260601-20260731",
        "holdout_timerange": "20260731-20260830",
        "stress_fee_multiplier": 2.0,
        "selection": {
            "minimum_trades": 20,
            "max_selected": 1,
            "no_eligible": "STOP",
            "missing_metric_policy": "STOP",
            "visibility": "DEVELOPMENT_ONLY_BLIND",
            "candidate_execution_failure": "STOP",
            "ranking": list(pilot.RANKING),
            "economic_gate": "NONE_TECHNICAL_PILOT",
        },
        "holdout_policy": {
            "max_open_count": 1,
            "retry_after_open": False,
            "tune_after_result": False,
        },
        "candidates": [
            {
                "candidate_id": "candidate-one",
                "class_name": "CandidateOne",
                "strategy_file": "candidates/CandidateOne.py",
                "research_spec_file": "candidates/CandidateOne-spec.json",
                "strategy_sha256": pilot.digest(source),
                "research_spec_sha256": pilot.digest(spec_path.read_bytes()),
            }
        ],
    }
    _write_json(root / pilot.PLAN, plan)
    return root


def test_t0_plan_freezes_candidate_hash_and_codex_lineage(tmp_path: Path) -> None:
    root = _plan_root(tmp_path)

    plan = pilot.load_plan(root)

    assert plan["pilot_id"] == "test-pilot"
    assert plan["selection"]["visibility"] == "DEVELOPMENT_ONLY_BLIND"
    assert plan["selection"]["max_selected"] == 1
    assert plan["candidates"][0]["_strategy"].name == "CandidateOne.py"
    (root / "candidates" / "CandidateOne.py").write_text("changed\n")
    with pytest.raises(pilot.PilotError, match="hash mismatch"):
        pilot.load_plan(root)


@pytest.mark.parametrize(
    "body, message",
    [
        ("dataframe['x'] = dataframe['close'].shift(-1); return dataframe", "shift"),
        ("dataframe['x'] = dataframe['close'].rolling(3, None, True).max(); return dataframe", "rolling"),
        ("dataframe['x'] = dataframe.iloc[-1]; return dataframe", "positional"),
        ("dataframe['x'] = dataframe['close'].max(); return dataframe", "full-sample"),
        ("open('holdout.feather'); return dataframe", "forbidden call"),
    ],
)
def test_t0_causal_gate_rejects_future_ambiguous_source(
    tmp_path: Path, body: str, message: str
) -> None:
    path = tmp_path / "BadCandidate.py"
    path.write_bytes(_candidate_source("BadCandidate", body))

    with pytest.raises(pilot.PilotError, match=message):
        pilot.causal_source(path, "BadCandidate")


def test_t0_selection_is_development_only_and_one_shot(tmp_path: Path) -> None:
    plan = {
        "pilot_id": "test-pilot",
        "_sha256": "a" * 64,
        "development_timerange": "20260601-20260731",
        "selection": {"minimum_trades": 20},
    }
    results = [
        {
            "candidate_id": "higher-drawdown",
            "total_trades": 30,
            "profit_pct": 1.0,
            "max_drawdown_pct": 4.0,
            "profit_factor": 2.0,
        },
        {
            "candidate_id": "winner",
            "total_trades": 25,
            "profit_pct": 1.0,
            "max_drawdown_pct": 3.0,
            "profit_factor": 1.2,
        },
        {
            "candidate_id": "too-few-trades",
            "total_trades": 19,
            "profit_pct": 99.0,
            "max_drawdown_pct": 0.1,
            "profit_factor": 99.0,
        },
    ]

    assert pilot.select(tmp_path, plan, results) == "winner"
    receipt = json.loads((tmp_path / pilot.SELECTION).read_bytes())
    assert receipt["holdout_read"] is False
    assert receipt["selected_candidate_id"] == "winner"
    assert not (tmp_path / pilot.HOLDOUT_SEAL).exists()
    with pytest.raises(pilot.PilotError, match="replay"):
        pilot.select(tmp_path, plan, results)


def test_t0_selected_development_replay_must_match_exact_semantics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    view = {"exclusive_stop_utc": "2026-07-31T00:00:00Z", "files": {}}
    screened = [
        {
            "candidate_id": "winner",
            "archive_sha256": "a" * 64,
            "report_semantic_sha256": "b" * 64,
            "scenario_data_view": view,
            "total_trades": 25,
            "profit_pct": 1.25,
            "max_drawdown_pct": 3.5,
            "profit_factor": 1.2,
        }
    ]
    evidence = {
        "candidate_class_name": "CandidateOne",
        "scenarios": [
            {
                "scenario": "DEVELOPMENT",
                "total_trades": 25,
                "profit_pct": 1.25,
                "max_drawdown_pct": 3.5,
                "profit_factor": 1.2,
            }
        ]
    }
    produced = SimpleNamespace(
        bundle_root=tmp_path,
        artifacts=[
            SimpleNamespace(scenario="DEVELOPMENT", archive="development.zip")
        ],
    )
    monkeypatch.setattr(
        pilot,
        "report_metrics",
        lambda *args: {
            "total_trades": 25,
            "profit_pct": 1.25,
            "max_drawdown_pct": 3.5,
            "profit_factor": 1.2,
            "report_semantic_sha256": "b" * 64,
        },
    )
    monkeypatch.setattr(
        pilot,
        "load_json",
        lambda *args: ({"generation": {"scenario_data_view": view}}, b"{}"),
    )

    assert (
        pilot.development_replay_evidence(
            screened, "winner", evidence, produced
        )["status"]
        == "EXACT_REPORT_SEMANTICS_AND_DATA_VIEW_MATCH"
    )
    evidence["scenarios"][0]["profit_pct"] = 1.2501
    with pytest.raises(pilot.PilotError, match="database disagree"):
        pilot.development_replay_evidence(screened, "winner", evidence, produced)


def test_t0_daily_ui_command_binds_exact_isolated_roots(tmp_path: Path) -> None:
    terminal = {
        "database": tmp_path / "workspace with spaces" / "lab.sqlite",
        "bundle_root": tmp_path / "bundle with spaces",
        "frequi_base_url": "http://127.0.0.1:18766",
        "frequi_results_root": tmp_path / "FreqUI results" / "backtest_results",
    }

    command = pilot.shlex.split(pilot.strategy_library_command(terminal))

    assert command[command.index("--artifact-root") + 1] == str(terminal["bundle_root"])
    assert command[command.index("--frequi-base-url") + 1] == terminal["frequi_base_url"]
    assert command[command.index("--frequi-results-root") + 1] == str(
        terminal["frequi_results_root"]
    )


def test_t0_invalid_open_receipt_is_unknown_not_counted(tmp_path: Path) -> None:
    invalid = tmp_path / pilot.HOLDOUT_SEAL
    invalid.mkdir(parents=True)

    state = pilot.failure_open_state(tmp_path, None)

    assert state["holdout_opened"] is None
    assert state["holdout_open_count"] is None
    assert state["stress_open_count"] == 0
    assert state["open_receipt_integrity"] == "UNKNOWN_INVALID_OR_PARTIAL_RECEIPT"


def test_t0_materialized_candidate_hashes_are_rechecked(tmp_path: Path) -> None:
    root = _plan_root(tmp_path)
    plan = pilot.load_plan(root)
    candidate = plan["candidates"][0]
    controls = tmp_path / "controls"
    (controls / "strategies").mkdir(parents=True)
    (controls / "strategies" / "CandidateOne.py").write_bytes(
        candidate["_strategy"].read_bytes()
    )
    (controls / "research-spec.json").write_bytes(candidate["_spec"].read_bytes())

    pilot.verify_candidate_copy(candidate, controls, "test")
    (controls / "research-spec.json").write_text("changed\n", encoding="utf-8")

    with pytest.raises(pilot.PilotError, match="research spec changed"):
        pilot.verify_candidate_copy(candidate, controls, "test")
