"""Fixed source contracts and synthetic HTTP integration; no market data or fills."""

import ast
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from lab import bounded_research as pilot, codex_generation, search_campaign
from lab.bounded_strategy import BoundedStrategyError, analyze_bounded_causal_strategy
from lab.database import get_connection
from tests.test_search_console_http import (
    NOW, _env, _post, _ready_round_one, _serve, _snapshot, _wait_file, _wait_search,
)


FIXTURES = Path(__file__).parent / "fixtures" / "prior_close_channel_v1"
HASHES = (
    "a30eed769bf5a73dfbd18675c93a91695dabb4f0cb57b62875d5aec3c30f1bd7",
    "34b1e006c3d65194ddb6e190306e7379db5957592bf714a1f9cc02e50fa8c289",
)
FACTOR = search_campaign.ENTRY_PRIOR_CLOSE_CHANNEL_FILTER_V1
FILTER = ('(dataframe["close"].rolling(28).max().shift(1) / '
          'dataframe["close"].rolling(28).min().shift(1)) <= 1.10')


@pytest.fixture
def sources():
    result = []
    for number, expected in enumerate(HASHES, 1):
        name = f"ConsolidationChannelR{number}"
        raw = (FIXTURES / f"{name}.py").read_bytes()
        assert hashlib.sha256(raw).hexdigest() == expected
        result.append(SimpleNamespace(class_name=name, code_text=raw.decode("utf-8")))
    return result


def test_t0_formal_dispatch_and_generation_accept_exact_reviewed_sources(sources):
    assert FACTOR == "entry_prior_close_channel_28_10pct_v1"
    assert search_campaign._single_factor_change(*sources, FACTOR)
    for source, expected_sha in zip(sources, HASHES):
        analysis = analyze_bounded_causal_strategy(
            source.code_text, source.class_name, expected_timeframe="1d"
        )
        assert analysis.max_lookback == analysis.startup_candle_count == 29
        raw = json.dumps({**vars(source), "display_name": source.class_name}).encode()
        parsed = codex_generation.parse_candidate_output(raw, timeframe="1d")
        assert parsed.code_text == source.code_text
        assert parsed.code_sha256 == expected_sha
        with pytest.raises(BoundedStrategyError) as error:
            analyze_bounded_causal_strategy(
                source.code_text.replace("startup_candle_count = 29", "startup_candle_count = 28"),
                source.class_name, expected_timeframe="1d",
            )
        assert error.value.code == "INSUFFICIENT_STARTUP_CANDLES"


@pytest.mark.parametrize("old,new", [
    ('< dataframe["exit_lower"]', '< dataframe["lower"]'),
    ("stoploss = -0.08", "stoploss = -0.09"),
    ("<= 1.10", "<= 1.11"),
    (FILTER, FILTER.replace("rolling(28)", "rolling(27)")),
    (FILTER, FILTER.replace("shift(1)", "shift(-1)")),
    (FILTER, FILTER.replace(".shift(1)", "")),
    (" & (" + FILTER + ")", ""),
    ("    stoploss = -0.08", "    stoploss = -0.08\n    position_adjustment_enable = False"),
    ('dataframe["upper"] = dataframe["close"].rolling(28)',
     'dataframe["upper"] = dataframe["close"].rolling(27)'),
    ("    def populate_indicators", "    def extra_method(self):\n        return 1\n\n    def populate_indicators"),
], ids=["exit", "stop", "width", "window", "future-shift", "missing-shift",
        "one-side", "class-setting", "shared-indicator", "extra-method"])
def test_t0_formal_dispatch_rejects_extra_or_incomplete_changes(sources, old, new):
    parent, child = sources
    mutated = child.code_text.replace(old, new, 1)
    assert mutated != child.code_text
    assert not search_campaign._single_factor_change(
        parent, SimpleNamespace(class_name=child.class_name, code_text=mutated), FACTOR
    )


def test_t0_formal_dispatch_rejects_no_change_reversal_and_wrong_factor(sources):
    parent, child = sources
    for first, second, factor in (
        (parent, parent, FACTOR), (child, child, FACTOR), (child, parent, FACTOR),
        (parent, child, "stoploss"), (parent, child, "entry_prior_close_channel_28_11pct_v1"),
        (parent, child, search_campaign.ENTRY_SMA_FILTER_84_V1),
    ):
        assert not search_campaign._single_factor_change(first, second, factor)


def test_t1_signal_methods_exclude_current_bar_and_preserve_future_prefix(sources):
    pd = pytest.importorskip("pandas")
    # Execute only the validated three populate methods. This is pandas signal
    # evidence, deliberately not an imitation of native order/fill execution.
    strategies = []
    for source in sources:
        tree = ast.parse(source.code_text)
        tree.body = [node for node in tree.body if isinstance(node, ast.ClassDef)]
        namespace = {"IStrategy": object, "DataFrame": pd.DataFrame}
        exec(compile(tree, "<synthetic-channel-signals>", "exec"), namespace)
        strategies.append(namespace[source.class_name]())

    def evaluate(strategy, frame):
        result = strategy.populate_indicators(frame.copy(), {})
        result = strategy.populate_entry_trend(result, {})
        return strategy.populate_exit_trend(result, {})

    for high, current, direction, expected in (
        (109., 115., "long", [True, True]),
        (130., 140., "long", [True, False]),
        (109., 95., "short", [True, True]),
        (130., 90., "short", [True, False]),
        (110., 115., "long", [True, True]),
        (109., 109., "long", [False, False]),
    ):
        values = [100.] * 5 + [100., high] * 14 + [current]
        frame = pd.DataFrame({"close": values, "volume": 100.})
        results = [evaluate(strategy, frame) for strategy in strategies]
        assert [bool(r[f"enter_{direction}"].iloc[-1] == 1) for r in results] == expected
        assert results[1]["upper"].iloc[-1] == high
        assert results[1]["lower"].iloc[-1] == 100.
        future = pd.concat([frame, pd.DataFrame({"close": [300., 10.] * 20, "volume": 100.})], ignore_index=True)
        for strategy, result in zip(strategies, results):
            assert not result[["enter_long", "enter_short"]].iloc[:28].eq(1).any().any()
            pd.testing.assert_frame_equal(evaluate(strategy, future).iloc[:len(frame)], result)
            for column, value in (("close", float("nan")), ("volume", 0.)):
                missing = frame.copy()
                missing.loc[len(frame) - 2, column] = value
                assert not evaluate(strategy, missing)[["enter_long", "enter_short"]].iloc[-1].eq(1).any()


