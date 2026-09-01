"""T0 contracts for the thin Console-to-screen_search adapter."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from lab import search_campaign
from lab.database import get_connection
from scripts import run_bounded_research_pilot as pilot
from tests.test_development_run import _approved_candidate_database


def _frozen_capability(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> search_campaign.FrozenSearchCapability:
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
        "search_timerange": "20260601-20260701",
        "data_provenance_sha256": "a" * 64,
        "pair": "ADA/USDT:USDT",
        "timeframe": "5m",
        "base_fee": 0.0005,
        "acquisition_receipts": (),
    }
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
        search_campaign, "_acquisition_snapshot", lambda _root: acquisition
    )
    monkeypatch.setattr(
        search_campaign,
        "_freqtrade_snapshot",
        lambda _python, _source: freqtrade,
    )
    capability = search_campaign.freeze_search_capability(root, python, source)
    assert capability.status == "READY"
    return capability


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
    brief = {
        "campaign": {
            "campaign_id": plan["campaign_id"],
            "round": 1,
            "budget": {
                "maximum_attempts": 6,
                "consumed_before_round": 0,
                "consumed_this_round": 1,
                "consumed_total": 1,
                "remaining": 5,
            },
        },
        "candidates": [
            {
                key: trial[key]
                for key in (
                    "candidate_id",
                    "class_name",
                    "mechanism",
                    "strategy_sha256",
                    "relationship",
                    "changed_factor",
                    "technical_status",
                    "failure_reason",
                    "search_metrics",
                )
            }
        ],
        "frozen_ranking": [],
        "selected_parent": None,
    }
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
        "finalist_gate": pilot.SEARCH_GATE_CONTRACT,
        "search_finalist": None,
        "round_receipt_sha256": pilot.digest(pilot.canonical(receipt)),
        "trials_sha256": pilot.digest(ledger),
        "brief": brief,
        "created_at_utc": "2026-09-01T00:00:00.000Z",
    }
    (root / pilot.SEARCH_TERMINAL).write_bytes(pilot.canonical(terminal))
    return str(plan["campaign_id"])


def test_t0_missing_root_and_unbound_later_phase_file_are_blocked(
    tmp_path: Path,
) -> None:
    missing = search_campaign.freeze_search_capability(None, None, None)
    assert missing.status == "BLOCKED_DATA"

    acquisition = tmp_path / "root" / "acquisition"
    acquisition.mkdir(parents=True)
    provenance = {
        "schema": "freqtrade-lab-retained-search-data-v2",
        "source": {},
        "freqtrade": {},
        "contract": {"search_timerange": "20260601-20260701"},
        "files": {},
        "local_only_files": {},
    }
    (acquisition / "retained-data-provenance.json").write_bytes(
        pilot.canonical(provenance)
    )
    (acquisition / "holdout-receipt.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(search_campaign.SearchCampaignError) as raised:
        search_campaign._acquisition_snapshot(acquisition.parent)
    assert raised.value.code == "BLOCKED_DATA"

    provenance["contract"]["search_timerange"] = "20260601-20260630"
    (acquisition / "retained-data-provenance.json").write_bytes(
        pilot.canonical(provenance)
    )
    with pytest.raises(search_campaign.SearchCampaignError) as raised:
        search_campaign._acquisition_snapshot(acquisition.parent)
    assert "exactly 30 days" in raised.value.message


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
        lambda _root: pytest.fail("unsafe root must be rejected before data reads"),
    )

    capability = search_campaign.freeze_search_capability(root, None, None)

    assert capability.status == "BLOCKED_DATA"


def test_t0_fresh_root_rejects_every_non_acquisition_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database, _ = _approved_candidate_database(tmp_path)
    capability = _frozen_capability(tmp_path, monkeypatch)
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
    capability = _frozen_capability(tmp_path, monkeypatch)
    try:
        before = search_campaign.business_table_digest(database)
        prepared = search_campaign.prepare_round_one(
            database, capability, [candidate_id], campaign_id="search-t0"
        )
        after = search_campaign.business_table_digest(database)

        assert prepared.database_digest_before == prepared.database_digest_after
        assert prepared.database_total_changes == 0
        assert before == after == prepared.database_digest_before
        assert prepared.argv[0] == str(capability.freqtrade_python)
        assert "--campaign-root" in prepared.argv
        assert str(database) not in prepared.argv
        assert capability.search_root is not None
        plan = pilot.load_plan(capability.search_root, pilot.SEARCH_CAMPAIGN)
        assert plan["round"] == 1
        assert plan["candidates"][0]["mechanism"] == "trend"
        assert plan["candidates"][0]["parent_strategy_sha256"] is None
        assert (capability.search_root / "campaign-round-1.json").is_file()
    finally:
        capability.close()


def test_t0_profile_and_safe_mechanism_are_server_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database, candidate_id = _approved_candidate_database(tmp_path)
    capability = _frozen_capability(tmp_path, monkeypatch)
    try:
        object.__setattr__(capability, "pair", "BTC/USDT:USDT")
        with pytest.raises(search_campaign.SearchCampaignError) as raised:
            search_campaign.prepare_round_one(database, capability, [candidate_id])
        assert raised.value.code == "BLOCKED_DATA"
    finally:
        capability.close()


def test_t0_full_round_one_plan_is_validated_before_root_materialization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database, candidate_id = _approved_candidate_database(tmp_path)
    capability = _frozen_capability(tmp_path, monkeypatch)
    try:
        with get_connection(database, read_only=True) as connection:
            connection.execute("BEGIN")
            snapshot = search_campaign.load_approved_candidate_snapshot(
                connection, candidate_id
            )
        reserved = replace(snapshot, strategy_family="holdout")
        monkeypatch.setattr(
            search_campaign,
            "_bound_candidate",
            lambda _connection, _candidate_id, _capability: reserved,
        )
        before = search_campaign.business_table_digest(database)

        with pytest.raises(search_campaign.SearchCampaignError) as raised:
            search_campaign.prepare_round_one(
                database, capability, [candidate_id], campaign_id="reserved-plan"
            )

        assert raised.value.code == "invalid_search_request"
        assert raised.value.status == 400
        assert not (capability.search_root / search_campaign.STRATEGIES).exists()
        assert not (capability.search_root / pilot.SEARCH_CAMPAIGN).exists()
        assert not (
            capability.search_root / search_campaign.ROUND_PLAN.format(round_number=1)
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
    capability = _frozen_capability(tmp_path, monkeypatch)
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


def test_t0_exit_three_is_legal_no_parent_terminal_and_does_not_write_db(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database, candidate_id = _approved_candidate_database(tmp_path)
    capability = _frozen_capability(tmp_path, monkeypatch)
    try:
        before = search_campaign.business_table_digest(database)
        prepared = search_campaign.prepare_round_one(
            database, capability, [candidate_id], campaign_id="search-exit-three"
        )
        campaign_id = _round_one_no_parent_receipts(capability)

        completed = search_campaign.complete_search_round(
            capability, campaign_id, 3
        )

        assert completed["status"] == "SEARCH_TERMINATED_NO_PARENT"
        assert completed["budget"]["consumed_total"] == 1
        assert completed["attempts"][0]["technical_status"] == "INVALID"
        assert search_campaign.business_table_digest(database) == before
        assert prepared.database_total_changes == 0
        raw = json.dumps(completed, sort_keys=True)
        assert str(tmp_path) not in raw
        assert "argv" not in raw and "stderr" not in raw
    finally:
        capability.close()


def test_t0_engine_terminal_wins_over_a_late_console_cancel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database, candidate_id = _approved_candidate_database(tmp_path)
    capability = _frozen_capability(tmp_path, monkeypatch)
    try:
        search_campaign.prepare_round_one(
            database, capability, [candidate_id], campaign_id="search-terminal-wins"
        )
        campaign_id = _round_one_no_parent_receipts(capability)
        search_campaign.record_search_runtime_status(
            capability, campaign_id, "CANCELLED", 1, error_code="LATE_CANCEL"
        )

        state = search_campaign.load_public_search_state(capability)

        assert state["status"] == "SEARCH_TERMINATED_NO_PARENT"
    finally:
        capability.close()


def test_t0_trial_identity_must_match_its_frozen_plan_candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database, candidate_id = _approved_candidate_database(tmp_path)
    capability = _frozen_capability(tmp_path, monkeypatch)
    try:
        search_campaign.prepare_round_one(
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
    capability = _frozen_capability(tmp_path, monkeypatch)
    try:
        prepared = search_campaign.prepare_round_one(
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
        search_campaign.record_search_runtime_status(
            capability, prepared.campaign_id, "RUNNING", 1
        )

        def expensive_poll_forbidden(*_args: object) -> object:
            raise AssertionError("GET/poll repeated an expensive frozen-input check")

        monkeypatch.setattr(search_campaign, "_acquisition_snapshot", expensive_poll_forbidden)
        monkeypatch.setattr(search_campaign, "_freqtrade_snapshot", expensive_poll_forbidden)

        assert search_campaign.load_public_search_state(
            capability, active=True
        )["status"] == "RUNNING"
        recovered = search_campaign.recover_interrupted_search(capability)
        assert recovered["status"] == "INTERRUPTED"
        assert search_campaign.load_public_search_state(capability)["status"] == "INTERRUPTED"
    finally:
        capability.close()


def test_t0_corrupt_search_context_is_locally_blocked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database, candidate_id = _approved_candidate_database(tmp_path)
    capability = _frozen_capability(tmp_path, monkeypatch)
    try:
        search_campaign.prepare_round_one(
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


def test_t0_engine_blocked_terminal_maps_to_failed_without_round_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database, candidate_id = _approved_candidate_database(tmp_path)
    capability = _frozen_capability(tmp_path, monkeypatch)
    try:
        prepared = search_campaign.prepare_round_one(
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
            "created_at_utc": "2026-09-01T00:00:00.000Z",
        }
        (capability.search_root / pilot.SEARCH_TERMINAL).write_bytes(
            pilot.canonical(blocked)
        )

        state = search_campaign.load_public_search_state(capability)

        assert state["status"] == "FAILED"
        assert state["campaign_id"] == prepared.campaign_id
        assert state["attempts"] == []
        assert state["search_finalist"] is None
        assert "error" not in state
    finally:
        capability.close()