def _approve_source(environment, source, parent=None):
    request = codex_generation.validate_generation_request({
        "profile_id": environment.profile_id, "parent_candidate_id": parent,
        "idea": "Synthetic fixture: reproduce the reviewed channel source.",
        "strategy_family": "prior_close_channel",
    })
    prepared = codex_generation.start_generation(
        environment.database, str(uuid4()), request, model="test-only", started_at=NOW
    )
    raw = json.dumps({**vars(source), "display_name": source.class_name}).encode()
    candidate_id = codex_generation.complete_generation(
        environment.database, prepared,
        codex_generation.parse_candidate_output(raw, timeframe="1d"),
        raw_output=raw, jsonl_summary={"event_count": 4, "tool_event_count": 0}, finished_at=NOW,
    )
    codex_generation.review_generation(
        environment.database, prepared.generation_id, "APPROVED", decided_at=NOW
    )
    return candidate_id


@pytest.mark.parametrize("case", ["accepted", "wrong-factor", "exit-change", "stale-source", "contract-drift"])
def test_t2_http_round_two_channel_binding_and_failure_before_writes(tmp_path, monkeypatch, sources, case):
    environment = _env(tmp_path, monkeypatch, "sleep", timeframe="1d")
    # Reuse the existing synthetic acquisition edge with sufficient startup.
    acquisition = search_campaign._acquisition_snapshot
    monkeypatch.setattr(search_campaign, "_acquisition_snapshot",
                        lambda *args: {**acquisition(*args), "pre_roll_candles": 29})
    parent, child = sources
    parent_id = _approve_source(environment, parent)
    if case == "exit-change":
        child = SimpleNamespace(class_name=child.class_name, code_text=child.code_text.replace(
            '< dataframe["exit_lower"]', '< dataframe["lower"]'))
    child_id = _approve_source(environment, child, parent_id)
    environment.seeds = (parent_id,)
    campaign_id = _ready_round_one(environment, monkeypatch)
    receipt = search_campaign._round_one_receipt(environment.root, campaign_id)
    if case == "stale-source":
        with get_connection(environment.database) as connection:
            connection.execute("UPDATE candidates SET code_text=code_text || ? WHERE id=?",
                               ("\n# changed after approval\n", child_id))
            connection.commit()
    before_database = _snapshot(environment.database)

    def files():
        return {p.relative_to(environment.root).as_posix(): p.read_bytes()
                for p in environment.root.rglob("*") if p.is_file()}

    with _serve(environment) as server:
        if case == "contract-drift":
            monkeypatch.setattr(search_campaign, "_acquisition_snapshot",
                                lambda *args: {**acquisition(*args), "pre_roll_candles": 30})
        before_files = files()
        status, response, _ = _post(server, f"/api/search-campaigns/{campaign_id}/actions", {
            "action": "START_ROUND_2", "candidates": [{
                "candidate_id": child_id,
                "changed_factor": "stoploss" if case == "wrong-factor" else FACTOR,
            }],
        })
        assert _snapshot(environment.database) == before_database
        if case != "accepted":
            expected = {
                "wrong-factor": (409, "invalid_child_set"),
                "exit-change": (409, "invalid_child_set"),
                "stale-source": (409, "approved_candidate_binding_invalid"),
                "contract-drift": (503, "BLOCKED_DATA"),
            }
            assert (status, response["error"]) == expected[case]
            assert files() == before_files
            assert not (environment.control / "started-2").exists()
            return
        assert status == 202 and response["status"] == "RUNNING"
        _wait_file(environment.control / "started-2")
        plan = pilot.load_plan(environment.root, pilot.SEARCH_CAMPAIGN)
        candidate = plan["candidates"][0]
        assert plan["round"] == 2
        assert candidate["changed_factor"] == FACTOR
        assert candidate["strategy_sha256"] == HASHES[1]
        assert candidate["parent_strategy_sha256"] == plan["parent"]["strategy_sha256"] == HASHES[0]
        assert plan["pre_roll_candles"] == 29
        assert plan["profile_snapshot_sha256"] == pilot.digest(pilot.canonical(plan["profile_snapshot"]))
        assert (environment.root / candidate["strategy_file"]).read_text() == child.code_text
        assert plan["previous_round_receipt_sha256"] == pilot.digest(pilot.canonical(receipt))
        assert _post(server, f"/api/search-campaigns/{campaign_id}/actions", {"action": "CANCEL"})[0] == 202
        final, _ = _wait_search(server, campaign_id, "FAILED")
        assert final["search_finalist"] is None
