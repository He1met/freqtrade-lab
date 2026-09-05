"""Implement one frozen bounded research Pilot or its Search-only gate.

Candidate files and the selection rule are frozen before this command. The
command screens at most three Candidates on Development, seals Holdout before
one existing producer invocation, and never retries an opened Holdout.

The separate ``screen-search`` command consumes only its frozen Search contract.
It never enters the producer/database path or reads later research windows.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import math
import os
import re
import shlex
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile
import zipfile
from bisect import bisect_left
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Optional, Sequence


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lab.database import get_connection, init_database
from lab.bounded_strategy import (
    MAX_STATIC_LOOKBACK,
    BoundedStrategyError,
    analyze_bounded_causal_strategy_file,
)
from lab.codex_generation import GenerationContractError, load_profile_snapshot
from lab.research_candidate import (
    DEFAULT_RUNNER,
    DEFAULT_SANDBOX_EXEC,
    ResearchCandidateError,
    _publish_directory_exclusive,
    _prepare_freqtrade_source_snapshot,
    _run_scenario,
    _runtime_config,
    _validate_config,
    run_research_candidate,
)
from lab.strategy_library import (
    DEFAULT_PORT,
    StrategyLibraryError,
    validate_strategy_library_database,
)
from scripts.run_freqtrade_backtest import (
    OfflineBacktestError,
    SUPPORTED_DEPENDENCIES as RUNNER_DEPENDENCIES,
    _create_scenario_data_view,
    _verify_data_provenance,
    _verify_dependency_versions,
)


SCHEMA = "freqtrade-lab-bounded-pilot-v1"
PLAN = "pilot-spec.json"
WINDOW = "window-spec.json"
LEGACY_WINDOW_SCHEMA = "freqtrade-lab-okx-window-v1"
STRICT_WINDOW_SCHEMA = "freqtrade-lab-okx-window-v2"
ACQUISITION = "acquisition"
SELECTION = "development-selection.json"
HOLDOUT_AUTHORIZATION = "holdout-authorized.json"
HOLDOUT_SEAL = "scenario-opens/HOLDOUT.json"
STRESS_SEAL = "scenario-opens/HOLDOUT_STRESS.json"
TERMINAL = "pilot-terminal.json"
SEARCH_SCHEMA = "freqtrade-lab-bounded-evolution-search-v2"
SEARCH_CAMPAIGN = "campaign.json"
SEARCH_TRIALS = "trials.jsonl"
SEARCH_TERMINAL = "search-terminal.json"
SEARCH_TRIAL_SCHEMA = "freqtrade-lab-search-trial-v2"
SEARCH_TERMINAL_SCHEMA = "freqtrade-lab-search-terminal-v2"
SEARCH_PROJECTION_SCHEMA = "freqtrade-lab-search-generation-projection-v1"
SEARCH_DATA_SCHEMA = "freqtrade-lab-retained-search-data-v2"
PROFILE_DEVELOPMENT_SCHEMA = "freqtrade-lab-profile-development-pilot-v1"
PROFILE_DEVELOPMENT_ACQUISITION_SCHEMA = (
    "freqtrade-lab-profile-development-acquisition-v1"
)
DEVELOPMENT_ISOLATION = "development-isolation"
SEARCH_MAX_ATTEMPTS = 6
SEARCH_MAX_ROUNDS = 2
SEARCH_RANKING = (
    "net_profit_after_base_fees_pct_desc",
    "max_drawdown_pct_asc",
    "candidate_id_asc",
)
RANKING = (
    "profit_pct_desc",
    "max_drawdown_pct_asc",
    "profit_factor_desc",
    "candidate_id_asc",
)
TECHNICAL_ECONOMIC_GATE = "NONE_TECHNICAL_PILOT"
POSITIVE_ECONOMIC_GATE = "POSITIVE_DEVELOPMENT_V1"
POSITIVE_GATE_THRESHOLDS = (
    "minimum_profit_pct",
    "minimum_profit_factor",
    "maximum_drawdown_pct",
)
PROFILE_SEARCH_FIELDS = {
    "profile_snapshot", "profile_snapshot_sha256", "development_timerange",
    "pre_roll_candles", "strategy_analyses", "capacity",
    "active_attempt_limit", "holdout", "holdout_stress",
}
PROFILE_ACQUISITION_FIELDS = (
    "profile_snapshot",
    "profile_snapshot_sha256",
    "search_timerange",
    "development_timerange",
    "pre_roll_candles",
    "capacity",
    "finalist_gate",
    "holdout",
    "holdout_stress",
)
PROFILE_SNAPSHOT_FIELDS = {
    "id", "name", "domain", "exchange", "trading_mode", "margin_mode",
    "pairs", "timeframe", "detail_timeframe", "history_start_date",
    "smoke_days", "holdout_days", "starting_balance", "stake_amount",
    "max_open_trades", "taker_fee_rate", "stress_fee_multiplier",
    "max_drawdown_pct", "min_development_trades", "min_holdout_trades",
    "min_profit_factor", "is_default", "created_at", "updated_at",
}
PROFILE_SEARCH_GATE = "PROFILE_DRIVEN_POSITIVE_FINALIST_V1"
EXPLORATORY_PROTOCOL = "EXPLORATORY_SESSION_RESEARCH_V1"
PROFILE_ECONOMIC_GATE = "PROFILE_DRIVEN_ECONOMIC_GATE_V1"
PROFILE_ECONOMIC_GATE_FIELDS = {
    "name",
    "version",
    "minimum_net_profit_after_base_fees_pct",
    "minimum_average_holding_period_minutes",
    "maximum_roi_exit_count",
}
PROFILE_ACTIVE_ATTEMPTS = 3
PROFILE_TRADABLE_BALANCE_RATIO = 0.99
SEARCH_PUBLIC_TRIAL_FIELDS = (
    "round",
    "attempt_number",
    "candidate_id",
    "class_name",
    "mechanism",
    "strategy_sha256",
    "relationship",
    "changed_factor",
    "technical_status",
    "failure_reason",
    "search_metrics",
    "evidence",
)
SEARCH_TERMINAL_FIELDS = {
    "schema", "campaign_id", "campaign_sha256", "contract_sha256", "round",
    "status", "finalist_gate", "search_finalist", "round_receipt_sha256",
    "trials_sha256", "brief", "created_at_utc",
}


def _search_terminal_fields(value: Mapping[str, Any]) -> set[str]:
    fields = set(SEARCH_TERMINAL_FIELDS)
    if "economic_gate" in value:
        fields.add("economic_gate")
    return fields
MARKET_STATE_DEFINITION = "LAST_CLOSED_CLOSE_VS_SMA_N_V1"
PROFILE_TIMEFRAME_STEPS = {"5m": timedelta(minutes=5), "1d": timedelta(days=1)}
SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
CLASS = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
LOOPBACK_URL = re.compile(r"^http://127\.0\.0\.1:([1-9][0-9]{0,4})$")
RUNNER_SHA = hashlib.sha256(DEFAULT_RUNNER.read_bytes()).hexdigest()

class PilotError(ValueError):
    """A terminal, fail-closed Pilot error."""


class PresentationUnavailableError(PilotError):
    """The isolated optional presentation target cannot be published."""


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode()


def search_projection_sha256(
    request: Mapping[str, Any],
    terminal: Mapping[str, Any],
    evidence: Mapping[str, Any],
) -> str:
    """Bind every independently mutable JSON part of a terminal projection."""
    return digest(
        canonical(
            {
                "schema": SEARCH_PROJECTION_SCHEMA,
                "request_sha256": digest(canonical(request)),
                "terminal_sha256": digest(canonical(terminal)),
                "evidence_sha256": digest(canonical(evidence)),
            }
        )
    )


def search_projection_request(
    round_contracts: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Build the complete immutable Search request projected to schema v1."""
    public_contracts = [{key: value for key, value in item.items() if not key.startswith("_")} for item in round_contracts]
    if not public_contracts:
        raise PilotError("Search projection requires at least one round contract")
    return {
        "schema": SEARCH_PROJECTION_SCHEMA,
        "campaign_id": public_contracts[0].get("campaign_id"),
        "round_contracts": public_contracts,
    }


def _projection_evidence_shape(value: Any, trial: Mapping[str, Any]) -> bool:
    if not isinstance(value, Mapping) or set(value) != {"archive", "result", "report_semantic_sha256"}:
        return False
    archive, result = value.get("archive"), value.get("result")
    if not all(isinstance(item, Mapping) and set(item) == {"path", "sha256"} for item in (archive, result)):
        return False
    prefix = f"search-results-round-{trial.get('round')}/{trial.get('candidate_id')}"
    path = archive.get("path")
    parts = PurePosixPath(path).parts if isinstance(path, str) else ()
    raw_parts = PurePosixPath(prefix, "raw").parts
    hashes = (archive.get("sha256"), result.get("sha256"), value.get("report_semantic_sha256"))
    return bool(
        parts[: len(raw_parts)] == raw_parts
        and len(parts) == len(raw_parts) + 1
        and result.get("path") == f"{prefix}/result.json"
        and all(isinstance(item, str) and _SHA256.fullmatch(item) for item in hashes)
    )


def verify_search_terminal_projection(
    request: Mapping[str, Any],
    terminal: Mapping[str, Any],
    evidence: Mapping[str, Any],
) -> dict[str, Any]:
    """Verify the complete frozen Search request, attempts, and terminal."""
    round_contracts = request.get("round_contracts") if isinstance(request, Mapping) else None
    if (not isinstance(request, Mapping) or set(request) != {"schema", "campaign_id", "round_contracts"}
            or request.get("schema") != SEARCH_PROJECTION_SCHEMA
            or not isinstance(round_contracts, list)
            or not 1 <= len(round_contracts) <= SEARCH_MAX_ROUNDS):
        raise PilotError("Search terminal projection request is invalid")
    contracts = []
    for raw in round_contracts:
        if not isinstance(raw, dict) or any(str(key).startswith("_") for key in raw):
            raise PilotError("Search terminal projection round contract is invalid")
        contracts.append(_load_search_campaign(dict(raw), canonical(raw)))
    campaign_id = request.get("campaign_id")
    if ([item["round"] for item in contracts] != list(range(1, len(contracts) + 1))
            or any(item["campaign_id"] != campaign_id for item in contracts)
            or any(item["_contract_sha256"] != contracts[0]["_contract_sha256"] for item in contracts[1:])):
        raise PilotError("Search terminal projection round binding is invalid")
    if not isinstance(evidence, Mapping) or set(evidence) not in ({"terminal", "attempts"}, {"terminal", "trials", "attempts"}):
        raise PilotError("Search terminal projection evidence is invalid")
    if evidence.get("terminal") != {"path": SEARCH_TERMINAL, "sha256": digest(canonical(terminal))}:
        raise PilotError("Search terminal projection terminal pointer is invalid")
    trials_pointer = evidence.get("trials")
    if trials_pointer is not None and (not isinstance(trials_pointer, Mapping)
            or set(trials_pointer) != {"path", "sha256"}
            or trials_pointer.get("path") != SEARCH_TRIALS
            or not isinstance(trials_pointer.get("sha256"), str)
            or _SHA256.fullmatch(trials_pointer["sha256"]) is None):
        raise PilotError("Search terminal projection trials pointer is invalid")
    attempts = evidence.get("attempts")
    if not isinstance(attempts, list) or len(attempts) > SEARCH_MAX_ATTEMPTS:
        raise PilotError("Search terminal projection attempts are invalid")
    expected = [(item["round"], candidate) for item in contracts for candidate in item["candidates"]]
    verified_attempts = []
    identity_fields = ("candidate_id", "class_name", "mechanism", "strategy_sha256", "relationship", "changed_factor")
    for index, raw in enumerate(attempts):
        if not isinstance(raw, Mapping) or set(raw) != set(SEARCH_PUBLIC_TRIAL_FIELDS) or index >= len(expected):
            raise PilotError("Search terminal projection attempt shape is invalid")
        trial, (round_number, candidate) = dict(raw), expected[index]
        if (trial.get("round") != round_number or trial.get("attempt_number") != index + 1
                or isinstance(trial.get("attempt_number"), bool)
                or any(trial.get(field) != candidate.get(field) for field in identity_fields)):
            raise PilotError("Search terminal projection attempt binding is invalid")
        if trial.get("technical_status") == "VALID":
            if trial.get("failure_reason") is not None or not _projection_evidence_shape(trial.get("evidence"), trial):
                raise PilotError("Search terminal projection valid attempt is invalid")
            _validated_search_metrics(trial.get("search_metrics"))
        elif trial.get("technical_status") == "INVALID":
            reason = trial.get("failure_reason")
            if (not isinstance(reason, str) or not reason or len(reason) > 500
                    or reason != " ".join(reason.split()) or trial.get("search_metrics") is not None
                    or trial.get("evidence") is not None):
                raise PilotError("Search terminal projection invalid attempt is invalid")
        else:
            raise PilotError("Search terminal projection technical status is invalid")
        verified_attempts.append(trial)
    current = contracts[-1]
    trials_sha = trials_pointer["sha256"] if isinstance(trials_pointer, Mapping) else digest(b"")
    if (not isinstance(terminal, Mapping) or terminal.get("schema") != SEARCH_TERMINAL_SCHEMA
            or terminal.get("campaign_id") != campaign_id or terminal.get("round") != current["round"]
            or terminal.get("campaign_sha256") != current["_sha256"]
            or terminal.get("contract_sha256") != current["_contract_sha256"]
            or terminal.get("trials_sha256") != trials_sha):
        raise PilotError("Search terminal projection terminal binding is invalid")
    status = terminal.get("status")
    if status == "SEARCH_BLOCKED":
        error = terminal.get("error")
        blocked_fields = SEARCH_TERMINAL_FIELDS - {
            "finalist_gate", "search_finalist", "round_receipt_sha256", "brief"
        } | {"error"}
        if (set(terminal) != blocked_fields or not isinstance(error, str) or not error
                or len(error) > 1000 or error != " ".join(error.split())):
            raise PilotError("Search blocked terminal projection is invalid")
    else:
        if set(terminal) != _search_terminal_fields(terminal) or len(verified_attempts) != len(expected):
            raise PilotError("Search terminal projection omits an attempt")
        current_attempts = [{key: value for key, value in item.items()
                             if key not in {"round", "attempt_number"} and not (key == "evidence" and value is None)}
                            for item in verified_attempts if item["round"] == current["round"]]
        brief, expected_status, finalist = _search_round_outcome(
            current, verified_attempts, current_attempts,
            len(verified_attempts) - len(current_attempts),
        )
        receipt_sha = terminal.get("round_receipt_sha256")
        if (status != expected_status or terminal.get("brief") != brief
                or terminal.get("search_finalist") != finalist
                or terminal.get("finalist_gate") != current["finalist_gate"]
                or terminal.get("economic_gate") != current.get("economic_gate")
                or not isinstance(receipt_sha, str) or _SHA256.fullmatch(receipt_sha) is None):
            raise PilotError("Search terminal projection outcome is invalid")
    return {"round_contracts": contracts, "profile_snapshot": dict(contracts[0]["profile_snapshot"]),
            "attempts": verified_attempts, "finalist": terminal.get("search_finalist"), "status": status}


def load_json(path: Path, label: str) -> tuple[dict[str, Any], bytes]:
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 64 * 1024 * 1024:
            raise PilotError(f"{label} must be a bounded regular file")
        data = path.read_bytes()
        value = json.loads(data)
    except PilotError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PilotError(f"{label} cannot be read: {exc}") from exc
    if not isinstance(value, dict):
        raise PilotError(f"{label} must be a JSON object")
    return value, data


def finite(value: Any, label: str, minimum: Optional[float] = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PilotError(f"{label} must be a finite number")
    number = float(value)
    if not math.isfinite(number) or (minimum is not None and number < minimum):
        raise PilotError(f"{label} must be a finite number")
    return number


def validate_profile_economic_gate(value: Any) -> dict[str, Any]:
    """Validate one result-independent Profile economic Gate V1 contract."""
    if not isinstance(value, Mapping) or set(value) != PROFILE_ECONOMIC_GATE_FIELDS:
        raise PilotError("Profile economic Gate shape is invalid")
    version = value.get("version")
    if (
        value.get("name") != PROFILE_ECONOMIC_GATE
        or isinstance(version, bool)
        or version != 1
    ):
        raise PilotError("Profile economic Gate version is not supported")
    minimum_net = finite(
        value.get("minimum_net_profit_after_base_fees_pct"),
        "Profile economic Gate minimum net profit",
        0,
    )
    minimum_holding = finite(
        value.get("minimum_average_holding_period_minutes"),
        "Profile economic Gate minimum holding period",
        0,
    )
    maximum_roi = value.get("maximum_roi_exit_count")
    if isinstance(maximum_roi, bool) or not isinstance(maximum_roi, int) or maximum_roi < 0:
        raise PilotError("Profile economic Gate maximum ROI exit count is invalid")
    return {
        "name": PROFILE_ECONOMIC_GATE,
        "version": 1,
        "minimum_net_profit_after_base_fees_pct": minimum_net,
        "minimum_average_holding_period_minutes": minimum_holding,
        "maximum_roi_exit_count": maximum_roi,
    }


def load_profile_economic_gate(path: Path) -> dict[str, Any]:
    """Load one bounded JSON Gate input and normalize it before freezing."""
    value, _ = load_json(path, "Profile economic Gate")
    return validate_profile_economic_gate(value)


def _profile_economic_gate(value: Mapping[str, Any]) -> Optional[dict[str, Any]]:
    if "economic_gate" not in value:
        return None
    return validate_profile_economic_gate(value.get("economic_gate"))


def _profile_acquisition_contract_fields(value: Mapping[str, Any]) -> tuple[str, ...]:
    return (
        *PROFILE_ACQUISITION_FIELDS,
        *(("economic_gate",) if "economic_gate" in value else ()),
        *(("exploration",) if "exploration" in value else ()),
    )


def validate_exploration(value: Any) -> dict[str, Any]:
    """Frozen exposure audit binding; never an independent validation contract."""
    if (not isinstance(value, dict)
            or set(value) != {"protocol", "status", "exposure_audit_sha256", "prior_research"}
            or value.get("protocol") != EXPLORATORY_PROTOCOL
            or value.get("status") != "NOT_INDEPENDENTLY_VALIDATED"
            or not isinstance(value.get("exposure_audit_sha256"), str)
            or re.fullmatch(r"[0-9a-f]{64}", value["exposure_audit_sha256"]) is None
            or not isinstance(value.get("prior_research"), list)
            or not 1 <= len(value["prior_research"]) <= 8
            or any(not isinstance(item, str) or not 1 <= len(item) <= 256
                   for item in value["prior_research"])):
        raise PilotError("Exploration contract is missing or invalid")
    return dict(value)


def timerange(value: Any, label: str) -> tuple[datetime, datetime]:
    if not isinstance(value, str) or re.fullmatch(r"\d{8}-\d{8}", value) is None:
        raise PilotError(f"{label} must use YYYYMMDD-YYYYMMDD")
    try:
        start = datetime.strptime(value[:8], "%Y%m%d").replace(tzinfo=timezone.utc)
        end = datetime.strptime(value[9:], "%Y%m%d").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise PilotError(f"{label} has an invalid date") from exc
    if end <= start:
        raise PilotError(f"{label} must have positive duration")
    return start, end


def _utc_boundary(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or len(value) != 20 or not value.endswith("Z"):
        raise PilotError(f"{label} must use YYYY-MM-DDTHH:MM:SSZ")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise PilotError(f"{label} must use YYYY-MM-DDTHH:MM:SSZ") from exc
    return parsed


def _validate_strict_window(
    value: Mapping[str, Any],
    dev_start: datetime,
    dev_end: datetime,
    hold_start: datetime,
    hold_end: datetime,
) -> None:
    required = {
        "schema",
        "data_start_utc",
        "development_start_utc",
        "holdout_start_utc",
        "end_exclusive_utc",
    }
    if set(value) != required or value.get("schema") != STRICT_WINDOW_SCHEMA:
        raise PilotError("strict window spec shape/version is not supported")
    data_start = _utc_boundary(value["data_start_utc"], "window data start")
    boundaries = (
        _utc_boundary(value["development_start_utc"], "window Development start"),
        _utc_boundary(value["holdout_start_utc"], "window Holdout start"),
        _utc_boundary(value["end_exclusive_utc"], "window exclusive stop"),
    )
    if (
        boundaries != (dev_start, hold_start, hold_end)
        or dev_end != hold_start
        or dev_end - dev_start != timedelta(days=60)
        or hold_end - hold_start != timedelta(days=30)
        or not data_start < dev_start
        or dev_start - data_start > timedelta(days=1)
        or any((data_start.minute, data_start.second, data_start.microsecond))
    ):
        raise PilotError(
            "strict window must bind contiguous 60-day Development and 30-day Holdout"
        )


def safe_file(root: Path, value: Any, label: str) -> Path:
    if not isinstance(value, str) or not value or "\\" in value or ".." in Path(value).parts:
        raise PilotError(f"{label} must be a safe relative path")
    path = Path(value)
    if path.is_absolute():
        raise PilotError(f"{label} must be a safe relative path")
    try:
        resolved = (root / path).resolve(strict=True)
        resolved.relative_to(root.resolve(strict=True))
    except (OSError, RuntimeError, ValueError) as exc:
        raise PilotError(f"{label} escapes the Pilot root") from exc
    if resolved.is_symlink() or not resolved.is_file():
        raise PilotError(f"{label} must be a regular file")
    return resolved


def causal_source(path: Path, class_name: str, *, expected_timeframe: str = "5m") -> Any:
    try:
        return analyze_bounded_causal_strategy_file(
            path, class_name, expected_timeframe=expected_timeframe
        )
    except BoundedStrategyError as exc:
        raise PilotError(str(exc)) from exc


def profile_search_capacity(
    profile_snapshot: Mapping[str, Any], search_timerange: str
) -> dict[str, int]:
    """Return the deterministic Profile capacity bound before any mutation."""
    timeframe = profile_snapshot.get("timeframe")
    pairs = profile_snapshot.get("pairs")
    max_open = profile_snapshot.get("max_open_trades")
    required = profile_snapshot.get("min_development_trades")
    if (timeframe not in PROFILE_TIMEFRAME_STEPS or not isinstance(pairs, list) or not pairs
            or isinstance(max_open, bool) or not isinstance(max_open, int) or max_open <= 0
            or isinstance(required, bool) or not isinstance(required, int) or required < 0):
        raise PilotError("Profile Search capacity inputs are invalid")
    start, stop = timerange(search_timerange, "Search")
    decision_slots = (stop - start) // PROFILE_TIMEFRAME_STEPS[str(timeframe)]
    entry_slots = max(0, int(decision_slots) - 2)
    maximum = entry_slots * min(len(pairs), max_open)
    result = {"maximum_theoretical_trades": int(maximum), "required_minimum_trades": required}
    if maximum < required:
        raise PilotError("BLOCKED_INSUFFICIENT_CAPACITY")
    return result


def profile_search_config(profile_snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Construct the sole base Freqtrade config for a frozen Profile."""
    pairs = profile_snapshot.get("pairs")
    if not isinstance(pairs, list) or len(pairs) != 1 or not isinstance(pairs[0], str):
        raise PilotError("Profile Search execution requires exactly one pair")
    match = re.fullmatch(
        r"([A-Za-z0-9-]+)/([A-Za-z0-9-]+):([A-Za-z0-9-]+)", pairs[0]
    )
    if match is None or match.group(2) != match.group(3):
        raise PilotError("Profile Search pair is outside the linear futures boundary")
    return {
        "max_open_trades": profile_snapshot["max_open_trades"],
        "stake_currency": match.group(2),
        "stake_amount": profile_snapshot["stake_amount"],
        "tradable_balance_ratio": PROFILE_TRADABLE_BALANCE_RATIO,
        "fiat_display_currency": "USD",
        "dry_run": True,
        "dry_run_wallet": profile_snapshot["starting_balance"],
        "cancel_open_orders_on_exit": False,
        "trading_mode": "futures",
        "margin_mode": "isolated",
        "timeframe": profile_snapshot["timeframe"],
        "fee": profile_snapshot["taker_fee_rate"],
        "unfilledtimeout": {"entry": 10, "exit": 30, "exit_timeout_count": 0, "unit": "minutes"},
        "entry_pricing": {"price_side": "same", "use_order_book": True, "order_book_top": 1},
        "exit_pricing": {"price_side": "same", "use_order_book": True, "order_book_top": 1},
        "exchange": {"name": "okx", "enable_ws": False, "pair_whitelist": pairs, "pair_blacklist": []},
        "pairlists": [{"method": "StaticPairList"}],
        "strategy": None,
        "dataformat_ohlcv": "feather",
        "disableparamexport": True,
        "backtest_cache": "none",
    }


def profile_search_finalist_gate(profile_snapshot: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "name": PROFILE_SEARCH_GATE,
        "minimum_trades": profile_snapshot.get("min_development_trades"),
        "minimum_profit_factor": profile_snapshot.get("min_profit_factor"),
        "maximum_drawdown_pct": profile_snapshot.get("max_drawdown_pct"),
        "net_profit_after_fees": "STRICTLY_POSITIVE",
    }


def validate_profile_runtime_contract(
    profile_snapshot: Mapping[str, Any],
    *,
    runtime_config: Optional[Mapping[str, Any]] = None,
    finalist_gate: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """Purely normalize the Profile values shared by Search and Development."""
    if not isinstance(profile_snapshot, Mapping) or set(profile_snapshot) != PROFILE_SNAPSHOT_FIELDS:
        raise PilotError("Profile Search snapshot shape is invalid")
    snapshot = dict(profile_snapshot)
    pairs, timeframe = snapshot.get("pairs"), snapshot.get("timeframe")
    if (snapshot.get("domain") != "OKX_CRYPTO_PERP" or snapshot.get("exchange") != "okx"
            or snapshot.get("trading_mode") != "futures" or snapshot.get("margin_mode") != "isolated"
            or snapshot.get("detail_timeframe") is not None or timeframe not in PROFILE_TIMEFRAME_STEPS
            or not isinstance(pairs, list) or len(pairs) != 1 or not isinstance(pairs[0], str) or not pairs[0]
            or not isinstance(snapshot.get("id"), str) or SAFE_ID.fullmatch(snapshot["id"]) is None
            or not isinstance(snapshot.get("history_start_date"), str)
            or re.fullmatch(r"\d{4}-\d{2}-\d{2}", snapshot["history_start_date"]) is None):
        raise PilotError("Profile Search snapshot runtime contract is invalid")
    values = {key: finite(snapshot.get(key), f"Profile {key}", 0) for key in (
        "starting_balance", "stake_amount", "taker_fee_rate", "min_profit_factor", "max_drawdown_pct"
    )}
    starting_balance, stake_amount = values["starting_balance"], values["stake_amount"]
    if starting_balance <= 0 or stake_amount <= 0:
        raise PilotError("Profile balance and stake must be positive")
    if stake_amount > starting_balance * PROFILE_TRADABLE_BALANCE_RATIO:
        raise PilotError("BLOCKED_INSUFFICIENT_CAPACITY")
    fee, profit_factor, drawdown = (values[key] for key in (
        "taker_fee_rate", "min_profit_factor", "max_drawdown_pct"
    ))
    if drawdown <= 0 or drawdown > 100:
        raise PilotError("Profile max_drawdown_pct is invalid")
    for key in ("max_open_trades", "min_development_trades"):
        item = snapshot.get(key)
        if isinstance(item, bool) or not isinstance(item, int) or item < (key == "max_open_trades"):
            raise PilotError(f"Profile {key} is invalid")
    expected_config = profile_search_config(snapshot)
    if runtime_config is not None:
        normalized_config = dict(runtime_config)
        normalized_config["strategy"] = None
        if normalized_config != expected_config:
            raise PilotError("Freqtrade config disagrees with the frozen Profile")
    expected_gate = profile_search_finalist_gate(snapshot)
    if finalist_gate is not None and dict(finalist_gate) != expected_gate:
        raise PilotError("Finalist Gate disagrees with the frozen Profile")
    return {
        "profile_snapshot": snapshot,
        "profile_snapshot_sha256": digest(canonical(snapshot)),
        "pair": pairs[0], "timeframe": timeframe,
        "timeframe_step_seconds": int(PROFILE_TIMEFRAME_STEPS[str(timeframe)].total_seconds()),
        "fee": fee, "starting_balance": starting_balance, "stake_amount": stake_amount,
        "max_open_trades": snapshot["max_open_trades"],
        "minimum_trades": snapshot["min_development_trades"],
        "minimum_profit_factor": profit_factor, "maximum_drawdown_pct": drawdown,
        "tradable_balance_ratio": PROFILE_TRADABLE_BALANCE_RATIO,
        "finalist_gate": expected_gate,
    }


def _validated_profile_search_contract(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the Profile, windows, capacity, and Gate shared by data and Search."""
    required = {"profile_snapshot", "profile_snapshot_sha256", "search_timerange",
                "development_timerange", "pre_roll_candles"}
    if not required <= set(value):
        raise PilotError("Profile Search contract is incomplete")
    snapshot = value.get("profile_snapshot")
    profile = validate_profile_runtime_contract(snapshot)
    snapshot = profile["profile_snapshot"]
    timeframe = profile["timeframe"]
    if value["profile_snapshot_sha256"] != digest(canonical(snapshot)):
        raise PilotError("Profile Search snapshot SHA-256 mismatch")
    pre_roll = value.get("pre_roll_candles")
    if isinstance(pre_roll, bool) or not isinstance(pre_roll, int) or not 1 <= pre_roll <= MAX_STATIC_LOOKBACK:
        raise PilotError("Profile Search pre-roll is invalid")
    search_start, search_stop = timerange(value["search_timerange"], "Search")
    exploration = validate_exploration(value["exploration"]) if "exploration" in value else None
    if exploration is not None:
        if value["development_timerange"] is not None:
            raise PilotError("Exploration must not reserve a Development window")
        development_start = search_stop
    else:
        development_start, _ = timerange(value["development_timerange"], "Development")
    try:
        history_start = datetime.strptime(snapshot["history_start_date"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise PilotError("Profile history_start_date is invalid") from exc
    startup_start = search_start - PROFILE_TIMEFRAME_STEPS[str(timeframe)] * pre_roll
    if search_stop > development_start or history_start > startup_start:
        raise PilotError("Profile Search/Development windows are not frozen and disjoint")
    economic_gate = _profile_economic_gate(value)
    return {
        **profile,
        "capacity": profile_search_capacity(snapshot, value["search_timerange"]),
        "economic_gate": economic_gate,
    }


def validate_profile_search_plan(plan: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the one supported Profile-driven Search contract."""
    public = {key: value for key, value in plan.items() if not key.startswith("_")}
    base = {"schema", "campaign_id", "freqtrade_version", "round", "previous_round_receipt_sha256",
            "search_timerange", "data_provenance_sha256", "budget", "ranking", "finalist_gate", "parent", "candidates"}
    expected_fields = base | PROFILE_SEARCH_FIELDS
    if "economic_gate" in public:
        expected_fields.add("economic_gate")
    if "exploration" in public:
        expected_fields.add("exploration")
    if set(public) != expected_fields:
        raise PilotError("Profile Search plan extension is incomplete or contains extras")
    profile = validate_profile_search_contract(public)
    snapshot = profile["profile_snapshot"]
    candidates = public.get("candidates")
    analyses = public.get("strategy_analyses")
    if (public.get("active_attempt_limit") != (2 if "exploration" in public else PROFILE_ACTIVE_ATTEMPTS)
            or public.get("holdout") != "SEALED_UNREAD" or public.get("holdout_stress") != "SEALED_UNREAD"
            or not isinstance(candidates, list) or any(not isinstance(item, dict) for item in candidates)
            or not isinstance(analyses, dict)
            or set(analyses) != {item.get("candidate_id") for item in candidates if isinstance(item, dict)}
            or len(candidates) > (2 if public.get("round") == 1 and "exploration" not in public else 1)):
        raise PilotError("Profile Search budget, pre-roll, or analyses are invalid")
    for candidate, analysis in zip(candidates, (analyses[item["candidate_id"]] for item in candidates), strict=True):
        candidate_fields = {"candidate_id", "class_name", "mechanism", "relationship", "changed_factor",
                            "parent_strategy_sha256", "strategy_file", "strategy_sha256", "generation_run_id", "profile_id"}
        analysis_fields = ("startup_candle_count", "maximum_lookback")
        if (set(candidate) != candidate_fields or candidate.get("profile_id") != snapshot["id"]
                or not isinstance(candidate.get("generation_run_id"), str)
                or SAFE_ID.fullmatch(candidate["generation_run_id"]) is None or not isinstance(analysis, dict)
                or set(analysis) != {"timeframe", *analysis_fields} or analysis.get("timeframe") != profile["timeframe"]
                or any(isinstance(analysis.get(key), bool) or not isinstance(analysis.get(key), int)
                       for key in analysis_fields)
                or analysis["startup_candle_count"] < analysis["maximum_lookback"]
                or analysis["maximum_lookback"] <= 0
                or public["pre_roll_candles"] < analysis["startup_candle_count"]):
            raise PilotError("Profile Search Candidate analysis/binding is invalid")
    return profile


def profile_search_contract(
    profile_snapshot: Mapping[str, Any],
    search_timerange: str,
    development_timerange: Optional[str],
    pre_roll_candles: int,
    economic_gate: Optional[Mapping[str, Any]] = None,
    exploration: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """Freeze the candidate-independent Profile contract used by data and Search."""
    contract = {
        "profile_snapshot": dict(profile_snapshot),
        "profile_snapshot_sha256": digest(canonical(profile_snapshot)),
        "search_timerange": search_timerange,
        "development_timerange": development_timerange,
        "pre_roll_candles": pre_roll_candles,
    }
    if economic_gate is not None:
        contract["economic_gate"] = validate_profile_economic_gate(economic_gate)
    if exploration is not None:
        contract["exploration"] = validate_exploration(exploration)
    profile = _validated_profile_search_contract(contract)
    contract.update(capacity=profile["capacity"], finalist_gate=profile["finalist_gate"],
                    holdout="SEALED_UNREAD", holdout_stress="SEALED_UNREAD")
    validate_profile_search_contract(contract)
    return contract


def profile_acquisition_contract(
    database_path: Path,
    profile_id: str,
    search_timerange: str,
    development_timerange: Optional[str],
    pre_roll_candles: int,
    economic_gate: Optional[Mapping[str, Any]] = None,
    exploration: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """Load one Profile read-only and return its acquisition/runtime contract."""
    try:
        with get_connection(database_path, read_only=True) as connection:
            snapshot = load_profile_snapshot(connection, profile_id)
    except GenerationContractError as exc:
        raise PilotError(exc.message) from exc
    contract = profile_search_contract(
        snapshot,
        search_timerange,
        development_timerange,
        pre_roll_candles,
        economic_gate,
        exploration,
    )
    profile = validate_profile_search_contract(contract)
    return {
        **contract,
        "pair": profile["pair"],
        "timeframe": profile["timeframe"],
        "runtime_config": profile_search_config(contract["profile_snapshot"]),
    }


def validate_profile_search_contract(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the shared candidate-independent Profile Search contract."""
    profile = _validated_profile_search_contract(value)
    if (value.get("capacity") != profile["capacity"] or value.get("finalist_gate") != profile["finalist_gate"]
            or value.get("holdout") != "SEALED_UNREAD" or value.get("holdout_stress") != "SEALED_UNREAD"):
        raise PilotError("Profile Search contract changed after freeze")
    return profile


def _search_contract(plan: Mapping[str, Any]) -> dict[str, Any]:
    contract = {
        "schema": plan["schema"],
        "campaign_id": plan["campaign_id"],
        "freqtrade_version": plan["freqtrade_version"],
        "search_timerange": plan["search_timerange"],
        "data_provenance_sha256": plan["data_provenance_sha256"],
        "budget": plan["budget"],
        "ranking": plan["ranking"],
        "finalist_gate": plan["finalist_gate"],
        **{
            key: plan[key]
            for key in PROFILE_SEARCH_FIELDS - {"strategy_analyses"}
        },
    }
    if "economic_gate" in plan:
        contract["economic_gate"] = validate_profile_economic_gate(
            plan["economic_gate"]
        )
    if "exploration" in plan:
        contract["exploration"] = validate_exploration(plan["exploration"])
    return contract


def _load_search_campaign(
    plan: dict[str, Any], plan_bytes: bytes
) -> dict[str, Any]:
    required = {
        "schema",
        "campaign_id",
        "freqtrade_version",
        "round",
        "previous_round_receipt_sha256",
        "search_timerange",
        "data_provenance_sha256",
        "budget",
        "ranking",
        "finalist_gate",
        "parent",
        "candidates",
    }
    expected_fields = required | PROFILE_SEARCH_FIELDS
    if "economic_gate" in plan:
        expected_fields.add("economic_gate")
    if "exploration" in plan:
        expected_fields.add("exploration")
    if (
        set(plan) != expected_fields
        or plan.get("schema") != SEARCH_SCHEMA
        or plan.get("freqtrade_version") != "2026.7"
    ):
        raise PilotError("Search campaign shape/version is not supported")
    profile = validate_profile_search_plan(plan)
    campaign_id = plan["campaign_id"]
    if not isinstance(campaign_id, str) or SAFE_ID.fullmatch(campaign_id) is None:
        raise PilotError("campaign_id is unsafe")
    round_number = plan["round"]
    if isinstance(round_number, bool) or round_number not in {1, 2}:
        raise PilotError("Search round must be 1 or 2")
    start, end = timerange(plan["search_timerange"], "Search")
    search_days = (end - start).days
    if search_days < 1 or search_days > 366:
        raise PilotError("Search window exceeds its bounded duration")
    if (
        not isinstance(plan["data_provenance_sha256"], str)
        or re.fullmatch(r"[0-9a-f]{64}", plan["data_provenance_sha256"]) is None
    ):
        raise PilotError("Search data provenance hash is invalid")
    if plan["budget"] != {"maximum_attempts": SEARCH_MAX_ATTEMPTS}:
        raise PilotError("Search budget must freeze exactly six attempts")
    if tuple(plan["ranking"]) != SEARCH_RANKING:
        raise PilotError("Search ranking is not the frozen V2 ranking")
    previous = plan["previous_round_receipt_sha256"]
    parent = plan["parent"]
    if round_number == 1:
        if previous is not None or parent is not None:
            raise PilotError("Search round 1 cannot declare prior state")
    else:
        if not isinstance(previous, str) or re.fullmatch(r"[0-9a-f]{64}", previous) is None:
            raise PilotError("Search round 2 must bind the round 1 receipt")
        if not isinstance(parent, dict) or set(parent) != {
            "candidate_id",
            "class_name",
            "mechanism",
            "strategy_sha256",
        }:
            raise PilotError("Search round 2 parent identity is invalid")
    candidates = plan["candidates"]
    fields = {
        "candidate_id",
        "class_name",
        "mechanism",
        "relationship",
        "changed_factor",
        "parent_strategy_sha256",
        "strategy_file",
        "strategy_sha256",
    }
    fields |= {"generation_run_id", "profile_id"}
    maximum_candidates = 2 if round_number == 1 else 1
    if not isinstance(candidates, list) or not 1 <= len(candidates) <= maximum_candidates:
        raise PilotError(
            "Search Round 1 must contain one or two Candidates; Round 2 exactly one Candidate"
        )
    candidate_ids: set[str] = set()
    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, dict) or set(candidate) != fields:
            raise PilotError(f"Search candidate {index} shape is invalid")
        candidate_id = candidate["candidate_id"]
        class_name = candidate["class_name"]
        strategy_file = candidate["strategy_file"]
        strategy_sha256 = candidate["strategy_sha256"]
        if (
            not isinstance(candidate_id, str)
            or SAFE_ID.fullmatch(candidate_id) is None
            or not isinstance(class_name, str)
            or CLASS.fullmatch(class_name) is None
            or not isinstance(strategy_file, str)
            or not strategy_file
            or Path(strategy_file).is_absolute()
            or "\\" in strategy_file
            or ".." in Path(strategy_file).parts
            or not isinstance(strategy_sha256, str)
            or re.fullmatch(r"[0-9a-f]{64}", strategy_sha256) is None
        ):
            raise PilotError(f"Search candidate {index} identity envelope is invalid")
        if candidate_id in candidate_ids:
            raise PilotError("Search candidate identities must be unique within a round")
        candidate_ids.add(candidate_id)
    plan["_sha256"] = digest(plan_bytes)
    plan["_contract_sha256"] = digest(canonical(_search_contract(plan)))
    return plan


def load_plan(root: Path, name: str = PLAN) -> dict[str, Any]:
    label = "Search campaign" if name == SEARCH_CAMPAIGN else "pilot spec"
    plan, plan_bytes = load_json(root / name, label)
    if name == SEARCH_CAMPAIGN:
        return _load_search_campaign(plan, plan_bytes)
    required = {
        "schema",
        "pilot_id",
        "freqtrade_version",
        "window_spec_sha256",
        "development_timerange",
        "holdout_timerange",
        "stress_fee_multiplier",
        "selection",
        "holdout_policy",
        "candidates",
    }
    if set(plan) != required or plan["schema"] != SCHEMA or plan["freqtrade_version"] != "2026.7":
        raise PilotError("pilot spec shape/version is not supported")
    if not isinstance(plan["pilot_id"], str) or SAFE_ID.fullmatch(plan["pilot_id"]) is None:
        raise PilotError("pilot_id is unsafe")
    window, window_bytes = load_json(root / WINDOW, "window spec")
    if plan["window_spec_sha256"] != digest(window_bytes):
        raise PilotError("window spec hash mismatch")
    dev_start, dev_end = timerange(plan["development_timerange"], "Development")
    hold_start, hold_end = timerange(plan["holdout_timerange"], "Holdout")
    if window.get("schema") == STRICT_WINDOW_SCHEMA:
        _validate_strict_window(window, dev_start, dev_end, hold_start, hold_end)
    elif window.get("schema") == LEGACY_WINDOW_SCHEMA:
        if dev_end != hold_start or not 60 <= (hold_end - dev_start).days <= 90:
            raise PilotError(
                "Development/Holdout must be contiguous and span 60 to 90 days"
            )
    else:
        raise PilotError("window spec shape/version is not supported")
    multiplier = finite(plan["stress_fee_multiplier"], "stress multiplier", 1.0)
    if multiplier <= 1:
        raise PilotError("stress multiplier must exceed 1")
    selection = plan["selection"]
    selection_keys = {
        "minimum_trades",
        "ranking",
        "economic_gate",
        "max_selected",
        "no_eligible",
        "missing_metric_policy",
        "visibility",
        "candidate_execution_failure",
    }
    if not isinstance(selection, dict):
        raise PilotError("selection rule shape is invalid")
    gate = selection.get("economic_gate")
    if gate == TECHNICAL_ECONOMIC_GATE:
        expected_selection_keys = selection_keys
    elif gate == POSITIVE_ECONOMIC_GATE:
        expected_selection_keys = selection_keys | set(POSITIVE_GATE_THRESHOLDS)
    else:
        raise PilotError("selection rule shape is invalid")
    if set(selection) != expected_selection_keys:
        raise PilotError("selection rule shape is invalid")
    if (
        isinstance(selection["minimum_trades"], bool)
        or not isinstance(selection["minimum_trades"], int)
        or selection["minimum_trades"] < 1
        or tuple(selection["ranking"]) != RANKING
        or selection["max_selected"] != 1
        or selection["no_eligible"] != "STOP"
        or selection["missing_metric_policy"] != "STOP"
        or selection["visibility"] != "DEVELOPMENT_ONLY_BLIND"
        or selection["candidate_execution_failure"] != "STOP"
    ):
        raise PilotError("selection rule is not the fixed technical Pilot rule")
    if gate == POSITIVE_ECONOMIC_GATE:
        if finite(selection["minimum_profit_pct"], "minimum_profit_pct") <= 0:
            raise PilotError("minimum_profit_pct must exceed 0")
        if finite(selection["minimum_profit_factor"], "minimum_profit_factor") <= 1:
            raise PilotError("minimum_profit_factor must exceed 1")
        maximum_drawdown = finite(
            selection["maximum_drawdown_pct"], "maximum_drawdown_pct", 0
        )
        if maximum_drawdown > 100:
            raise PilotError("maximum_drawdown_pct must not exceed 100")
    if plan["holdout_policy"] != {
        "max_open_count": 1,
        "retry_after_open": False,
        "tune_after_result": False,
    }:
        raise PilotError("Holdout must be one-shot and no-tuning")
    candidates = plan["candidates"]
    if not isinstance(candidates, list) or not 1 <= len(candidates) <= 3:
        raise PilotError("pilot spec must contain one to three Candidates")
    ids, classes = set(), set()
    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, dict) or set(candidate) != {
            "candidate_id",
            "class_name",
            "strategy_file",
            "research_spec_file",
            "strategy_sha256",
            "research_spec_sha256",
        }:
            raise PilotError(f"candidate {index} shape is invalid")
        candidate_id, class_name = candidate["candidate_id"], candidate["class_name"]
        if (
            not isinstance(candidate_id, str)
            or SAFE_ID.fullmatch(candidate_id) is None
            or candidate_id in ids
            or not isinstance(class_name, str)
            or CLASS.fullmatch(class_name) is None
            or class_name in classes
        ):
            raise PilotError(f"candidate {index} identity is invalid")
        ids.add(candidate_id)
        classes.add(class_name)
        strategy = safe_file(root, candidate["strategy_file"], "strategy_file")
        spec = safe_file(root, candidate["research_spec_file"], "research_spec_file")
        if candidate["strategy_sha256"] != digest(strategy.read_bytes()) or candidate[
            "research_spec_sha256"
        ] != digest(spec.read_bytes()):
            raise PilotError(f"candidate {index} frozen hash mismatch")
        causal_source(strategy, class_name)
        spec_value, _ = load_json(spec, "Candidate research spec")
        metadata = spec_value.get("candidate", {}).get("metadata", {})
        if (
            spec_value.get("candidate", {}).get("class_name") != class_name
            or metadata.get("pilot_id") != plan["pilot_id"]
            or metadata.get("economic_evidence") != "NOT_EVALUATED"
            or metadata.get("generation")
            != {
                "source": "CODEX",
                "model": None,
                "returned_strategy_count": len(candidates),
                "source_item_index": index,
            }
            or spec_value.get("profile", {}).get("history_start_date")
            != dev_start.strftime("%Y-%m-%d")
            or spec_value.get("profile", {}).get("holdout_days") != (hold_end - hold_start).days
            or spec_value.get("profile", {}).get("stress_fee_multiplier") != multiplier
        ):
            raise PilotError(f"candidate {index} research spec disagrees with the Pilot")
        candidate["_strategy"] = strategy
        candidate["_spec"] = spec
    plan["_sha256"] = digest(plan_bytes)
    return plan


def _search_series_contract(timeframe: str) -> tuple[dict[str, timedelta], dict[str, str]]:
    if timeframe not in PROFILE_TIMEFRAME_STEPS:
        raise PilotError("Search timeframe must be 5m or 1d")
    base = f"futures_{timeframe}"
    return (
        {base: PROFILE_TIMEFRAME_STEPS[timeframe], "mark_1h": timedelta(hours=1), "funding_history": timedelta(hours=8)},
        {base: f"-{timeframe}-futures.feather", "mark_1h": "-1h-mark.feather", "funding_history": "-1h-funding_rate.feather"},
    )


def _search_window_contract(
    value: Any, *, timeframe: str, pre_roll_candles: int
) -> dict[str, Any]:
    window = _profile_window_contract(
        value,
        phase="Search",
        timeframe=timeframe,
        pre_roll_candles=pre_roll_candles,
    )
    return {
        "startup_start": window["startup_start"],
        "search_start": window["phase_start"],
        "search_stop": window["phase_stop"],
        "starts": window["starts"],
        "rows": window["rows"],
    }


def _development_window_contract(
    value: Any, *, timeframe: str, pre_roll_candles: int
) -> dict[str, Any]:
    window = _profile_window_contract(
        value,
        phase="Development",
        timeframe=timeframe,
        pre_roll_candles=pre_roll_candles,
    )
    return {
        "startup_start": window["startup_start"],
        "development_start": window["phase_start"],
        "development_stop": window["phase_stop"],
        "starts": window["starts"],
        "rows": window["rows"],
    }


def _profile_window_contract(
    value: Any,
    *,
    phase: str,
    timeframe: str,
    pre_roll_candles: int,
) -> dict[str, Any]:
    phase_start, phase_stop = timerange(value, phase)
    duration = phase_stop - phase_start
    if not timedelta(days=1) <= duration <= timedelta(days=366):
        raise PilotError(f"{phase} window exceeds its bounded duration")
    steps, _ = _search_series_contract(timeframe)
    startup_start = (
        phase_start - PROFILE_TIMEFRAME_STEPS[timeframe] * pre_roll_candles
    )
    mark_start = startup_start.replace(minute=0, second=0, microsecond=0)
    starts = {
        f"futures_{timeframe}": startup_start,
        "mark_1h": mark_start,
        "funding_history": phase_start,
    }
    rows: dict[str, int] = {}
    for series, step in steps.items():
        duration = phase_stop - starts[series]
        if duration % step:
            label = "Search-only" if phase == "Search" else phase
            raise PilotError(f"{label} {series} boundaries do not align")
        rows[series] = duration // step
    return {
        "startup_start": startup_start,
        "phase_start": phase_start,
        "phase_stop": phase_stop,
        "starts": starts,
        "rows": rows,
    }


def _search_sha256(value: Any, label: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise PilotError(f"{label} must be a lowercase SHA-256")
    return value


def _verify_search_receipt(
    data_root: Path,
    name: str,
    value: Any,
    label: str,
    *,
    expected_rows: Optional[int] = None,
) -> Path:
    expected_fields = {"bytes", "sha256"}
    if expected_rows is not None:
        expected_fields.add("rows")
    if not isinstance(value, dict) or set(value) != expected_fields:
        raise PilotError(f"{label} shape is invalid")
    size = value.get("bytes")
    if isinstance(size, bool) or not isinstance(size, int) or size < 0:
        raise PilotError(f"{label} bytes is invalid")
    expected_sha = _search_sha256(value.get("sha256"), f"{label} sha256")
    if expected_rows is not None:
        rows = value.get("rows")
        if isinstance(rows, bool) or not isinstance(rows, int) or rows != expected_rows:
            raise PilotError(f"{label} rows disagree with the Search window")
    path = safe_file(data_root, name, label)
    data = path.read_bytes()
    if len(data) != size or digest(data) != expected_sha:
        raise PilotError(f"{label} receipt mismatch")
    return path


def _search_data_names(pair: Any, timeframe: str) -> dict[str, str]:
    if not isinstance(pair, str):
        raise PilotError("Search source pair is invalid")
    match = re.fullmatch(
        r"([A-Za-z0-9-]+)/([A-Za-z0-9-]+):([A-Za-z0-9-]+)", pair
    )
    if match is None or match.group(2) != match.group(3):
        raise PilotError("Search source pair is invalid")
    stem = "_".join(match.groups())
    _, suffixes = _search_series_contract(timeframe)
    return {
        series: f"futures/{stem}{suffix}"
        for series, suffix in suffixes.items()
    }


def _verify_search_data(
    data_root: Path,
    provenance: Mapping[str, Any],
    provenance_bytes: bytes,
    plan: Mapping[str, Any],
) -> dict[str, Any]:
    profile = validate_profile_search_contract(plan)
    source = provenance.get("source")
    freqtrade = provenance.get("freqtrade")
    contract = provenance.get("contract")
    if not isinstance(source, dict) or not isinstance(freqtrade, dict) or not isinstance(contract, dict):
        raise PilotError("Search data provenance is incomplete")
    expected_contract = {
        "data_dir": "data/okx",
        "market_snapshot": "market_snapshot.json",
        "leverage_tiers": "isolated_tiers_snapshot.json",
        "config": "config.json",
        "search_timerange": plan["search_timerange"],
        "timeframe": profile["timeframe"],
        "profile_snapshot": plan["profile_snapshot"],
        "profile_snapshot_sha256": plan["profile_snapshot_sha256"],
        "development_timerange": plan["development_timerange"],
        "pre_roll_candles": plan["pre_roll_candles"],
        "capacity": plan["capacity"],
        "finalist_gate": plan["finalist_gate"],
        "holdout": plan["holdout"],
        "holdout_stress": plan["holdout_stress"],
    }
    if "economic_gate" in plan:
        expected_contract["economic_gate"] = validate_profile_economic_gate(
            plan["economic_gate"]
        )
    if "exploration" in plan:
        expected_contract["exploration"] = validate_exploration(plan["exploration"])
    if (
        digest(provenance_bytes) != plan["data_provenance_sha256"]
        or provenance.get("schema") != SEARCH_DATA_SCHEMA
        or source.get("host") != "www.okx.com"
        or source.get("authentication") != "none"
        or freqtrade.get("version") != "2026.7"
        or freqtrade.get("tag") != "2026.7"
        or freqtrade.get("commit") != "52bc96f4480b1a0da6a9b455bd00b17fbb6786a5"
        or freqtrade.get("dependencies") != RUNNER_DEPENDENCIES
        or contract != expected_contract
    ):
        raise PilotError("data provenance disagrees with the Search-only contract")

    timeframe = expected_contract["timeframe"]
    pre_roll = plan["pre_roll_candles"]
    window = _search_window_contract(
        plan["search_timerange"],
        timeframe=timeframe,
        pre_roll_candles=pre_roll,
    )
    expected_rows = window["rows"]
    pair = source.get("pair")
    instrument_id = source.get("instrument_id")
    if not isinstance(instrument_id, str) or not instrument_id:
        raise PilotError("Search source instrument identity is invalid")
    if pair != profile["pair"]:
        raise PilotError("Search source pair disagrees with the Profile")
    data_names = _search_data_names(pair, timeframe)

    source_acquisition = provenance.get("source_acquisition")
    if not isinstance(source_acquisition, dict) or set(source_acquisition) != {
        "provenance_sha256",
        "retrieval_receipt_sha256",
        "data_sha256",
    }:
        raise PilotError("Search source_acquisition shape is invalid")
    _search_sha256(
        source_acquisition.get("provenance_sha256"),
        "Search source provenance_sha256",
    )
    _search_sha256(
        source_acquisition.get("retrieval_receipt_sha256"),
        "Search source retrieval_receipt_sha256",
    )
    source_data_sha256 = source_acquisition.get("data_sha256")
    if not isinstance(source_data_sha256, dict) or set(source_data_sha256) != set(
        data_names.values()
    ):
        raise PilotError("Search source data_sha256 must bind exactly three series")
    for name, value in source_data_sha256.items():
        _search_sha256(value, f"Search source data_sha256 {name!r}")

    retention = provenance.get("search_retention")
    if not isinstance(retention, dict) or set(retention) != {
        "startup_start_utc",
        "search_start_utc",
        "end_exclusive_utc",
        "later_rows_exposed_to_search",
        "rows",
    }:
        raise PilotError("Search retention shape is invalid")
    retention_rows = retention.get("rows")
    if (
        retention.get("startup_start_utc")
        != window["startup_start"].isoformat().replace("+00:00", "Z")
        or retention.get("search_start_utc")
        != window["search_start"].isoformat().replace("+00:00", "Z")
        or retention.get("end_exclusive_utc")
        != window["search_stop"].isoformat().replace("+00:00", "Z")
        or retention.get("later_rows_exposed_to_search") is not False
        or not isinstance(retention_rows, dict)
        or set(retention_rows) != set(expected_rows)
        or any(
            isinstance(retention_rows.get(series), bool)
            or not isinstance(retention_rows.get(series), int)
            or retention_rows[series] != rows
            for series, rows in expected_rows.items()
        )
    ):
        raise PilotError("Search retention disagrees with the Search window")

    local = provenance.get("local_only_files")
    expected_local_names = {
        *(f"data/okx/{name}" for name in data_names.values()),
        contract["market_snapshot"],
        contract["leverage_tiers"],
    }
    if not isinstance(local, dict) or set(local) != expected_local_names:
        raise PilotError("Search local_only_files must bind exact data and controls")
    for series, name in data_names.items():
        _verify_search_receipt(
            data_root,
            f"data/okx/{name}",
            local[f"data/okx/{name}"],
            f"Search {series} data",
            expected_rows=expected_rows[series],
        )
    for name in (contract["market_snapshot"], contract["leverage_tiers"]):
        _verify_search_receipt(
            data_root, name, local[name], f"Search control {name!r}"
        )

    market_data_root = data_root / contract["data_dir"]
    if market_data_root.is_symlink() or not market_data_root.is_dir():
        raise PilotError("Search market data directory is unsafe")
    actual_data_names: set[str] = set()
    try:
        for path in market_data_root.rglob("*"):
            if path.is_symlink():
                raise PilotError("Search market data directory contains a symlink")
            if path.is_file():
                actual_data_names.add(path.relative_to(market_data_root).as_posix())
    except OSError as exc:
        raise PilotError("Search market data directory cannot be inspected") from exc
    if actual_data_names != set(data_names.values()):
        raise PilotError("Search market data file set is not exact")

    tracked = provenance.get("files")
    if not isinstance(tracked, dict) or set(tracked) != {contract["config"]}:
        raise PilotError("Search provenance must bind only its config file")
    config_path = _verify_search_receipt(
        data_root,
        contract["config"],
        tracked[contract["config"]],
        "Search config",
    )
    config, _ = load_json(config_path, "Search config")
    configured_strategy = config.get("strategy")
    if configured_strategy is not None and (
        not isinstance(configured_strategy, str)
        or CLASS.fullmatch(configured_strategy) is None
    ):
        raise PilotError("Search config strategy is invalid")
    fee, pairs = profile["fee"], (profile["pair"],)
    if (
        pairs != (pair,)
        or config.get("timeframe") != contract["timeframe"]
        or config != profile_search_config(plan["profile_snapshot"])
    ):
        raise PilotError("Search config/profile contract mismatch")

    market, _ = load_json(
        data_root / contract["market_snapshot"], "Search market snapshot"
    )
    if market.get("id") != instrument_id or market.get("symbol") != pair:
        raise PilotError("Search market identity disagrees with its SHA-bound snapshot")

    actual_rows = _verify_search_output_dates(
        market_data_root,
        data_names,
        plan["search_timerange"],
        timeframe=timeframe,
        pre_roll_candles=pre_roll,
    )
    if actual_rows != expected_rows:
        raise PilotError("Search market data rows disagree with provenance")
    return {
        "status": "DATA_READY",
        "source": {
            "host": source["host"],
            "authentication": "none",
            "pair": pair,
        },
        "rows": expected_rows,
        "provenance_sha256": digest(provenance_bytes),
        "local_files": len(local),
        "search_timerange": plan["search_timerange"],
        "timeframe": contract["timeframe"],
        "base_fee": fee,
    }


def verify_data(root: Path, plan: Mapping[str, Any]) -> dict[str, Any]:
    data_root = root / ACQUISITION
    provenance, provenance_bytes = load_json(
        data_root / "retained-data-provenance.json", "data provenance"
    )
    source = provenance.get("source", {})
    ft = provenance.get("freqtrade", {})
    contract = provenance.get("contract", {})
    search_only = plan.get("schema") == SEARCH_SCHEMA
    if search_only:
        return _verify_search_data(data_root, provenance, provenance_bytes, plan)
    elif (
        provenance.get("schema") != "freqtrade-lab-retained-okx-data-v1"
        or source.get("host") != "www.okx.com"
        or source.get("authentication") != "none"
        or ft.get("version") != "2026.7"
        or ft.get("commit") != "52bc96f4480b1a0da6a9b455bd00b17fbb6786a5"
        or contract.get("timeframe") != "5m"
        or contract.get("development_timerange") != plan["development_timerange"]
        or contract.get("holdout_timerange") != plan["holdout_timerange"]
    ):
        raise PilotError("data provenance disagrees with the public fixed Pilot contract")
    local = provenance.get("local_only_files")
    if not isinstance(local, dict) or not local:
        raise PilotError("data provenance has no local files")
    for name, receipt in local.items():
        path = safe_file(data_root, name, "local data file")
        data = path.read_bytes()
        if not isinstance(receipt, dict) or receipt.get("bytes") != len(data) or receipt.get("sha256") != digest(data):
            raise PilotError(f"local data receipt mismatch: {name}")
    receipt_name = source.get("retrieval_receipt")
    receipt, receipt_bytes = load_json(
        safe_file(data_root, receipt_name, "retrieval receipt"), "retrieval receipt"
    )
    rows = {
        name: receipt.get("series", {}).get(name, {}).get("rows")
        for name in ("futures_5m", "mark_1h", "funding_history")
    }
    if any(isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in rows.values()):
        raise PilotError("retrieval receipt has an empty series")
    result = {
        "status": "DATA_READY",
        "source": {"host": source["host"], "authentication": "none", "pair": source.get("pair")},
        "rows": rows,
        "retrieval_receipt_sha256": digest(receipt_bytes),
        "provenance_sha256": digest(provenance_bytes),
        "local_files": len(local),
    }
    result["timeranges"] = [
        plan["development_timerange"],
        plan["holdout_timerange"],
    ]
    return result


def _source_timestamp(value: Any, label: str) -> datetime:
    if not isinstance(value, str):
        raise PilotError(f"{label} is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PilotError(f"{label} is invalid") from exc
    if parsed.utcoffset() != timedelta(0):
        raise PilotError(f"{label} must be UTC")
    return parsed.astimezone(timezone.utc)


def _load_search_source(
    source_root: Path,
    trusted_provenance_sha256: str,
    trusted_receipt_sha256: str,
    *,
    profile_contract: Mapping[str, Any],
) -> dict[str, Any]:
    """Adapt one hash-trusted, runner-verified acquisition into Search."""
    profile = validate_profile_search_contract(profile_contract)
    pair = str(profile["pair"])
    timeframe = str(profile["timeframe"])
    search_timerange = str(profile_contract["search_timerange"])
    development_timerange = profile_contract["development_timerange"]
    pre_roll_candles = profile_contract["pre_roll_candles"]
    source_window = _search_window_contract(
        search_timerange,
        timeframe=timeframe,
        pre_roll_candles=pre_roll_candles,
    )
    if "exploration" in profile_contract:
        development_start = development_stop = source_window["search_stop"]
    else:
        development_start, development_stop = timerange(development_timerange, "Development")
    expected_acquisition = {
        key: profile_contract[key]
        for key in _profile_acquisition_contract_fields(profile_contract)
    }
    expected_config = profile_search_config(profile_contract["profile_snapshot"])
    if any(
        re.fullmatch(r"[0-9a-f]{64}", value) is None
        for value in (trusted_provenance_sha256, trusted_receipt_sha256)
    ):
        raise PilotError("trusted source SHA-256 values are invalid")
    provenance, provenance_bytes = load_json(
        source_root / "retained-data-provenance.json", "source provenance"
    )
    if digest(provenance_bytes) != trusted_provenance_sha256:
        raise PilotError("source provenance trusted SHA mismatch")
    source = provenance.get("source", {})
    contract = provenance.get("contract", {})
    files = provenance.get("files", {})
    if (
        not isinstance(source, dict)
        or not isinstance(contract, dict)
        or not isinstance(files, dict)
        or "retrievals" in source
        or source.get("retrieval_receipt") != "retrieval_receipt.json"
        or source.get("pair") != pair
        or not isinstance(source.get("instrument_id"), str)
        or not source["instrument_id"]
        or contract.get("data_dir") != "data/okx"
        or contract.get("market_snapshot") != "market_snapshot.json"
        or contract.get("leverage_tiers") != "isolated_tiers_snapshot.json"
        or contract.get("config") != "config.json"
        or contract.get("development_timerange") != search_timerange
        or contract.get("holdout_timerange") != development_timerange
        or contract.get("timeframe") != timeframe
        or contract.get("profile_acquisition") != expected_acquisition
        or source_window["search_stop"] != development_start
    ):
        raise PilotError("source must be one complete singular Profile acquisition")
    receipt_name = source["retrieval_receipt"]
    data_dir = source_root / "data" / "okx"
    if (
        (source_root / "data").is_symlink()
        or data_dir.is_symlink()
        or not data_dir.is_dir()
    ):
        raise PilotError("source data directory must stay inside the acquisition")
    receipt_path = safe_file(source_root, receipt_name, "source retrieval receipt")
    receipt, receipt_bytes = load_json(receipt_path, "source retrieval receipt")
    config_path = safe_file(source_root, contract.get("config"), "source config")
    expected_files = {
        contract["config"]: "profile_bound_search_config",
        receipt_name: "local_public_retrieval_receipt",
        "producer/fetch_okx_profile_data.py": "profile_acquisition_and_validation",
        "producer/historical_fetch_okx_public_data.py": (
            "historical_transport_dependency"
        ),
    }
    if set(files) != set(expected_files):
        raise PilotError("source Profile producer receipts are incomplete")
    tracked_bytes: dict[str, bytes] = {}
    for name, expected_role in expected_files.items():
        path = safe_file(source_root, name, f"source tracked file {name}")
        data = path.read_bytes()
        tracked_bytes[name] = data
        record = files.get(name)
        if (
            not isinstance(record, dict)
            or set(record) != {"role", "bytes", "sha256"}
            or record.get("role") != expected_role
            or record.get("bytes") != len(data)
            or record.get("sha256") != digest(data)
        ):
            raise PilotError(f"source tracked receipt mismatch: {name}")
    if digest(receipt_bytes) != trusted_receipt_sha256:
        raise PilotError(f"source tracked receipt mismatch: {receipt_name}")
    if (
        digest(tracked_bytes["producer/historical_fetch_okx_public_data.py"])
        != "8a9ad34654693bbada15da4a90caacb380364ea8b747f2d5be193633080d843f"
    ):
        raise PilotError("source historical producer identity is invalid")
    try:
        config = json.loads(tracked_bytes[contract["config"]])
        if not isinstance(config, dict):
            raise ResearchCandidateError("Freqtrade config must be a JSON object")
        configured_strategy = config.get("strategy")
        if configured_strategy is not None and (
            not isinstance(configured_strategy, str)
            or CLASS.fullmatch(configured_strategy) is None
        ):
            raise ResearchCandidateError("config strategy is invalid")
        if config != expected_config:
            raise ResearchCandidateError(
                "config must bind the frozen Search Profile"
            )
    except (UnicodeError, json.JSONDecodeError, ResearchCandidateError) as exc:
        raise PilotError(str(exc)) from exc
    try:
        _verify_dependency_versions(provenance, RUNNER_DEPENDENCIES)
        verified = _verify_data_provenance(
            provenance,
            scenario="DEVELOPMENT",
            timerange=search_timerange,
            pair=pair,
            data_dir=data_dir,
            market_snapshot=source_root / contract["market_snapshot"],
            leverage_tiers=source_root / contract["leverage_tiers"],
            timeframe=timeframe,
        )
    except OfflineBacktestError as exc:
        raise PilotError(str(exc)) from exc
    control_bytes = {"config.json": tracked_bytes[contract["config"]]}
    for name, receipt_key in (
        ("market_snapshot.json", "market_snapshot_sha256"),
        ("isolated_tiers_snapshot.json", "leverage_tiers_sha256"),
    ):
        data = (source_root / name).read_bytes()
        if digest(data) != verified[receipt_key]:
            raise PilotError(f"source {name} changed after provenance validation")
        control_bytes[name] = data
    data_names = _search_data_names(pair, timeframe)
    if (
        set(verified["data_sha256"]) != set(data_names.values())
    ):
        raise PilotError("source acquisition must contain the exact Search data series")
    market, _ = load_json(
        source_root / contract["market_snapshot"], "source market snapshot"
    )
    window = receipt.get("data_window")
    if (
        not isinstance(window, dict)
        or window.get("fully_closed_at_fetch") is not True
        or receipt.get("host") != "www.okx.com"
        or receipt.get("authentication") != "none"
        or receipt.get("pair") != pair
        or receipt.get("instrument_id") != source["instrument_id"]
        or market.get("symbol") != pair
        or market.get("id") != source["instrument_id"]
    ):
        raise PilotError("source retrieval identity/completeness receipt mismatch")
    source_start = _source_timestamp(window.get("start_utc"), "source start")
    source_stop = _source_timestamp(window.get("end_exclusive_utc"), "source stop")
    receipt_development_start = _source_timestamp(
        window.get("development_start_utc"), "source Development start"
    )
    receipt_holdout_start = _source_timestamp(
        window.get("holdout_start_utc"), "source Holdout start"
    )
    startup_candles = window.get("startup_candles_required")
    if (
        source_start != source_window["startup_start"]
        or source_stop != development_stop
        or receipt_development_start != source_window["search_start"]
        or receipt_holdout_start != source_window["search_stop"]
        or isinstance(startup_candles, bool)
        or not isinstance(startup_candles, int)
        or startup_candles != pre_roll_candles
    ):
        raise PilotError("source acquisition window does not bind the frozen Profile")
    return {
        "provenance_sha256": trusted_provenance_sha256,
        "receipt_sha256": trusted_receipt_sha256,
        "source": {
            key: source.get(key)
            for key in ("host", "authentication", "pair", "instrument_id", "pair_family")
        },
        "freqtrade": {
            "version": provenance["freqtrade"]["version"],
            "tag": provenance["freqtrade"]["tag"],
            "commit": provenance["freqtrade"]["commit"],
            "dependencies": dict(RUNNER_DEPENDENCIES),
        },
        "data_names": data_names,
        "data_sha256": verified["data_sha256"],
        "controls": control_bytes,
    }


def _verify_search_output_dates(
    data_root: Path,
    data_names: Mapping[str, str],
    search_timerange: str,
    *,
    timeframe: str,
    pre_roll_candles: int,
) -> dict[str, int]:
    return _verify_profile_output_dates(
        data_root,
        data_names,
        search_timerange,
        phase="Search",
        timeframe=timeframe,
        pre_roll_candles=pre_roll_candles,
    )


def _verify_profile_output_dates(
    data_root: Path,
    data_names: Mapping[str, str],
    phase_timerange: str,
    *,
    phase: str,
    timeframe: str,
    pre_roll_candles: int,
) -> dict[str, int]:
    try:
        import pyarrow
        import pyarrow.compute as pc
        import pyarrow.feather as feather
    except (ImportError, ModuleNotFoundError) as exc:
        raise PilotError("exact PyArrow 25.0.0 is required") from exc
    if pyarrow.__version__ != RUNNER_DEPENDENCIES["pyarrow"]:
        raise PilotError("exact PyArrow 25.0.0 is required")
    steps, _ = _search_series_contract(timeframe)
    label = "Search-only" if phase == "Search" else phase
    if set(data_names) != set(steps) or len(set(data_names.values())) != 3:
        raise PilotError(f"{label} output must contain exactly three series")
    window = _profile_window_contract(
        phase_timerange,
        phase=phase,
        timeframe=timeframe,
        pre_roll_candles=pre_roll_candles,
    )
    expected_columns = ("date", "open", "high", "low", "close", "volume")
    for series, relative_name in data_names.items():
        try:
            table = feather.read_table(data_root / relative_name)
            if tuple(table.column_names) != expected_columns:
                raise PilotError(
                    f"{label} {series} does not have the exact Freqtrade OHLCV schema"
                )
            dates = table.column("date")
            if dates.null_count:
                raise PilotError(f"{label} {series} timestamps contain nulls")
            for column_name in expected_columns[1:]:
                column = table.column(column_name)
                if not pyarrow.types.is_floating(column.type):
                    raise PilotError(
                        f"{label} {series} {column_name} values are invalid"
                    )
                if series == "mark_1h" and column_name == "volume":
                    valid_values = pc.fill_null(pc.is_finite(column), True)
                elif column.null_count:
                    raise PilotError(
                        f"{label} {series} {column_name} values are invalid"
                    )
                else:
                    valid_values = pc.is_finite(column)
                if not pc.all(valid_values).as_py():
                    raise PilotError(
                        f"{label} {series} {column_name} values are invalid"
                    )
            raw_values = dates.to_pylist()
        except PilotError:
            raise
        except Exception as exc:
            raise PilotError(
                f"{label} {series} is not a readable Feather series"
            ) from exc
        if any(
            not isinstance(item, datetime) or item.utcoffset() != timedelta(0)
            for item in raw_values
        ):
            raise PilotError(f"{label} {series} timestamps are not UTC")
        values = [item.astimezone(timezone.utc) for item in raw_values]
        start = window["starts"][series]
        stop = window["phase_stop"]
        step = steps[series]
        if (
            len(values) != window["rows"][series]
            or not values
            or values[0] != start
            or values[-1] + step != stop
            or any(item >= stop for item in values)
            or any(right - left != step for left, right in zip(values, values[1:]))
        ):
            raise PilotError(f"{label} {series} output is not contiguous")
    return dict(window["rows"])


def prepare_search_data(
    source_root: Path,
    output_root: Path,
    trusted_provenance_sha256: str,
    trusted_receipt_sha256: str,
    *,
    database_path: Path,
    profile_id: str,
    search_timerange: str,
    development_timerange: Optional[str],
    pre_roll_candles: int,
    economic_gate: Optional[Mapping[str, Any]] = None,
    exploration: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """Publish a fresh root containing only one verified Search acquisition."""
    raw_source = source_root.expanduser()
    if raw_source.is_symlink():
        raise PilotError("source acquisition root must not be a symlink")
    source = raw_source.resolve(strict=True)
    expanded_output = output_root.expanduser()
    if expanded_output.name in {"", ".", ".."}:
        raise PilotError("Search output root must name one new directory")
    output_parent = expanded_output.parent.resolve(strict=True)
    output = output_parent / expanded_output.name
    try:
        output.relative_to(ROOT.resolve(strict=True))
    except ValueError:
        pass
    else:
        raise PilotError("Search output root must stay outside Git")
    current = output_parent
    while True:
        if (current / ".git").exists() or (current / ".git").is_symlink():
            raise PilotError("Search output root must stay outside every Git worktree")
        if current.parent == current:
            break
        current = current.parent
    if output.exists() or output.is_symlink():
        raise PilotError("Search output root already exists; replay is forbidden")
    if source == output_parent or source in output.parents or output in source.parents:
        raise PilotError("source and Search output roots must be independent")
    acquisition_contract = profile_acquisition_contract(
        database_path,
        profile_id,
        search_timerange,
        development_timerange,
        pre_roll_candles,
        economic_gate,
        exploration,
    )
    data_contract = {
        key: acquisition_contract[key]
        for key in _profile_acquisition_contract_fields(acquisition_contract)
    }
    profile = validate_profile_search_contract(data_contract)
    timeframe = str(profile["timeframe"])
    pre_roll = int(pre_roll_candles)
    source_contract = data_contract
    if exploration is not None:
        source_document, source_bytes = load_json(source / "retained-data-provenance.json", "source provenance")
        if digest(source_bytes) != trusted_provenance_sha256:
            raise PilotError("source provenance trusted SHA mismatch")
        source_contract = source_document.get("contract", {}).get("profile_acquisition")
        if not isinstance(source_contract, dict) or "exploration" not in source_contract:
            raise PilotError("Shared source requires two exploratory contracts")
    frozen = _load_search_source(
        source,
        trusted_provenance_sha256,
        trusted_receipt_sha256,
        profile_contract=source_contract,
    )
    if exploration is not None:
        # The original source/config has already passed its own complete verification.
        source_profile = source_contract["profile_snapshot"]
        allowed = {"id", "name", "created_at", "updated_at", "starting_balance", "stake_amount",
                   "min_development_trades", "min_holdout_trades"}
        if (any(source_profile[key] != data_contract["profile_snapshot"][key]
                for key in PROFILE_SNAPSHOT_FIELDS - allowed)
                or source_contract != profile_search_contract(
                    source_profile, search_timerange, development_timerange, pre_roll,
                    economic_gate, exploration)):
            raise PilotError("Shared exploratory source differs outside the Profile identity/capital/sample whitelist")
        # Source originals and their trusted SHA links remain intact; only this consumer gets its config.
        frozen["controls"]["config.json"] = canonical(profile_search_config(data_contract["profile_snapshot"]))
    window = _search_window_contract(search_timerange, timeframe=timeframe, pre_roll_candles=pre_roll)
    staging = Path(tempfile.mkdtemp(prefix=".search-data-", dir=output_parent))
    staging.chmod(0o700)
    published = False
    try:
        acquisition = staging / ACQUISITION
        data_root = acquisition / "data" / "okx"
        data_root.mkdir(parents=True)
        expected = {
            name: frozen["data_sha256"][name]
            for name in frozen["data_names"].values()
        }
        view = _create_scenario_data_view(
            source / "data" / "okx",
            data_root,
            search_timerange,
            expected,
            timeframe=timeframe,
            lower_bounds={
                frozen["data_names"][series]: start
                for series, start in window["starts"].items()
            },
        )
        for data_path in data_root.rglob("*.feather"):
            data_path.chmod(0o400)
        for name, data in frozen["controls"].items():
            (acquisition / name).write_bytes(data)
        local_files = {
            f"data/okx/{name}": {
                "bytes": (data_root / name).stat().st_size,
                "sha256": view["files"][name]["sha256"],
                "rows": window["rows"][series],
            }
            for series, name in frozen["data_names"].items()
        }
        for name in ("market_snapshot.json", "isolated_tiers_snapshot.json"):
            data = frozen["controls"][name]
            local_files[name] = {"bytes": len(data), "sha256": digest(data)}
        contract = {
            "data_dir": "data/okx", "market_snapshot": "market_snapshot.json",
            "leverage_tiers": "isolated_tiers_snapshot.json", "config": "config.json",
            "search_timerange": search_timerange, "timeframe": timeframe,
            **data_contract,
        }
        provenance = {
            "schema": SEARCH_DATA_SCHEMA,
            "portable_retained_fixture": False,
            "source": frozen["source"],
            "freqtrade": frozen["freqtrade"],
            "contract": contract,
            "source_acquisition": {
                "provenance_sha256": frozen["provenance_sha256"],
                "retrieval_receipt_sha256": frozen["receipt_sha256"],
                "data_sha256": frozen["data_sha256"],
            },
            "search_retention": {
                "startup_start_utc": window["startup_start"].isoformat().replace("+00:00", "Z"),
                "search_start_utc": window["search_start"].isoformat().replace("+00:00", "Z"),
                "end_exclusive_utc": window["search_stop"].isoformat().replace("+00:00", "Z"),
                "later_rows_exposed_to_search": False,
                "rows": window["rows"],
            },
            "files": {
                "config.json": {
                    "bytes": len(frozen["controls"]["config.json"]),
                    "sha256": digest(frozen["controls"]["config.json"]),
                }
            },
            "local_only_files": local_files,
        }
        (acquisition / "retained-data-provenance.json").write_bytes(canonical(provenance))
        provenance_bytes = (acquisition / "retained-data-provenance.json").read_bytes()
        _verify_search_data(
            acquisition,
            provenance,
            provenance_bytes,
            {
                **data_contract,
                "data_provenance_sha256": digest(provenance_bytes),
            },
        )
        if output.exists() or output.is_symlink():
            raise PilotError("Search output root already exists; replay is forbidden")
        try:
            _publish_directory_exclusive(staging, output)
        except ResearchCandidateError as exc:
            raise PilotError(str(exc)) from exc
        published = True
        return {
            "status": "SEARCH_DATA_READY",
            "search_timerange": search_timerange,
            "provenance_sha256": digest(provenance_bytes),
            "rows": window["rows"],
        }
    finally:
        if not published:
            shutil.rmtree(staging, ignore_errors=True)


def _source_acquisition_binding(frozen: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "provenance_sha256": frozen["provenance_sha256"],
        "retrieval_receipt_sha256": frozen["receipt_sha256"],
        "data_sha256": dict(frozen["data_sha256"]),
    }


def _profile_development_selection(profile: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "economic_gate": POSITIVE_ECONOMIC_GATE,
        "minimum_trades": profile["minimum_trades"],
        "minimum_profit_pct": 0.0,
        "minimum_profit_factor": profile["minimum_profit_factor"],
        "maximum_drawdown_pct": profile["maximum_drawdown_pct"],
        "max_selected": 1,
        "visibility": "DEVELOPMENT_ONLY_BLIND",
        "candidate_execution_failure": "STOP",
    }


def _profile_development_contract(
    profile_contract: Mapping[str, Any], timeframe: str
) -> dict[str, Any]:
    contract = {
        "data_dir": "data/okx",
        "market_snapshot": "market_snapshot.json",
        "leverage_tiers": "isolated_tiers_snapshot.json",
        "config": "config.json",
        "timeframe": timeframe,
        "development_timerange": profile_contract["development_timerange"],
        "profile_snapshot": profile_contract["profile_snapshot"],
        "profile_snapshot_sha256": profile_contract["profile_snapshot_sha256"],
        "pre_roll_candles": profile_contract["pre_roll_candles"],
    }
    if "economic_gate" in profile_contract:
        contract["economic_gate"] = validate_profile_economic_gate(
            profile_contract["economic_gate"]
        )
    return contract


def _profile_development_window_spec(
    profile_contract: Mapping[str, Any], profile: Mapping[str, Any]
) -> dict[str, Any]:
    window = _development_window_contract(
        profile_contract["development_timerange"],
        timeframe=profile["timeframe"],
        pre_roll_candles=profile_contract["pre_roll_candles"],
    )
    holdout_stop = window["development_stop"] + timedelta(
        days=int(profile["profile_snapshot"]["holdout_days"])
    )
    return {
        "schema": STRICT_WINDOW_SCHEMA,
        "data_start_utc": window["startup_start"]
        .isoformat()
        .replace("+00:00", "Z"),
        "development_start_utc": window["development_start"]
        .isoformat()
        .replace("+00:00", "Z"),
        "holdout_start_utc": window["development_stop"]
        .isoformat()
        .replace("+00:00", "Z"),
        "end_exclusive_utc": holdout_stop.isoformat().replace("+00:00", "Z"),
    }


def _profile_development_plan(
    profile_contract: Mapping[str, Any],
    profile: Mapping[str, Any],
    source_acquisition: Mapping[str, Any],
    *,
    window_sha256: str,
    acquisition_provenance_sha256: str,
    development_provenance_sha256: str,
) -> dict[str, Any]:
    _, development_stop = timerange(
        profile_contract["development_timerange"], "Development"
    )
    holdout_stop = development_stop + timedelta(
        days=int(profile["profile_snapshot"]["holdout_days"])
    )
    return {
        "schema": PROFILE_DEVELOPMENT_SCHEMA,
        "freqtrade_version": "2026.7",
        "development_timerange": profile_contract["development_timerange"],
        "holdout_timerange": (
            f"{development_stop:%Y%m%d}-{holdout_stop:%Y%m%d}"
        ),
        "window_spec_sha256": window_sha256,
        "acquisition_provenance_sha256": acquisition_provenance_sha256,
        "development_provenance_sha256": development_provenance_sha256,
        "profile_contract": dict(profile_contract),
        "source_acquisition": dict(source_acquisition),
        "selection": _profile_development_selection(profile),
        "candidates": [],
    }


def _profile_development_input_contract(
    database_path: Path,
    profile_id: str,
    search_timerange: str,
    development_timerange: str,
    pre_roll_candles: int,
    economic_gate: Optional[Mapping[str, Any]] = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    acquisition_contract = profile_acquisition_contract(
        database_path,
        profile_id,
        search_timerange,
        development_timerange,
        pre_roll_candles,
        economic_gate,
    )
    profile_contract = {
        key: acquisition_contract[key]
        for key in _profile_acquisition_contract_fields(acquisition_contract)
    }
    profile = validate_profile_search_contract(profile_contract)
    return profile_contract, profile


def _development_receipt(path: Path, *, rows: Optional[int] = None) -> dict[str, Any]:
    data = path.read_bytes()
    result: dict[str, Any] = {"bytes": len(data), "sha256": digest(data)}
    if rows is not None:
        result["rows"] = rows
    return result


def _validate_source_acquisition_binding(
    value: Any, data_names: Mapping[str, str], label: str
) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {
        "provenance_sha256",
        "retrieval_receipt_sha256",
        "data_sha256",
    }:
        raise PilotError(f"{label} source_acquisition shape is invalid")
    _search_sha256(value["provenance_sha256"], f"{label} source provenance")
    _search_sha256(
        value["retrieval_receipt_sha256"], f"{label} source retrieval receipt"
    )
    data_sha256 = value["data_sha256"]
    if not isinstance(data_sha256, dict) or set(data_sha256) != set(
        data_names.values()
    ):
        raise PilotError(f"{label} source data hashes are invalid")
    for name, sha256 in data_sha256.items():
        _search_sha256(sha256, f"{label} source data hash {name!r}")
    return {
        "provenance_sha256": value["provenance_sha256"],
        "retrieval_receipt_sha256": value["retrieval_receipt_sha256"],
        "data_sha256": dict(data_sha256),
    }


def _development_root_entries(root: Path) -> tuple[set[str], set[str]]:
    files: set[str] = set()
    directories: set[str] = set()
    try:
        for path in root.rglob("*"):
            if path.is_symlink():
                raise PilotError("Development pilot root contains a symlink")
            relative = path.relative_to(root).as_posix()
            if path.is_file():
                files.add(relative)
            elif path.is_dir():
                directories.add(relative)
            else:
                raise PilotError("Development pilot root contains an unsafe entry")
    except PilotError:
        raise
    except OSError as exc:
        raise PilotError("Development pilot root cannot be inspected") from exc
    return files, directories


def _canonical_json(path: Path, label: str) -> tuple[dict[str, Any], bytes]:
    value, data = load_json(path, label)
    if data != canonical(value):
        raise PilotError(f"{label} must use canonical JSON")
    return value, data


def check_development_data(root: Path) -> dict[str, Any]:
    """Verify one self-contained Profile Development-only pilot root."""
    raw_root = root.expanduser()
    if raw_root.is_symlink():
        raise PilotError("Development pilot root must not be a symlink")
    try:
        resolved_root = raw_root.resolve(strict=True)
    except OSError as exc:
        raise PilotError("Development pilot root does not exist") from exc
    if not resolved_root.is_dir():
        raise PilotError("Development pilot root must be a directory")

    top_level = {path.name for path in resolved_root.iterdir()}
    if top_level != {PLAN, WINDOW, ACQUISITION, DEVELOPMENT_ISOLATION}:
        raise PilotError("Development pilot root file set is not exact")
    plan, plan_bytes = _canonical_json(resolved_root / PLAN, "Development plan")
    plan_fields = {
        "schema",
        "freqtrade_version",
        "development_timerange",
        "holdout_timerange",
        "window_spec_sha256",
        "acquisition_provenance_sha256",
        "development_provenance_sha256",
        "profile_contract",
        "source_acquisition",
        "selection",
        "candidates",
    }
    profile_contract = plan.get("profile_contract")
    if (
        set(plan) != plan_fields
        or plan.get("schema") != PROFILE_DEVELOPMENT_SCHEMA
        or plan.get("freqtrade_version") != "2026.7"
        or not isinstance(profile_contract, dict)
        or set(profile_contract)
        != set(_profile_acquisition_contract_fields(profile_contract))
        or plan.get("candidates") != []
    ):
        raise PilotError("Development plan shape/version is invalid")
    profile = validate_profile_search_contract(profile_contract)
    timeframe = str(profile["timeframe"])
    data_names = _search_data_names(profile["pair"], timeframe)
    source_acquisition = _validate_source_acquisition_binding(
        plan.get("source_acquisition"), data_names, "Development plan"
    )

    window, window_bytes = _canonical_json(
        resolved_root / WINDOW, "Development window"
    )
    expected_window = _profile_development_window_spec(profile_contract, profile)
    if (
        window != expected_window
        or plan.get("window_spec_sha256") != digest(window_bytes)
    ):
        raise PilotError("Development window disagrees with the Profile")

    acquisition = resolved_root / ACQUISITION
    isolation = resolved_root / DEVELOPMENT_ISOLATION
    acquisition_provenance, acquisition_bytes = _canonical_json(
        acquisition / "retained-data-provenance.json",
        "Development acquisition provenance",
    )
    development_provenance, development_bytes = _canonical_json(
        isolation / "retained-data-provenance.json", "Development provenance"
    )
    if (
        plan.get("acquisition_provenance_sha256") != digest(acquisition_bytes)
        or plan.get("development_provenance_sha256") != digest(development_bytes)
    ):
        raise PilotError("Development provenance hash binding is invalid")

    source = acquisition_provenance.get("source")
    freqtrade = acquisition_provenance.get("freqtrade")
    if (
        not isinstance(source, dict)
        or set(source)
        != {"host", "authentication", "pair", "instrument_id", "pair_family"}
        or source.get("host") != "www.okx.com"
        or source.get("authentication") != "none"
        or source.get("pair") != profile["pair"]
        or not isinstance(source.get("instrument_id"), str)
        or not source["instrument_id"]
        or not isinstance(freqtrade, dict)
        or freqtrade
        != {
            "version": "2026.7",
            "tag": "2026.7",
            "commit": "52bc96f4480b1a0da6a9b455bd00b17fbb6786a5",
            "dependencies": dict(RUNNER_DEPENDENCIES),
        }
    ):
        raise PilotError("Development source identity is invalid")
    if acquisition_provenance.get("source_acquisition") != source_acquisition:
        raise PilotError("Development source acquisition binding changed")

    contract = _profile_development_contract(profile_contract, timeframe)
    config_path = acquisition / "config.json"
    config_receipt = _development_receipt(config_path)
    expected_acquisition_provenance = {
        "schema": PROFILE_DEVELOPMENT_ACQUISITION_SCHEMA,
        "portable_retained_fixture": False,
        "source": source,
        "freqtrade": freqtrade,
        "contract": contract,
        "source_acquisition": source_acquisition,
        "files": {"config.json": config_receipt},
    }
    if acquisition_provenance != expected_acquisition_provenance:
        raise PilotError("Development acquisition provenance is invalid")
    config, _ = load_json(config_path, "Development config")
    if config != profile_search_config(profile_contract["profile_snapshot"]):
        raise PilotError("Development config disagrees with the Profile")

    window_contract = _development_window_contract(
        profile_contract["development_timerange"],
        timeframe=timeframe,
        pre_roll_candles=profile_contract["pre_roll_candles"],
    )
    expected_rows = window_contract["rows"]
    local = development_provenance.get("local_only_files")
    expected_local_names = {
        "market_snapshot.json",
        "isolated_tiers_snapshot.json",
        *(f"data/okx/{name}" for name in data_names.values()),
    }
    if not isinstance(local, dict) or set(local) != expected_local_names:
        raise PilotError("Development input receipt set is not exact")
    for control_name in ("market_snapshot.json", "isolated_tiers_snapshot.json"):
        _verify_search_receipt(
            acquisition,
            control_name,
            local[control_name],
            f"Development control {control_name!r}",
        )
    view_files: dict[str, Any] = {}
    for series, relative_name in data_names.items():
        local_name = f"data/okx/{relative_name}"
        _verify_search_receipt(
            isolation,
            local_name,
            local[local_name],
            f"Development {series} data",
            expected_rows=expected_rows[series],
        )
        view_files[relative_name] = {
            "rows": expected_rows[series],
            "sha256": local[local_name]["sha256"],
        }
    actual_rows = _verify_profile_output_dates(
        isolation / "data" / "okx",
        data_names,
        profile_contract["development_timerange"],
        phase="Development",
        timeframe=timeframe,
        pre_roll_candles=profile_contract["pre_roll_candles"],
    )
    if actual_rows != expected_rows:
        raise PilotError("Development data rows disagree with the Profile")

    market, _ = load_json(
        acquisition / "market_snapshot.json", "Development market snapshot"
    )
    if (
        market.get("id") != source["instrument_id"]
        or market.get("symbol") != source["pair"]
    ):
        raise PilotError("Development market identity is invalid")
    expected_development_provenance = {
        "schema": "freqtrade-lab-retained-okx-data-v1",
        "portable_retained_fixture": False,
        "source": source,
        "freqtrade": freqtrade,
        "contract": contract,
        "source_acquisition": source_acquisition,
        "files": {},
        "local_only_files": local,
        "development_isolation": {
            "kind": "PHYSICAL_EXCLUSIVE_STOP_VIEW",
            "timerange": profile_contract["development_timerange"],
            "exclusive_stop_utc": window_contract["development_stop"]
            .isoformat()
            .replace("+00:00", "Z"),
            "source_provenance_sha256": digest(acquisition_bytes),
            "holdout_values_present": False,
            "files": view_files,
        },
    }
    if development_provenance != expected_development_provenance:
        raise PilotError("Development isolation provenance is invalid")

    expected_plan = _profile_development_plan(
        profile_contract,
        profile,
        source_acquisition,
        window_sha256=digest(window_bytes),
        acquisition_provenance_sha256=digest(acquisition_bytes),
        development_provenance_sha256=digest(development_bytes),
    )
    if plan != expected_plan:
        raise PilotError("Development plan disagrees with its frozen inputs")

    expected_files = {
        PLAN,
        WINDOW,
        f"{ACQUISITION}/config.json",
        f"{ACQUISITION}/market_snapshot.json",
        f"{ACQUISITION}/isolated_tiers_snapshot.json",
        f"{ACQUISITION}/retained-data-provenance.json",
        f"{DEVELOPMENT_ISOLATION}/retained-data-provenance.json",
        *(
            f"{DEVELOPMENT_ISOLATION}/data/okx/{name}"
            for name in data_names.values()
        ),
    }
    expected_directories = {
        ACQUISITION,
        DEVELOPMENT_ISOLATION,
        f"{DEVELOPMENT_ISOLATION}/data",
        f"{DEVELOPMENT_ISOLATION}/data/okx",
        f"{DEVELOPMENT_ISOLATION}/data/okx/futures",
    }
    actual_files, actual_directories = _development_root_entries(resolved_root)
    if actual_files != expected_files or actual_directories != expected_directories:
        raise PilotError("Development pilot root file set is not exact")
    return {
        "status": "DEVELOPMENT_DATA_READY",
        "development_timerange": profile_contract["development_timerange"],
        "timeframe": timeframe,
        "source": {
            "host": source["host"],
            "authentication": source["authentication"],
            "pair": source["pair"],
        },
        "rows": expected_rows,
        "plan_sha256": digest(plan_bytes),
        "provenance_sha256": digest(development_bytes),
        "source_acquisition_sha256": digest(canonical(source_acquisition)),
    }


def prepare_development_data(
    source_root: Path,
    output_root: Path,
    trusted_provenance_sha256: str,
    trusted_receipt_sha256: str,
    *,
    database_path: Path,
    profile_id: str,
    search_timerange: str,
    development_timerange: str,
    pre_roll_candles: int,
    economic_gate: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """Publish one independent Profile Development-only pilot root."""
    raw_source = source_root.expanduser()
    if raw_source.is_symlink():
        raise PilotError("source acquisition root must not be a symlink")
    source = raw_source.resolve(strict=True)
    expanded_output = output_root.expanduser()
    if expanded_output.name in {"", ".", ".."}:
        raise PilotError("Development output root must name one new directory")
    output_parent = expanded_output.parent.resolve(strict=True)
    output = output_parent / expanded_output.name
    try:
        output.relative_to(ROOT.resolve(strict=True))
    except ValueError:
        pass
    else:
        raise PilotError("Development output root must stay outside Git")
    current = output_parent
    while True:
        if (current / ".git").exists() or (current / ".git").is_symlink():
            raise PilotError(
                "Development output root must stay outside every Git worktree"
            )
        if current.parent == current:
            break
        current = current.parent
    if output.exists() or output.is_symlink():
        raise PilotError("Development output root already exists; replay is forbidden")
    if source == output_parent or source in output.parents or output in source.parents:
        raise PilotError("source and Development output roots must be independent")

    profile_contract, profile = _profile_development_input_contract(
        database_path,
        profile_id,
        search_timerange,
        development_timerange,
        pre_roll_candles,
        economic_gate,
    )
    timeframe = str(profile["timeframe"])
    frozen = _load_search_source(
        source,
        trusted_provenance_sha256,
        trusted_receipt_sha256,
        profile_contract=profile_contract,
    )
    source_acquisition = _source_acquisition_binding(frozen)
    window_contract = _development_window_contract(
        development_timerange,
        timeframe=timeframe,
        pre_roll_candles=pre_roll_candles,
    )
    staging = Path(tempfile.mkdtemp(prefix=".development-data-", dir=output_parent))
    staging.chmod(0o700)
    published = False
    try:
        acquisition = staging / ACQUISITION
        acquisition.mkdir()
        isolation = staging / DEVELOPMENT_ISOLATION
        data_root = isolation / "data" / "okx"
        data_root.mkdir(parents=True)
        expected = {
            name: frozen["data_sha256"][name]
            for name in frozen["data_names"].values()
        }
        try:
            view = _create_scenario_data_view(
                source / "data" / "okx",
                data_root,
                development_timerange,
                expected,
                timeframe=timeframe,
                lower_bounds={
                    frozen["data_names"][series]: start
                    for series, start in window_contract["starts"].items()
                },
            )
        except OfflineBacktestError as exc:
            raise PilotError(str(exc)) from exc
        for data_path in data_root.rglob("*.feather"):
            data_path.chmod(0o444)
        for name, data in frozen["controls"].items():
            (acquisition / name).write_bytes(data)

        contract = _profile_development_contract(profile_contract, timeframe)
        acquisition_provenance = {
            "schema": PROFILE_DEVELOPMENT_ACQUISITION_SCHEMA,
            "portable_retained_fixture": False,
            "source": frozen["source"],
            "freqtrade": frozen["freqtrade"],
            "contract": contract,
            "source_acquisition": source_acquisition,
            "files": {
                "config.json": _development_receipt(acquisition / "config.json")
            },
        }
        acquisition_bytes = canonical(acquisition_provenance)
        (acquisition / "retained-data-provenance.json").write_bytes(
            acquisition_bytes
        )

        local_files = {
            f"data/okx/{name}": _development_receipt(
                data_root / name, rows=window_contract["rows"][series]
            )
            for series, name in frozen["data_names"].items()
        }
        for name in ("market_snapshot.json", "isolated_tiers_snapshot.json"):
            local_files[name] = _development_receipt(acquisition / name)
        development_provenance = {
            "schema": "freqtrade-lab-retained-okx-data-v1",
            "portable_retained_fixture": False,
            "source": frozen["source"],
            "freqtrade": frozen["freqtrade"],
            "contract": contract,
            "source_acquisition": source_acquisition,
            "files": {},
            "local_only_files": local_files,
            "development_isolation": {
                "kind": "PHYSICAL_EXCLUSIVE_STOP_VIEW",
                "timerange": development_timerange,
                "exclusive_stop_utc": view["exclusive_stop_utc"],
                "source_provenance_sha256": digest(acquisition_bytes),
                "holdout_values_present": False,
                "files": view["files"],
            },
        }
        development_bytes = canonical(development_provenance)
        (isolation / "retained-data-provenance.json").write_bytes(
            development_bytes
        )

        window_bytes = canonical(
            _profile_development_window_spec(profile_contract, profile)
        )
        (staging / WINDOW).write_bytes(window_bytes)
        plan = _profile_development_plan(
            profile_contract,
            profile,
            source_acquisition,
            window_sha256=digest(window_bytes),
            acquisition_provenance_sha256=digest(acquisition_bytes),
            development_provenance_sha256=digest(development_bytes),
        )
        (staging / PLAN).write_bytes(canonical(plan))
        result = check_development_data(staging)
        if output.exists() or output.is_symlink():
            raise PilotError(
                "Development output root already exists; replay is forbidden"
            )
        try:
            _publish_directory_exclusive(staging, output)
        except ResearchCandidateError as exc:
            raise PilotError(str(exc)) from exc
        published = True
        return result
    finally:
        if not published:
            shutil.rmtree(staging, ignore_errors=True)


def _search_feather_rows(path: Path) -> int:
    try:
        import pyarrow.feather as feather

        rows = feather.read_table(path, columns=["date"]).num_rows
    except Exception as exc:
        raise PilotError("Search source row count cannot be verified") from exc
    if isinstance(rows, bool) or not isinstance(rows, int) or rows <= 0:
        raise PilotError("Search source has no rows")
    return rows


def materialize_screening_isolation(
    root: Path,
    plan: Mapping[str, Any],
) -> dict[str, Any]:
    """Create a physical view containing no candle at/after the screen stop."""
    search_only = plan.get("schema") == SEARCH_SCHEMA
    profile = validate_profile_search_plan(plan) if search_only else None
    phase = "Search" if search_only else "Development"
    timerange_key = "search_timerange" if search_only else "development_timerange"
    directory_name = (
        f"search-isolation-round-{plan['round']}"
        if search_only
        else "development-isolation"
    )
    isolation_root = root / directory_name
    if isolation_root.exists():
        raise PilotError(f"{phase} isolation already exists; replay is forbidden")
    data_root = isolation_root / "data" / "okx"
    data_root.mkdir(parents=True)
    provenance, provenance_bytes = load_json(
        root / ACQUISITION / "retained-data-provenance.json", "data provenance"
    )
    if (
        plan.get("schema") == SEARCH_SCHEMA
        and digest(provenance_bytes) != plan["data_provenance_sha256"]
    ):
        raise PilotError("Search data provenance changed after preflight")
    contract = provenance.get("contract", {})
    prefix = contract.get("data_dir")
    local = provenance.get("local_only_files")
    if prefix != "data/okx" or not isinstance(local, dict):
        raise PilotError(f"data provenance cannot build a {phase}-only view")
    expected: dict[str, str] = {}
    for name, receipt in local.items():
        marker = f"{prefix}/"
        if isinstance(name, str) and name.startswith(marker):
            relative = name.removeprefix(marker)
            if not isinstance(receipt, dict) or not isinstance(receipt.get("sha256"), str):
                raise PilotError(f"{phase} source receipt is invalid")
            expected[relative] = receipt["sha256"]
    if not expected:
        raise PilotError(f"{phase} source receipt has no market data")
    source_rows: dict[str, int] = {}
    if search_only:
        for relative in expected:
            actual_rows = _search_feather_rows(
                root / ACQUISITION / "data" / "okx" / relative
            )
            source_rows[relative] = actual_rows
            if actual_rows != local[f"{prefix}/{relative}"].get("rows"):
                raise PilotError("Search source row receipt mismatch")
    if profile is None:
        view = _create_scenario_data_view(
            root / ACQUISITION / "data" / "okx",
            data_root,
            plan[timerange_key],
            expected,
        )
    else:
        view = _create_scenario_data_view(
            root / ACQUISITION / "data" / "okx",
            data_root,
            plan[timerange_key],
            expected,
            timeframe=profile["timeframe"],
        )
    updated_local = dict(local)
    for relative, receipt in view["files"].items():
        path = data_root / relative
        data = path.read_bytes()
        if receipt.get("sha256") != digest(data):
            raise PilotError(f"{phase} isolation receipt disagrees with its file")
        source_receipt = local[f"{prefix}/{relative}"]
        if search_only and receipt.get("rows") != source_rows.get(relative):
            raise PilotError("Search source contains post-window data")
        updated_local[f"{prefix}/{relative}"] = {
            "bytes": len(data),
            "sha256": receipt["sha256"],
        }
    provenance["local_only_files"] = updated_local
    provenance["files"] = {}
    provenance["portable_retained_fixture"] = False
    for path in data_root.rglob("*"):
        if path.is_file():
            path.chmod(0o444)
    for path in sorted(
        (item for item in data_root.rglob("*") if item.is_dir()),
        key=lambda item: len(item.parts),
        reverse=True,
    ):
        path.chmod(0o555)
    data_root.chmod(0o555)
    receipt_key = f"{phase.lower()}_isolation"
    receipt = {
        "kind": "PHYSICAL_EXCLUSIVE_STOP_VIEW",
        "timerange": plan[timerange_key],
        "exclusive_stop_utc": view["exclusive_stop_utc"],
        "source_provenance_sha256": digest(provenance_bytes),
        "filesystem_mode": "files=0444,directories=0555",
        "files": view["files"],
    }
    if not search_only:
        receipt["holdout_values_present"] = False
    else:
        receipt["outside_search_values_present"] = False
    provenance[receipt_key] = receipt
    provenance_path = isolation_root / "retained-data-provenance.json"
    provenance_path.write_bytes(canonical(provenance))
    return {
        "data_dir": data_root,
        "provenance": provenance_path,
        "receipt": receipt,
    }


def materialize_development_isolation(
    root: Path, plan: Mapping[str, Any]
) -> dict[str, Any]:
    return materialize_screening_isolation(root, plan)


def materialize_inputs(
    root: Path,
    plan: Mapping[str, Any],
) -> dict[str, Path]:
    directory_name = (
        f"search-inputs-round-{plan['round']}"
        if plan.get("schema") == SEARCH_SCHEMA
        else "candidate-inputs"
    )
    inputs_root = root / directory_name
    if inputs_root.exists():
        raise PilotError("candidate inputs already exist; replay is forbidden")
    search_config_receipt: Optional[Mapping[str, Any]] = None
    if plan.get("schema") == SEARCH_SCHEMA:
        provenance, provenance_bytes = load_json(
            root / ACQUISITION / "retained-data-provenance.json",
            "data provenance",
        )
        tracked = provenance.get("files")
        search_config_receipt = (
            tracked.get("config.json") if isinstance(tracked, dict) else None
        )
        if (
            digest(provenance_bytes) != plan["data_provenance_sha256"]
            or not isinstance(search_config_receipt, Mapping)
        ):
            raise PilotError("Search config provenance changed after preflight")
    inputs_root.mkdir()
    result = {}
    try:
        for candidate in plan["candidates"]:
            destination = inputs_root / candidate["candidate_id"]
            destination.mkdir()
            strategies = destination / "strategies"
            strategies.mkdir()
            strategy = strategies / candidate["_strategy"].name
            shutil.copyfile(candidate["_strategy"], strategy)
            if "_spec" in candidate:
                shutil.copyfile(candidate["_spec"], destination / "research-spec.json")
            for name in ("config.json", "market_snapshot.json", "isolated_tiers_snapshot.json"):
                shutil.copyfile(root / ACQUISITION / name, destination / name)
            config_bytes = (destination / "config.json").read_bytes()
            if search_config_receipt is not None and (
                search_config_receipt.get("bytes") != len(config_bytes)
                or search_config_receipt.get("sha256") != digest(config_bytes)
            ):
                raise PilotError("Search config changed after preflight")
            config, _ = load_json(destination / "config.json", "config")
            config["strategy"] = candidate["class_name"]
            (destination / "config.json").write_bytes(canonical(config))
            verify_candidate_copy(candidate, destination, "Candidate controls")
            result[candidate["candidate_id"]] = destination
    except BaseException:
        shutil.rmtree(inputs_root, ignore_errors=True)
        raise
    return result


def verify_candidate_copy(
    candidate: Mapping[str, Any], root: Path, label: str
) -> None:
    strategy = root / "strategies" / candidate["_strategy"].name
    expected_files = [(strategy, candidate["strategy_sha256"], "strategy")]
    if "_spec" in candidate:
        expected_files.append(
            (
                root / "research-spec.json",
                candidate["research_spec_sha256"],
                "research spec",
            )
        )
    for path, expected, kind in expected_files:
        if path.is_symlink() or not path.is_file() or digest(path.read_bytes()) != expected:
            raise PilotError(f"{label} {kind} changed after the frozen plan was loaded")


def materialize_selected_input(
    root: Path, candidate: Mapping[str, Any], controls: Path
) -> Path:
    destination = root / "selected-input"
    if destination.exists():
        raise PilotError("selected input already exists; replay is forbidden")
    shutil.copytree(root / ACQUISITION, destination)
    strategies = destination / "strategies"
    for child in strategies.iterdir():
        child.unlink()
    strategy = strategies / candidate["_strategy"].name
    shutil.copyfile(controls / "strategies" / candidate["_strategy"].name, strategy)
    shutil.copyfile(controls / "research-spec.json", destination / "research-spec.json")
    shutil.copyfile(controls / "config.json", destination / "config.json")
    provenance, _ = load_json(
        destination / "retained-data-provenance.json", "selected provenance"
    )
    provenance["contract"]["strategy"] = f"strategies/{strategy.name}"
    files = {
        name: value
        for name, value in provenance["files"].items()
        if name not in {"config.json", "research-spec.json", "UPSTREAM_LICENSE.txt"}
        and not name.startswith("strategies/")
    }
    for name, path, role in (
        ("config.json", destination / "config.json", "sanitized_freqtrade_config"),
        (
            "research-spec.json",
            destination / "research-spec.json",
            "user_selected_local_research_spec",
        ),
        (
            f"strategies/{strategy.name}",
            strategy,
            "user_selected_local_candidate_strategy",
        ),
    ):
        data = path.read_bytes()
        files[name] = {"role": role, "bytes": len(data), "sha256": digest(data)}
    provenance["files"] = files
    license_path = destination / "UPSTREAM_LICENSE.txt"
    if license_path.exists():
        license_path.unlink()
    (destination / "retained-data-provenance.json").write_bytes(canonical(provenance))
    verify_candidate_copy(candidate, destination, "selected input")
    strategy.chmod(0o444)
    (destination / "research-spec.json").chmod(0o444)
    return destination


def _market_state_from_values(
    dates: Sequence[datetime],
    closes: Sequence[float],
    trades: Sequence[Mapping[str, Any]],
    lookback: int,
) -> Optional[float]:
    if not trades:
        return None
    if dates != sorted(dates) or len(set(dates)) != len(dates):
        raise PilotError("Search market-state candles are not strictly ordered")
    states = {"UP": 0, "DOWN": 0, "FLAT": 0}
    for trade in trades:
        opened = _source_timestamp(trade.get("open_date"), "Search trade open_date")
        index = bisect_left(dates, opened) - 1
        first = index - lookback + 1
        if first < 0:
            raise PilotError("Search market-state lookback is unavailable")
        current = closes[index]
        average = sum(closes[first : index + 1]) / lookback
        states[
            "UP" if current > average else "DOWN" if current < average else "FLAT"
        ] += 1
    return max(states.values()) / len(trades)


def _market_state_concentration(
    data_path: Path, trades: Sequence[Mapping[str, Any]], lookback: int
) -> Optional[float]:
    if not trades:
        return None
    try:
        import pyarrow.feather as feather

        table = feather.read_table(data_path, columns=["date", "close"])
        dates: list[datetime] = []
        closes: list[float] = []
        for raw_date, raw_close in zip(
            table.column("date").to_pylist(),
            table.column("close").to_pylist(),
            strict=True,
        ):
            if (
                not isinstance(raw_date, datetime)
                or raw_date.tzinfo is None
                or raw_date.utcoffset() != timedelta(0)
            ):
                raise PilotError("Search market-state candle date must be UTC")
            dates.append(raw_date.astimezone(timezone.utc))
            closes.append(finite(raw_close, "Search market-state close", 0))
        return _market_state_from_values(dates, closes, trades, lookback)
    except PilotError:
        raise
    except Exception as exc:
        raise PilotError("Search market-state concentration cannot be computed") from exc


def verify_profile_artifact_config(
    profile_snapshot: Mapping[str, Any], exported_config: Any
) -> dict[str, Any]:
    """Verify the runtime identity echoed inside a Freqtrade result ZIP."""
    profile = validate_profile_runtime_contract(profile_snapshot)
    expected = profile_search_config(profile["profile_snapshot"])
    message = "Freqtrade artifact config disagrees with frozen Profile"
    if not isinstance(exported_config, Mapping) or not isinstance(exported_config.get("exchange"), Mapping):
        raise PilotError("Freqtrade artifact config disagrees with frozen Profile")
    try:
        actual = {
            "exchange": exported_config["exchange"].get("name"),
            "pair": exported_config["exchange"].get("pair_whitelist"),
            "trading_mode": exported_config.get("trading_mode"),
            "margin_mode": exported_config.get("margin_mode"),
            "timeframe": exported_config.get("timeframe"),
            "dry_run": exported_config.get("dry_run"),
            "stake_currency": exported_config.get("stake_currency"),
            "tradable_balance_ratio": finite(
                exported_config.get("tradable_balance_ratio"), "artifact tradable_balance_ratio", 0
            ),
            "fee": finite(exported_config.get("fee"), "artifact fee", 0),
            "starting_balance": finite(exported_config.get("dry_run_wallet"), "artifact dry_run_wallet", 0),
            "stake_amount": finite(exported_config.get("stake_amount"), "artifact stake_amount", 0),
            "max_open_trades": exported_config.get("max_open_trades"),
        }
    except PilotError as exc:
        raise PilotError(message) from exc
    exact = {
        "exchange": expected["exchange"]["name"], "pair": expected["exchange"]["pair_whitelist"],
        "trading_mode": expected["trading_mode"], "margin_mode": expected["margin_mode"],
        "timeframe": expected["timeframe"], "dry_run": expected["dry_run"],
        "stake_currency": expected["stake_currency"],
    }
    if (any(actual[key] != value for key, value in exact.items())
            or actual["dry_run"] is not True
            or isinstance(actual["max_open_trades"], bool) or not isinstance(actual["max_open_trades"], int)
            or actual["max_open_trades"] != profile["max_open_trades"]
            or any(not math.isclose(actual[key], profile[key], rel_tol=0.0, abs_tol=tolerance)
                   for key, tolerance in (("fee", 1e-15), ("starting_balance", 1e-12), ("stake_amount", 1e-12)))
            or not math.isclose(actual["tradable_balance_ratio"], expected["tradable_balance_ratio"],
                                rel_tol=0.0, abs_tol=1e-15)):
        raise PilotError(message)
    return {**actual, "pair": profile["pair"]}


def report_metrics(
    raw: Path,
    archive_name: str,
    class_name: str,
    phase: str = "Development",
    configured_fee: Optional[float] = None,
    market_data: Optional[Path] = None,
    market_state_lookback: Optional[int] = None,
    profile_snapshot: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    archive_path = raw / archive_name
    try:
        if market_data is not None and (
            isinstance(market_state_lookback, bool)
            or not isinstance(market_state_lookback, int)
            or market_state_lookback <= 0
        ):
            raise PilotError("Search market-state lookback is invalid")
        with zipfile.ZipFile(archive_path) as archive:
            names = archive.namelist()
            reports = [
                name
                for name in names
                if name.endswith(".json") and not name.endswith("_config.json")
            ]
            configs = [name for name in names if name.endswith("_config.json")]
            if len(reports) != 1:
                raise PilotError(f"{phase} archive has no unique report")
            if phase == "Search":
                if profile_snapshot is None or len(configs) != 1:
                    raise PilotError(
                        "Search archive has no unique Profile-bound config"
                    )
                exported_config = json.loads(archive.read(configs[0]))
                configured_fee = float(
                    verify_profile_artifact_config(
                        profile_snapshot, exported_config
                    )["fee"]
                )
            result = json.loads(archive.read(reports[0]))["strategy"][class_name]
        total = result["total_trades"]
        if isinstance(total, bool) or not isinstance(total, int) or total < 0:
            raise PilotError(f"{phase} trade count is invalid")
        semantic_result = dict(result)
        semantic_result.pop("backtest_run_start_ts", None)
        semantic_result.pop("backtest_run_end_ts", None)
        net = finite(result["profit_total"], "profit_total") * 100
        fee_cost: Optional[float] = None
        holding: Optional[float] = None
        roi_exit_count: Optional[int] = None
        direction: Optional[float] = None
        trades = result.get("trades")
        if configured_fee is not None:
            if not isinstance(trades, list) or len(trades) != total:
                raise PilotError(f"{phase} trade detail is incomplete")
            fee_cost = 0.0
            roi_exit_count = 0
            if total:
                balance = finite(result.get("starting_balance"), "starting_balance", 0)
                if balance <= 0:
                    raise PilotError(f"{phase} starting balance is invalid")
                if any(
                    not isinstance(item, dict)
                    or not isinstance(item.get("is_short"), bool)
                    for item in trades
                ):
                    raise PilotError(f"{phase} trade detail is invalid")
                notionals = [
                    (finite(item.get("open_rate"), "open_rate", 0) + finite(item.get("close_rate"), "close_rate", 0))
                    * finite(item.get("amount"), "amount", 0)
                    for item in trades
                ]
                fee_cost = sum(notionals) * configured_fee / balance * 100
                holding = sum(
                    finite(item.get("trade_duration"), "trade_duration", 0)
                    for item in trades
                ) / total
                exit_reasons = [item.get("exit_reason") for item in trades]
                if any(not isinstance(item, str) or not item for item in exit_reasons):
                    raise PilotError(f"{phase} trade exit reason is invalid")
                roi_exit_count = sum(item == "roi" for item in exit_reasons)
                shorts = sum(item.get("is_short") is True for item in trades)
                direction = max(shorts, total - shorts) / total
        return {
            "archive": archive_name,
            "archive_sha256": digest(archive_path.read_bytes()),
            "report_semantic_sha256": digest(canonical(semantic_result)),
            "total_trades": total,
            "profit_pct": net,
            "gross_profit_before_fees_pct": None if fee_cost is None else net + fee_cost,
            "net_profit_after_fees_pct": net,
            "configured_fee_cost_pct": fee_cost,
            "max_drawdown_pct": finite(result["max_drawdown_account"], "drawdown", 0) * 100,
            "profit_factor": finite(result["profit_factor"], "profit_factor", 0),
            "average_holding_period_minutes": holding,
            "roi_exit_count": roi_exit_count,
            "direction_concentration": direction,
            "market_state_concentration": (
                None
                if market_data is None
                else _market_state_concentration(
                    market_data, trades, int(market_state_lookback)
                )
            ),
            "market_state_definition": (
                None if market_data is None else MARKET_STATE_DEFINITION
            ),
            "market_state_lookback_candles": market_state_lookback,
        }
    except PilotError:
        raise
    except (OSError, KeyError, json.JSONDecodeError, zipfile.BadZipFile) as exc:
        raise PilotError(f"{phase} report cannot be read: {exc}") from exc


def _screen_candidate(
    *,
    candidate: Mapping[str, Any],
    input_root: Path,
    isolation: Mapping[str, Any],
    output: Path,
    python: Path,
    snapshot: Path,
    source_sha: str,
    timerange_value: str,
    phase: str,
    market_state_lookback: Optional[int] = None,
    profile_snapshot: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    verify_candidate_copy(candidate, input_root, f"{phase} input")
    run_root = output / candidate["candidate_id"]
    raw, user, home = run_root / "raw", run_root / "user_data", run_root / "home"
    for path in (raw, user, home, home / "tmp"):
        path.mkdir(parents=True, exist_ok=True)
    config, _ = load_json(input_root / "config.json", "Candidate config")
    fee = finite(config["fee"], "fee", 0)
    strategy_root = input_root / "strategies"
    strategy = strategy_root / candidate["_strategy"].name
    screening_provenance = run_root / "retained-data-provenance.json"
    provenance, _ = load_json(
        isolation["provenance"], f"{phase} isolation provenance"
    )
    provenance["contract"]["strategy"] = f"strategies/{strategy.name}"
    files = {
        name: value
        for name, value in provenance["files"].items()
        if not name.startswith("strategies/")
    }
    strategy_bytes = strategy.read_bytes()
    files[f"strategies/{strategy.name}"] = {
        "role": "user_selected_local_candidate_strategy",
        "bytes": len(strategy_bytes),
        "sha256": digest(strategy_bytes),
    }
    provenance["files"] = files
    screening_provenance.write_bytes(canonical(provenance))
    runtime_config = run_root / "config.json"
    runtime_config.write_bytes(
        canonical(
            _runtime_config(
                config,
                config_source=input_root / "config.json",
                data_dir=isolation["data_dir"],
                user_data_dir=user,
                strategy_path=strategy_root,
                strategy=candidate["class_name"],
                timerange=timerange_value,
                fee=fee,
                export_dir=raw,
            )
        )
    )
    completed, summary, _ = _run_scenario(
        scenario=phase.upper(),
        timerange=timerange_value,
        fee=fee,
        python=python,
        source=snapshot,
        source_tree_sha256=source_sha,
        runner_script=DEFAULT_RUNNER,
        runner_sha256=RUNNER_SHA,
        sandbox_exec=DEFAULT_SANDBOX_EXEC,
        config_path=runtime_config,
        data_dir=isolation["data_dir"],
        user_data_dir=user,
        strategy_path=strategy_root,
        strategy_file=strategy,
        strategy_sha256=candidate["strategy_sha256"],
        strategy=candidate["class_name"],
        export_dir=raw,
        market_snapshot=input_root / "market_snapshot.json",
        leverage_tiers=input_root / "isolated_tiers_snapshot.json",
        data_provenance=screening_provenance,
        home=home,
        command_runner=subprocess.run,
        allow_zero_trades=True,
    )
    market_data = None
    if phase == "Search":
        pair = config["exchange"]["pair_whitelist"][0]
        timeframe = config["timeframe"]
        data_names = _search_data_names(pair, timeframe)
        market_data = Path(isolation["data_dir"]) / data_names[f"futures_{timeframe}"]
    metrics = report_metrics(
        raw,
        summary["archive"],
        candidate["class_name"],
        phase,
        configured_fee=fee if phase == "Search" else None,
        market_data=market_data,
        market_state_lookback=market_state_lookback,
        profile_snapshot=profile_snapshot,
    )
    if metrics["total_trades"] != summary["total_trades"]:
        raise PilotError("runner/report trade counts disagree")
    view_key = "scenario_data_view" if phase == "Development" else "search_data_view"
    item = {
        "candidate_id": candidate["candidate_id"],
        "class_name": candidate["class_name"],
        "strategy_sha256": candidate["strategy_sha256"],
        "exit_code": completed.returncode,
        view_key: summary["scenario_data_view"],
        **metrics,
    }
    if phase == "Search":
        item.update(technical_status="VALID", failure_reason=None)
    (run_root / "result.json").write_bytes(canonical(item))
    shutil.rmtree(user)
    shutil.rmtree(home)
    runtime_config.unlink()
    return item


def screen(
    root: Path,
    plan: Mapping[str, Any],
    inputs: Mapping[str, Path],
    python: Path,
    source: Path,
    isolation: Mapping[str, Any],
) -> list[dict[str, Any]]:
    search_only = plan.get("schema") == SEARCH_SCHEMA
    phase = "Search" if search_only else "Development"
    timerange_key = "search_timerange" if search_only else "development_timerange"
    directory_name = (
        f"search-results-round-{plan['round']}" if search_only else "development"
    )
    output = root / directory_name
    if output.exists():
        raise PilotError(f"{phase} outputs already exist; replay is forbidden")
    output.mkdir(parents=True)
    work = Path(tempfile.mkdtemp(prefix=".screen-", dir=root))
    try:
        snapshot = work / "freqtrade-source"
        source_sha = _prepare_freqtrade_source_snapshot(
            source, snapshot, work / "git-home", DEFAULT_SANDBOX_EXEC
        )
        results = []
        for candidate in plan["candidates"]:
            try:
                item = _screen_candidate(
                    candidate=candidate,
                    input_root=inputs[candidate["candidate_id"]],
                    isolation=isolation,
                    output=output,
                    python=python,
                    snapshot=snapshot,
                    source_sha=source_sha,
                    timerange_value=plan[timerange_key],
                    phase=phase,
                    market_state_lookback=(
                        int(plan["pre_roll_candles"]) if search_only else None
                    ),
                    profile_snapshot=(
                        plan["profile_snapshot"] if search_only else None
                    ),
                )
                if search_only:
                    item.update(
                        {"technical_status": "VALID", "failure_reason": None}
                    )
            except Exception as exc:
                if not search_only:
                    raise
                failed_root = output / candidate["candidate_id"]
                shutil.rmtree(failed_root / "user_data", ignore_errors=True)
                shutil.rmtree(failed_root / "home", ignore_errors=True)
                (failed_root / "config.json").unlink(missing_ok=True)
                item = {
                    "candidate_id": candidate["candidate_id"],
                    "class_name": candidate["class_name"],
                    "strategy_sha256": candidate["strategy_sha256"],
                    "technical_status": "FAILED",
                    "failure_reason": " ".join(str(exc).split())[:500],
                }
            results.append(item)
        return results
    finally:
        shutil.rmtree(work, ignore_errors=True)


def write_once(path: Path, value: Mapping[str, Any]) -> None:
    try:
        with path.open("xb") as handle:
            handle.write(canonical(value))
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise PilotError(f"{path.name} already exists; replay is forbidden") from exc


def write_once_atomic(path: Path, value: Mapping[str, Any]) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(canonical(value))
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError as exc:
            raise PilotError(
                f"{path.name} already exists; replay is forbidden"
            ) from exc
        temporary.unlink()
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def select(
    root: Path,
    plan: Mapping[str, Any],
    results: Sequence[Mapping[str, Any]],
    isolation_receipt: Optional[Mapping[str, Any]] = None,
) -> Optional[str]:
    selection = plan["selection"]
    minimum = selection["minimum_trades"]
    gate = selection["economic_gate"]
    if gate == TECHNICAL_ECONOMIC_GATE:
        eligible = [item for item in results if item["total_trades"] >= minimum]
    elif gate == POSITIVE_ECONOMIC_GATE:
        eligible = []
        for item in results:
            total_trades = item["total_trades"]
            if (
                isinstance(total_trades, bool)
                or not isinstance(total_trades, int)
                or total_trades < 0
            ):
                raise PilotError("Development trade count is invalid")
            profit_pct = finite(item["profit_pct"], "Development profit_pct")
            profit_factor = finite(
                item["profit_factor"], "Development profit_factor", 0
            )
            max_drawdown_pct = finite(
                item["max_drawdown_pct"], "Development max_drawdown_pct", 0
            )
            if max_drawdown_pct > 100:
                raise PilotError("Development max_drawdown_pct must not exceed 100")
            if (
                total_trades >= minimum
                and profit_pct >= selection["minimum_profit_pct"]
                and profit_factor >= selection["minimum_profit_factor"]
                and max_drawdown_pct <= selection["maximum_drawdown_pct"]
            ):
                eligible.append(item)
    else:
        raise PilotError("selection economic gate is not supported")
    ranked = sorted(
        eligible,
        key=lambda item: (
            -item["profit_pct"],
            item["max_drawdown_pct"],
            -item["profit_factor"],
            item["candidate_id"],
        ),
    )
    chosen = None if not ranked else ranked[0]["candidate_id"]
    receipt = {
        "schema": SCHEMA,
        "pilot_id": plan["pilot_id"],
        "plan_sha256": plan["_sha256"],
        "development_timerange": plan["development_timerange"],
        "minimum_trades": minimum,
        "ranking": list(RANKING),
        "economic_gate": gate,
        "candidate_results": list(results),
        "eligible_candidate_ids": [item["candidate_id"] for item in ranked],
        "selected_candidate_id": chosen,
        "holdout_read": False,
        "development_isolation": isolation_receipt,
        "created_at_utc": now(),
    }
    if gate == POSITIVE_ECONOMIC_GATE:
        receipt.update({key: selection[key] for key in POSITIVE_GATE_THRESHOLDS})
    write_once(root / SELECTION, receipt)
    return chosen


def _search_identity(candidate: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "candidate_id": candidate["candidate_id"],
        "class_name": candidate["class_name"],
        "mechanism": candidate["mechanism"],
        "strategy_sha256": candidate["strategy_sha256"],
    }


def _open_search_ledger(path: Path, *, create: bool = True) -> Any:
    descriptor = -1
    flags = os.O_CLOEXEC | os.O_NOFOLLOW
    flags |= os.O_RDWR | os.O_APPEND | os.O_CREAT if create else os.O_RDONLY
    try:
        descriptor = os.open(path, flags, 0o600)
        opened = os.fstat(descriptor)
        current = os.stat(path, follow_symlinks=False)
        if (
            not stat.S_ISREG(opened.st_mode)
            or not stat.S_ISREG(current.st_mode)
            or (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino)
        ):
            raise OSError("ledger identity mismatch")
        handle = os.fdopen(descriptor, "a+b" if create else "rb")
        descriptor = -1
        return handle
    except OSError as exc:
        raise PilotError("Search trial ledger cannot be opened safely") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _load_search_records(handle: Any, campaign_id: str) -> list[dict[str, Any]]:
    handle.seek(0)
    data = handle.read(2 * 1024 * 1024 + 1)
    if len(data) > 2 * 1024 * 1024:
        raise PilotError("Search trial ledger is too large")
    if data and not data.endswith(b"\n"):
        raise PilotError("Search trial ledger has a partial record")
    records = []
    for index, line in enumerate(data.splitlines(keepends=True), start=1):
        try:
            record = json.loads(line)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise PilotError(f"Search trial record {index} is invalid") from exc
        if (
            not isinstance(record, dict)
            or canonical(record) != line
            or record.get("schema") != SEARCH_TRIAL_SCHEMA
            or record.get("campaign_id") != campaign_id
            or record.get("record_type")
            not in {"ROUND_STARTED", "TRIAL", "ROUND_RECEIPT"}
        ):
            raise PilotError(f"Search trial record {index} is invalid")
        records.append(record)
    return records


def _append_search_record(handle: Any, record: Mapping[str, Any]) -> str:
    data = canonical(record)
    handle.seek(0, os.SEEK_END)
    handle.write(data)
    handle.flush()
    os.fsync(handle.fileno())
    return digest(data)


def _sanitize_search_text(value: Any, root: Optional[Path] = None) -> str:
    message = " ".join(str(value).split())[:500]
    for path in (root, ROOT):
        if path is not None:
            message = message.replace(str(path), "<path>")
    message = re.sub(r"(?<![A-Za-z0-9])/(?:[^\s]+)", "<path>", message)
    for token in ("acquisition", "validation", "development", "holdout", "stress"):
        message = re.sub(token, "later-phase", message, flags=re.IGNORECASE)
    return message


def _search_candidate_failure(
    candidate: Mapping[str, Any], reason: str, root: Optional[Path] = None
) -> dict[str, Any]:
    return {
        **_search_identity(candidate),
        "relationship": candidate["relationship"],
        "changed_factor": candidate["changed_factor"],
        "technical_status": "INVALID",
        "failure_reason": _sanitize_search_text(reason, root),
        "search_metrics": None,
    }


def _validate_search_candidates(
    root: Path,
    plan: Mapping[str, Any],
    previous_trials: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    profile = validate_profile_search_plan(plan)
    previous_ids = {item.get("candidate_id") for item in previous_trials}
    previous_classes = {item.get("class_name") for item in previous_trials}
    previous_hashes = {item.get("strategy_sha256") for item in previous_trials}
    seen_mechanisms: set[str] = set()
    valid: list[dict[str, Any]] = []
    failures: dict[str, dict[str, Any]] = {}
    parent = plan["parent"]
    for candidate_value in plan["candidates"]:
        candidate = dict(candidate_value)
        reason: Optional[str] = None
        mechanism = candidate["mechanism"]
        relationship = candidate["relationship"]
        changed_factor = candidate["changed_factor"]
        parent_sha = candidate["parent_strategy_sha256"]
        if not isinstance(mechanism, str) or SAFE_ID.fullmatch(mechanism) is None:
            reason = "mechanism identity is invalid"
        elif candidate["candidate_id"] in previous_ids:
            reason = "duplicate candidate identity"
        elif candidate["class_name"] in previous_classes:
            reason = "duplicate Candidate class"
        elif candidate["strategy_sha256"] in previous_hashes:
            reason = "duplicate strategy SHA-256"
        elif plan["round"] == 1 and mechanism in seen_mechanisms:
            reason = "round 1 mechanism seed is duplicated"
        elif plan["round"] == 1 and (
            relationship != "MECHANISM_SEED"
            or changed_factor is not None
            or parent_sha is not None
        ):
            reason = "round 1 Candidate is not a mechanism seed"
        elif plan["round"] == 2 and (
            relationship != "SINGLE_FACTOR_CHILD"
            or not isinstance(changed_factor, str)
            or re.fullmatch(r"[a-z][a-z0-9_.-]{0,62}", changed_factor) is None
            or parent_sha != parent["strategy_sha256"]
            or mechanism != parent["mechanism"]
            or candidate["strategy_sha256"] == parent["strategy_sha256"]
        ):
            reason = "round 2 Candidate is not a declared single-factor child"
        if reason is None:
            try:
                strategy = safe_file(root, candidate["strategy_file"], "Search strategy")
                if digest(strategy.read_bytes()) != candidate["strategy_sha256"]:
                    raise PilotError("Search strategy frozen hash mismatch")
                analysis = causal_source(
                    strategy,
                    candidate["class_name"],
                    expected_timeframe=profile["timeframe"],
                )
                if {
                    "timeframe": analysis.timeframe,
                    "startup_candle_count": analysis.startup_candle_count,
                    "maximum_lookback": analysis.max_lookback,
                } != plan["strategy_analyses"][candidate["candidate_id"]]:
                    raise PilotError("Profile strategy analysis changed after freeze")
                candidate["_strategy"] = strategy
            except PilotError as exc:
                reason = str(exc).replace(str(root), "<campaign-root>")
        if reason is None:
            valid.append(candidate)
        else:
            failures[candidate["candidate_id"]] = _search_candidate_failure(
                candidate, reason, root
            )
        previous_ids.add(candidate["candidate_id"])
        previous_classes.add(candidate["class_name"])
        previous_hashes.add(candidate["strategy_sha256"])
        if isinstance(mechanism, str):
            seen_mechanisms.add(mechanism)
    return valid, failures


def _search_result(
    root: Path,
    candidate: Mapping[str, Any],
    raw: Mapping[str, Any],
    *,
    round_number: int,
) -> dict[str, Any]:
    if raw.get("technical_status") != "VALID":
        return _search_candidate_failure(
            candidate,
            str(raw.get("failure_reason") or "Search execution failed"),
            root,
        )
    metrics = {
        "total_trades": raw.get("total_trades"),
        "net_profit_after_base_fees_pct": raw.get("profit_pct"),
        "max_drawdown_pct": raw.get("max_drawdown_pct"),
        "profit_factor": raw.get("profit_factor"),
    }
    metrics.update({key: raw.get(key) for key in (
        "gross_profit_before_fees_pct",
        "configured_fee_cost_pct", "average_holding_period_minutes",
        "roi_exit_count",
        "direction_concentration", "market_state_concentration",
        "market_state_definition", "market_state_lookback_candles",
    )})
    _validated_search_metrics(metrics)
    result = {
        **_search_identity(candidate),
        "relationship": candidate["relationship"],
        "changed_factor": candidate["changed_factor"],
        "technical_status": "VALID",
        "failure_reason": None,
        "search_metrics": metrics,
    }
    archive = raw.get("archive")
    archive_sha = raw.get("archive_sha256")
    report_sha = raw.get("report_semantic_sha256")
    if (
        round_number not in {1, 2}
        or not isinstance(archive, str)
        or Path(archive).name != archive
        or any(
            not isinstance(value, str)
            or re.fullmatch(r"[0-9a-f]{64}", value) is None
            for value in (archive_sha, report_sha)
        )
    ):
        raise PilotError("Profile Search artifact evidence is incomplete")
    prefix = Path(f"search-results-round-{round_number}") / candidate["candidate_id"]
    archive_relative = (prefix / "raw" / archive).as_posix()
    result_relative = (prefix / "result.json").as_posix()
    archive_bytes = safe_file(root, archive_relative, "Search result archive").read_bytes()
    result_bytes = safe_file(root, result_relative, "Search result receipt").read_bytes()
    if digest(archive_bytes) != archive_sha or canonical(dict(raw)) != result_bytes:
        raise PilotError("Profile Search artifact evidence changed before receipt")
    result["evidence"] = {
        "archive": {"path": archive_relative, "sha256": archive_sha},
        "result": {"path": result_relative, "sha256": digest(result_bytes)},
        "report_semantic_sha256": report_sha,
    }
    return result


def _validated_search_metrics(value: Any) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise PilotError("Search finalist metrics are invalid")
    trades = value.get("total_trades")
    if isinstance(trades, bool) or not isinstance(trades, int) or trades < 0:
        raise PilotError("Search finalist metrics are invalid")
    def finite_number(item: Any) -> bool:
        return not isinstance(item, bool) and isinstance(item, (int, float)) and math.isfinite(item)
    net, drawdown, profit_factor = (value.get(key) for key in (
        "net_profit_after_base_fees_pct", "max_drawdown_pct", "profit_factor"
    ))
    gross, fee_cost = value.get("gross_profit_before_fees_pct"), value.get("configured_fee_cost_pct")
    holding, direction, market_state = (value.get(key) for key in (
        "average_holding_period_minutes", "direction_concentration", "market_state_concentration"
    ))
    roi_exit_count = value.get("roi_exit_count")
    trade_metrics = (holding, direction, market_state)
    lookback = value.get("market_state_lookback_candles")
    if (not all(finite_number(item) for item in (net, drawdown, profit_factor, gross, fee_cost))
            or not 0 <= drawdown <= 100 or profit_factor < 0 or fee_cost < 0
            or not math.isclose(gross - fee_cost, net, rel_tol=1e-12, abs_tol=1e-12)
            or (trades == 0 and any(item is not None for item in trade_metrics))
            or (trades > 0 and (not all(finite_number(item) for item in trade_metrics)
                               or holding < 0 or not 0 <= direction <= 1 or not 0 <= market_state <= 1))
            or (
                roi_exit_count is not None
                and (
                    isinstance(roi_exit_count, bool)
                    or not isinstance(roi_exit_count, int)
                    or roi_exit_count < 0
                    or roi_exit_count > trades
                )
            )
            or value.get("market_state_definition") != MARKET_STATE_DEFINITION
            or isinstance(lookback, bool) or not isinstance(lookback, int) or lookback <= 0):
        raise PilotError("Search finalist metrics are invalid")
    return value


def _rank_search_results(
    trials: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    valid = [
        dict(item)
        for item in trials
        if item.get("technical_status") == "VALID"
        and isinstance(item.get("search_metrics"), dict)
    ]
    for item in valid:
        _validated_search_metrics(item["search_metrics"])
    return sorted(
        valid,
        key=lambda item: (
            -item["search_metrics"]["net_profit_after_base_fees_pct"],
            item["search_metrics"]["max_drawdown_pct"],
            item["candidate_id"],
            item["attempt_number"],
        ),
    )


def _search_parent(item: Optional[Mapping[str, Any]]) -> Optional[dict[str, Any]]:
    if item is None:
        return None
    return {
        "candidate_id": item["candidate_id"],
        "class_name": item["class_name"],
        "mechanism": item["mechanism"],
        "strategy_sha256": item["strategy_sha256"],
        "search_metrics": item["search_metrics"],
    }


def _search_finalist(
    ranked: Sequence[Mapping[str, Any]],
    gate: Mapping[str, Any],
    economic_gate: Optional[Mapping[str, Any]] = None,
) -> Optional[dict[str, Any]]:
    normalized_economic = (
        None
        if economic_gate is None
        else validate_profile_economic_gate(economic_gate)
    )
    for item in ranked:
        metrics = item["search_metrics"]
        _validated_search_metrics(metrics)
        profile_passed = (
            metrics["total_trades"] >= gate["minimum_trades"]
            and metrics["net_profit_after_base_fees_pct"] > 0
            and metrics["max_drawdown_pct"] <= gate["maximum_drawdown_pct"]
            and metrics["profit_factor"] >= gate["minimum_profit_factor"]
        )
        economic_passed = normalized_economic is None or (
            metrics["net_profit_after_base_fees_pct"]
            >= normalized_economic["minimum_net_profit_after_base_fees_pct"]
            and metrics["average_holding_period_minutes"] is not None
            and metrics["average_holding_period_minutes"]
            >= normalized_economic["minimum_average_holding_period_minutes"]
            and metrics["roi_exit_count"] is not None
            and metrics["roi_exit_count"]
            <= normalized_economic["maximum_roi_exit_count"]
        )
        if profile_passed and economic_passed:
            return _search_parent(item)
    return None


def _search_round_outcome(
    plan: Mapping[str, Any],
    trials: Sequence[Mapping[str, Any]],
    current_results: Sequence[Mapping[str, Any]],
    consumed_before: int,
) -> tuple[dict[str, Any], str, Optional[dict[str, Any]]]:
    validate_profile_search_plan(plan)
    active_limit = plan["active_attempt_limit"]
    consumed = consumed_before + len(current_results)
    ranked = _rank_search_results(trials)
    selected_parent = _search_parent(ranked[0] if ranked else None)
    finalist = (
        _search_finalist(
            ranked,
            plan["finalist_gate"],
            plan.get("economic_gate"),
        )
        if plan["round"] == SEARCH_MAX_ROUNDS
        else None
    )
    budget = {
        "maximum_attempts": SEARCH_MAX_ATTEMPTS,
        "consumed_before_round": consumed_before,
        "consumed_this_round": len(current_results),
        "consumed_total": consumed,
        "remaining": active_limit - consumed,
    }
    budget.update(
        active_attempt_limit=active_limit,
        hard_remaining=SEARCH_MAX_ATTEMPTS - consumed,
    )
    ranking = [
        {
            "candidate_id": item["candidate_id"],
            "strategy_sha256": item["strategy_sha256"],
            "round": item["round"],
            "attempt_number": item["attempt_number"],
        }
        for item in ranked
    ]
    brief = {
        "campaign": {
            "campaign_id": plan["campaign_id"],
            "round": plan["round"],
            "budget": budget,
        },
        "candidates": list(current_results),
        "frozen_ranking": ranking,
        "selected_parent": selected_parent,
    }
    if plan["round"] == 1 and selected_parent is not None:
        status = "SEARCH_ROUND_READY_FOR_CHILDREN"
    elif plan["round"] == 1:
        status = "SEARCH_TERMINATED_NO_PARENT"
    elif finalist is not None:
        status = "SEARCH_FINALIST_FROZEN"
    else:
        status = "SEARCH_TERMINATED_NO_FINALIST"
    return brief, status, finalist


def _remove_search_runtime(path: Path) -> None:
    if not path.exists():
        return
    try:
        for child in path.rglob("*"):
            if child.is_dir() and not child.is_symlink():
                child.chmod(0o700)
        path.chmod(0o700)
        shutil.rmtree(path)
    except OSError as exc:
        raise PilotError(f"Search runtime cleanup failed: {exc}") from exc


def screen_search(
    root: Path,
    plan: dict[str, Any],
    python: Path,
    source: Path,
) -> dict[str, Any]:
    if Path(sys.executable).resolve(strict=True) != python.resolve(strict=True):
        raise PilotError("run Search with the exact --freqtrade-python interpreter")
    if (root / SEARCH_TERMINAL).exists() or (root / SEARCH_TERMINAL).is_symlink():
        raise PilotError("Search terminal receipt already exists; replay is forbidden")
    verify_data(root, plan)
    validate_profile_search_plan(plan)
    ledger_path = root / SEARCH_TRIALS
    with _open_search_ledger(ledger_path) as ledger:
        fcntl.flock(ledger.fileno(), fcntl.LOCK_EX)
        if (root / SEARCH_TERMINAL).exists() or (root / SEARCH_TERMINAL).is_symlink():
            raise PilotError(
                "Search terminal receipt already exists; replay is forbidden"
            )
        records = _load_search_records(ledger, plan["campaign_id"])
        starts = [item for item in records if item["record_type"] == "ROUND_STARTED"]
        trials = [item for item in records if item["record_type"] == "TRIAL"]
        receipts = [
            item for item in records if item["record_type"] == "ROUND_RECEIPT"
        ]
        reserved_numbers = [
            number
            for started in starts
            if isinstance(started.get("attempt_numbers"), list)
            for number in started["attempt_numbers"]
        ]
        trial_numbers = [item.get("attempt_number") for item in trials]
        if reserved_numbers != list(range(1, len(reserved_numbers) + 1)) or any(
            number not in reserved_numbers for number in trial_numbers
        ):
            raise PilotError("Search trial ledger attempt sequence is invalid")
        if plan["round"] == 1:
            if records:
                raise PilotError("Search round 1 already consumed its write-once ledger")
        else:
            if (
                len(starts) != 1
                or starts[0].get("round") != 1
                or len(receipts) != 1
                or receipts[0].get("round") != 1
                or trial_numbers != reserved_numbers
            ):
                raise PilotError("Search round 2 requires one completed round 1 receipt")
            prior_receipt_sha = digest(canonical(receipts[0]))
            if plan["previous_round_receipt_sha256"] != prior_receipt_sha:
                raise PilotError("Search round 2 receipt binding changed")
            receipt_index = records.index(receipts[0])
            prefix_sha = digest(
                b"".join(canonical(item) for item in records[:receipt_index])
            )
            if receipts[0].get("ledger_prefix_sha256") != prefix_sha:
                raise PilotError("Search round 1 trial ledger changed")
            if plan["_contract_sha256"] != receipts[0].get("contract_sha256"):
                raise PilotError("Search contract changed between rounds")
            prior_parent = receipts[0].get("brief", {}).get("selected_parent")
            if (
                not isinstance(prior_parent, Mapping)
                or plan["parent"] != _search_identity(prior_parent)
            ):
                raise PilotError("Search round 2 parent changed after selection")
        active_limit = plan["active_attempt_limit"]
        if len(reserved_numbers) + len(plan["candidates"]) > active_limit:
            raise PilotError(
                f"Search candidate batch exceeds the {active_limit}-attempt active budget"
            )
        attempt_numbers = list(
            range(
                len(reserved_numbers) + 1,
                len(reserved_numbers) + len(plan["candidates"]) + 1,
            )
        )
        started = {
            "schema": SEARCH_TRIAL_SCHEMA,
            "record_type": "ROUND_STARTED",
            "campaign_id": plan["campaign_id"],
            "campaign_sha256": plan["_sha256"],
            "round": plan["round"],
            "attempt_numbers": attempt_numbers,
        }
        _append_search_record(ledger, started)
        records.append(started)
        reserved_numbers.extend(attempt_numbers)
        valid, failures = _validate_search_candidates(root, plan, trials)
        screened: dict[str, Mapping[str, Any]] = {}
        if valid:
            valid_plan = dict(plan)
            valid_plan["candidates"] = valid
            isolation_name = f"search-isolation-round-{plan['round']}"
            inputs_name = f"search-inputs-round-{plan['round']}"
            try:
                isolation = materialize_screening_isolation(
                    root,
                    plan,
                )
                inputs = materialize_inputs(root, valid_plan)
                screened = {
                    item["candidate_id"]: item
                    for item in screen(
                        root,
                        valid_plan,
                        inputs,
                        python,
                        source,
                        isolation,
                    )
                }
            finally:
                _remove_search_runtime(root / inputs_name)
                _remove_search_runtime(root / isolation_name)

        current_results = []
        valid_by_id = {item["candidate_id"]: item for item in valid}
        for number, candidate in zip(
            attempt_numbers, plan["candidates"], strict=True
        ):
            if candidate["candidate_id"] in failures:
                result_value = failures[candidate["candidate_id"]]
            else:
                result_value = _search_result(
                    root,
                    valid_by_id[candidate["candidate_id"]],
                    screened[candidate["candidate_id"]],
                    round_number=int(plan["round"]),
                )
            current_results.append(result_value)
            record = {
                "schema": SEARCH_TRIAL_SCHEMA,
                "record_type": "TRIAL",
                "campaign_id": plan["campaign_id"],
                "round": plan["round"],
                "attempt_number": number,
                **result_value,
            }
            _append_search_record(ledger, record)
            records.append(record)
            trials.append(record)

        brief, status, finalist = _search_round_outcome(
            plan,
            trials,
            current_results,
            len(reserved_numbers) - len(attempt_numbers),
        )
        round_receipt = {
            "schema": SEARCH_TRIAL_SCHEMA,
            "record_type": "ROUND_RECEIPT",
            "campaign_id": plan["campaign_id"],
            "campaign_sha256": plan["_sha256"],
            "contract_sha256": plan["_contract_sha256"],
            "round": plan["round"],
            "status": status,
            "ledger_prefix_sha256": digest(
                b"".join(canonical(item) for item in records)
            ),
            "brief": brief,
            "created_at_utc": now(),
        }
        round_receipt_sha = _append_search_record(ledger, round_receipt)
        records.append(round_receipt)
        terminal_path: Optional[Path] = None
        if plan["round"] == SEARCH_MAX_ROUNDS or brief["selected_parent"] is None:
            ledger.seek(0)
            trials_sha = digest(ledger.read())
            terminal = {
                "schema": SEARCH_TERMINAL_SCHEMA,
                "campaign_id": plan["campaign_id"],
                "campaign_sha256": plan["_sha256"],
                "contract_sha256": plan["_contract_sha256"],
                "round": plan["round"],
                "status": status,
                "finalist_gate": plan["finalist_gate"],
                "search_finalist": finalist,
                "round_receipt_sha256": round_receipt_sha,
                "trials_sha256": trials_sha,
                "brief": brief,
                "created_at_utc": now(),
            }
            if "economic_gate" in plan:
                terminal["economic_gate"] = validate_profile_economic_gate(
                    plan["economic_gate"]
                )
            terminal_path = root / SEARCH_TERMINAL
            write_once_atomic(terminal_path, terminal)
        return {
            "status": status,
            "brief": brief,
            "round_receipt_sha256": round_receipt_sha,
            "terminal": terminal_path,
        }


def database_evidence(database: Path, run_id: str) -> dict[str, Any]:
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        run = connection.execute(
            """
            SELECT rr.status,rr.verdict,c.class_name,c.source_item_index,
                   g.source,g.model,g.returned_strategy_count
            FROM research_runs rr JOIN candidates c ON c.id=rr.candidate_id
            JOIN generation_runs g ON g.id=c.generation_run_id WHERE rr.id=?
            """,
            (run_id,),
        ).fetchone()
        scenarios = connection.execute(
            """
            SELECT scenario,status,total_trades,profit_pct,max_drawdown_pct,
                   profit_factor,scenario_passed FROM backtest_executions
            WHERE research_run_id=? ORDER BY sequence
            """,
            (run_id,),
        ).fetchall()
        releases = connection.execute(
            "SELECT COUNT(*) FROM releases WHERE research_run_id=?", (run_id,)
        ).fetchone()[0]
    finally:
        connection.close()
    if (
        run is None
        or run["status"] != "COMPLETED"
        or run["verdict"] is not None
        or run["source"] != "CODEX"
        or [row["scenario"] for row in scenarios]
        != ["DEVELOPMENT", "HOLDOUT", "HOLDOUT_STRESS"]
        or any(row["status"] != "SUCCEEDED" or row["scenario_passed"] is not None for row in scenarios)
        or releases != 0
    ):
        raise PilotError("database violates the no-verdict three-scenario contract")
    return {
        "research_run_id": run_id,
        "candidate_class_name": run["class_name"],
        "generation_source": run["source"],
        "generation_model": run["model"],
        "returned_strategy_count": run["returned_strategy_count"],
        "source_item_index": run["source_item_index"],
        "status": run["status"],
        "verdict": None,
        "release_count": releases,
        "scenarios": [dict(row) for row in scenarios],
    }


def development_replay_evidence(
    results: Sequence[Mapping[str, Any]],
    chosen: str,
    evidence: Mapping[str, Any],
    produced: Any,
) -> dict[str, Any]:
    screened = next((item for item in results if item["candidate_id"] == chosen), None)
    scenarios = evidence.get("scenarios")
    if screened is None or not isinstance(scenarios, list) or not scenarios:
        raise PilotError("Development replay evidence is incomplete")
    replayed = scenarios[0]
    if replayed.get("scenario") != "DEVELOPMENT":
        raise PilotError("Development replay scenario is missing")
    development_artifact = next(
        (artifact for artifact in produced.artifacts if artifact.scenario == "DEVELOPMENT"),
        None,
    )
    if development_artifact is None:
        raise PilotError("producer Development artifact is missing")
    replay_metrics = report_metrics(
        produced.bundle_root,
        development_artifact.archive,
        evidence["candidate_class_name"],
    )
    provenance_name = (
        development_artifact.archive.removesuffix(".zip") + ".provenance.json"
    )
    replay_provenance, _ = load_json(
        produced.bundle_root / provenance_name, "Development replay provenance"
    )
    replay_view = replay_provenance.get("generation", {}).get("scenario_data_view")
    if replay_view != screened.get("scenario_data_view"):
        raise PilotError("selected Development replay changed its physical data view")
    if (
        replay_metrics["report_semantic_sha256"]
        != screened["report_semantic_sha256"]
    ):
        raise PilotError("selected Development replay changed report semantics")
    comparisons = {
        "total_trades": (screened["total_trades"], replay_metrics["total_trades"]),
        "profit_pct": (screened["profit_pct"], replay_metrics["profit_pct"]),
        "max_drawdown_pct": (
            screened["max_drawdown_pct"],
            replay_metrics["max_drawdown_pct"],
        ),
        "profit_factor": (screened["profit_factor"], replay_metrics["profit_factor"]),
    }
    for label, (before, after) in comparisons.items():
        if label == "total_trades":
            equal = before == after
        else:
            equal = math.isclose(
                finite(before, f"screened {label}"),
                finite(after, f"replayed {label}"),
                rel_tol=0.0,
                abs_tol=1e-12,
            )
        if not equal:
            raise PilotError(f"selected Development replay changed {label}")
        database_value = replayed.get(label)
        if label == "total_trades":
            database_equal = after == database_value
        else:
            database_equal = math.isclose(
                finite(after, f"replayed {label}"),
                finite(database_value, f"database {label}"),
                rel_tol=0.0,
                abs_tol=1e-12,
            )
        if not database_equal:
            raise PilotError(f"Development artifact/database disagree on {label}")
    return {
        "status": "EXACT_REPORT_SEMANTICS_AND_DATA_VIEW_MATCH",
        "screened_archive_sha256": screened["archive_sha256"],
        "screened_report_semantic_sha256": screened["report_semantic_sha256"],
        "producer_report_semantic_sha256": replay_metrics[
            "report_semantic_sha256"
        ],
        "scenario_data_view": replay_view,
        "metrics": {
            label: {"screened": before, "producer_replay": after}
            for label, (before, after) in comparisons.items()
        },
    }


def validate_scenario_open_receipt(
    root: Path,
    plan: Mapping[str, Any],
    candidate: Mapping[str, Any],
    data_provenance_sha256: str,
    scenario: str,
    relative: str,
) -> dict[str, Any]:
    expected_stop = timerange(plan["holdout_timerange"], "Holdout")[1]
    value, data = load_json(root / relative, f"{scenario} open receipt")
    if set(value) != {
        "schema",
        "scenario",
        "timerange",
        "strategy",
        "strategy_sha256",
        "data_provenance_sha256",
        "exclusive_stop_utc",
        "meaning",
        "opened_at_utc",
    } or (
        value["schema"] != "freqtrade-lab-scenario-open-v1"
        or value["scenario"] != scenario
        or value["timerange"] != plan["holdout_timerange"]
        or value["strategy"] != candidate["class_name"]
        or value["strategy_sha256"] != candidate["strategy_sha256"]
        or value["data_provenance_sha256"] != data_provenance_sha256
        or value["exclusive_stop_utc"]
        != expected_stop.isoformat().replace("+00:00", "Z")
        or value["meaning"]
        != (
            "one-shot scenario execution budget was consumed before retained market data "
            "validation began"
        )
        or not isinstance(value["opened_at_utc"], str)
        or not value["opened_at_utc"].endswith("Z")
    ):
        raise PilotError(f"{scenario} open receipt is invalid")
    return {
        "sha256": digest(data),
        "opened_at_utc": value["opened_at_utc"],
    }


def scenario_open_evidence(
    root: Path,
    plan: Mapping[str, Any],
    candidate: Mapping[str, Any],
    data_provenance_sha256: str,
) -> dict[str, Any]:
    receipts = {
        scenario: validate_scenario_open_receipt(
            root,
            plan,
            candidate,
            data_provenance_sha256,
            scenario,
            relative,
        )
        for scenario, relative in (
            ("HOLDOUT", HOLDOUT_SEAL),
            ("HOLDOUT_STRESS", STRESS_SEAL),
        )
    }
    return {
        "holdout_open_count": 1,
        "stress_open_count": 1,
        "receipts": receipts,
    }


def copy_frequi_results(root: Path, chosen: str, produced: Any) -> dict[str, Any]:
    if produced.imported is None:
        raise PilotError("FreqUI copy requires an imported ResearchRun")
    destination = (
        root
        / "frequi"
        / chosen
        / produced.imported.research_run_id
        / "user_data"
        / "backtest_results"
    )
    try:
        destination.mkdir(parents=True)
    except OSError as exc:
        raise PresentationUnavailableError("FreqUI target directory is unavailable") from exc
    copied: list[dict[str, Any]] = []
    for artifact in produced.artifacts:
        archive = produced.bundle_root / artifact.archive
        provenance_name = artifact.archive.removesuffix(".zip") + ".provenance.json"
        provenance, _ = load_json(
            produced.bundle_root / provenance_name, "artifact provenance"
        )
        artifact_receipt = provenance.get("artifact")
        if not isinstance(artifact_receipt, Mapping):
            raise PilotError("FreqUI copy provenance is incomplete")
        metadata_name = artifact_receipt.get("metadata")
        metadata_sha256 = artifact_receipt.get("metadata_sha256")
        if (
            artifact_receipt.get("archive") != artifact.archive
            or artifact_receipt.get("archive_sha256") != artifact.archive_sha256
            or not isinstance(metadata_name, str)
            or Path(metadata_name).name != metadata_name
            or not isinstance(metadata_sha256, str)
        ):
            raise PilotError("FreqUI copy provenance is incomplete")
        metadata = produced.bundle_root / metadata_name
        for source_path, expected_sha in (
            (archive, artifact.archive_sha256),
            (metadata, metadata_sha256),
        ):
            try:
                data = source_path.read_bytes()
            except OSError as exc:
                raise PilotError("FreqUI source cannot be read") from exc
            if digest(data) != expected_sha:
                raise PilotError("FreqUI source changed before copy")
            target = destination / source_path.name
            try:
                if target.is_symlink():
                    raise PresentationUnavailableError("FreqUI target is a symlink")
                with target.open("xb") as handle:
                    handle.write(data)
                if (
                    target.stat().st_nlink != 1
                    or digest(target.read_bytes()) != expected_sha
                ):
                    raise PresentationUnavailableError("FreqUI target identity check failed")
            except PresentationUnavailableError:
                raise
            except OSError as exc:
                raise PresentationUnavailableError("FreqUI target copy is unavailable") from exc
        copied.append(
            {
                "scenario": artifact.scenario,
                "archive": artifact.archive,
                "archive_sha256": artifact.archive_sha256,
                "metadata": metadata_name,
                "metadata_sha256": metadata_sha256,
            }
        )
    if len(copied) != 3:
        raise PilotError("FreqUI source lacks three scenario artifacts")
    try:
        target_count = len(list(destination.iterdir()))
    except OSError as exc:
        raise PresentationUnavailableError("FreqUI target directory is unavailable") from exc
    if target_count != 6:
        raise PresentationUnavailableError("FreqUI target lacks three exact ZIP/meta pairs")
    return {"root": str(destination), "files": copied}


def strategy_library_command(terminal: Mapping[str, Any]) -> str:
    return shlex.join(
        (
            sys.executable,
            str(ROOT / "scripts" / "serve_strategy_library.py"),
            "--database",
            str(terminal["database"]),
            "--artifact-root",
            str(terminal["bundle_root"]),
            "--frequi-base-url",
            str(terminal["frequi_base_url"]),
            "--frequi-results-root",
            str(terminal["frequi_results_root"]),
            "--port",
            str(DEFAULT_PORT),
        )
    )


def run(
    root: Path,
    plan: dict[str, Any],
    python: Path,
    source: Path,
    frequi_base_url: str,
) -> dict[str, Any]:
    url_match = LOOPBACK_URL.fullmatch(frequi_base_url)
    if url_match is None or int(url_match.group(1)) > 65535:
        raise PilotError("FreqUI base URL must be exact numeric loopback HTTP origin")
    if Path(sys.executable).resolve(strict=True) != python.resolve(strict=True):
        raise PilotError("run this Pilot with the exact --freqtrade-python interpreter")
    if any(
        (root / name).exists()
        for name in (
            SELECTION,
            HOLDOUT_AUTHORIZATION,
            HOLDOUT_SEAL,
            STRESS_SEAL,
            TERMINAL,
        )
    ):
        raise PilotError("Pilot receipt already exists; replay is forbidden")
    data = verify_data(root, plan)
    inputs = materialize_inputs(root, plan)
    isolation = materialize_development_isolation(root, plan)
    results = screen(root, plan, inputs, python, source, isolation)
    chosen = select(root, plan, results, isolation["receipt"])
    if chosen is None:
        terminal = {
            "schema": SCHEMA,
            "pilot_id": plan["pilot_id"],
            "plan_sha256": plan["_sha256"],
            "status": "NO_DEVELOPMENT_FINALIST",
            "holdout_opened": False,
            "holdout_open_count": 0,
            "stress_open_count": 0,
            "retry_allowed": False,
            "data": data,
            "development_isolation": isolation["receipt"],
            "created_at_utc": now(),
        }
        write_once(root / TERMINAL, terminal)
        return terminal
    candidate = next(item for item in plan["candidates"] if item["candidate_id"] == chosen)
    workspace = root / "workspace"
    workspace.mkdir()
    database = workspace / "lab.sqlite"
    init_database(database)
    artifacts = workspace / "artifacts"
    artifacts.mkdir()
    opens = root / "scenario-opens"
    opens.mkdir()
    write_once(
        root / HOLDOUT_AUTHORIZATION,
        {
            "schema": SCHEMA,
            "pilot_id": plan["pilot_id"],
            "plan_sha256": plan["_sha256"],
            "selected_candidate_id": chosen,
            "strategy_sha256": candidate["strategy_sha256"],
            "holdout_timerange": plan["holdout_timerange"],
            "holdout_open_count": 0,
            "stress_open_count": 0,
            "retry_after_open": False,
            "tune_after_result": False,
            "meaning": "authorization frozen; no Holdout values have been opened yet",
            "authorized_at_utc": now(),
        },
    )
    input_root = materialize_selected_input(root, candidate, inputs[chosen])
    input_provenance_sha256 = digest(
        (input_root / "retained-data-provenance.json").read_bytes()
    )
    verify_candidate_copy(candidate, input_root, "producer input")
    try:
        produced = run_research_candidate(
            freqtrade_python=python,
            freqtrade_source=source,
            config=input_root / "config.json",
            data_dir=input_root / "data" / "okx",
            strategy_path=input_root / "strategies",
            strategy_file=input_root / "strategies" / candidate["_strategy"].name,
            strategy=candidate["class_name"],
            research_spec=input_root / "research-spec.json",
            data_provenance=input_root / "retained-data-provenance.json",
            market_snapshot=input_root / "market_snapshot.json",
            leverage_tiers=input_root / "isolated_tiers_snapshot.json",
            development_timerange=plan["development_timerange"],
            holdout_timerange=plan["holdout_timerange"],
            stress_fee_multiplier=plan["stress_fee_multiplier"],
            output_dir=artifacts / f"pilot-{plan['pilot_id']}",
            database=database,
            scenario_open_receipts={
                "HOLDOUT": root / HOLDOUT_SEAL,
                "HOLDOUT_STRESS": root / STRESS_SEAL,
            },
        )
    except ResearchCandidateError as exc:
        raise PilotError(f"one-shot existing producer failed: {exc}") from exc
    if produced.imported is None:
        raise PilotError("existing producer did not import a ResearchRun")
    opens_evidence = scenario_open_evidence(
        root, plan, candidate, input_provenance_sha256
    )
    evidence = database_evidence(database, produced.imported.research_run_id)
    replay = development_replay_evidence(results, chosen, evidence, produced)
    frequi_history_visibility: Optional[str] = None
    try:
        validate_strategy_library_database(database)
        frequi = copy_frequi_results(root, chosen, produced)
    except (PresentationUnavailableError, StrategyLibraryError):
        frequi = {"root": None, "files": None}
        frequi_history_visibility = "UNKNOWN"
    terminal = {
        "schema": SCHEMA,
        "pilot_id": plan["pilot_id"],
        "plan_sha256": plan["_sha256"],
        "status": "PILOT_COMPLETED_NO_VERDICT",
        "data": data,
        "development_isolation": isolation["receipt"],
        "development_results": results,
        "development_replay": replay,
        "selected_candidate_id": chosen,
        "selection_basis": plan["selection"],
        **opens_evidence,
        "retry_allowed": False,
        "tuning_after_result": False,
        "manifest_sha256": produced.manifest_sha256,
        "bundle_root": str(produced.bundle_root),
        "database": str(database),
        "database_evidence": evidence,
        "frequi_base_url": frequi_base_url,
        "frequi_results_root": frequi["root"],
        "frequi_copy_receipts": frequi["files"],
        "frequi_history_visibility": frequi_history_visibility,
        "research_claim": "NOT_EVALUATED",
        "trading_claim": "NONE",
        "created_at_utc": now(),
    }
    write_once(root / TERMINAL, terminal)
    return terminal


def failure_open_state(
    root: Path, plan: Optional[Mapping[str, Any]]
) -> dict[str, Any]:
    paths = {
        "HOLDOUT": root / HOLDOUT_SEAL,
        "HOLDOUT_STRESS": root / STRESS_SEAL,
    }
    counts: dict[str, Optional[int]] = {
        scenario: 0 if not path.exists() and not path.is_symlink() else None
        for scenario, path in paths.items()
    }
    if all(value == 0 for value in counts.values()):
        return {
            "holdout_opened": False,
            "holdout_open_count": 0,
            "stress_open_count": 0,
            "open_receipt_integrity": "NOT_OPENED",
        }
    try:
        if plan is None:
            raise PilotError("plan is unavailable")
        selection, _ = load_json(root / SELECTION, "Development selection")
        chosen = selection.get("selected_candidate_id")
        candidate = next(
            item for item in plan["candidates"] if item["candidate_id"] == chosen
        )
        provenance_sha = digest(
            (root / "selected-input" / "retained-data-provenance.json").read_bytes()
        )
        for scenario, relative in (
            ("HOLDOUT", HOLDOUT_SEAL),
            ("HOLDOUT_STRESS", STRESS_SEAL),
        ):
            if paths[scenario].exists() or paths[scenario].is_symlink():
                validate_scenario_open_receipt(
                    root, plan, candidate, provenance_sha, scenario, relative
                )
                counts[scenario] = 1
    except (KeyError, OSError, StopIteration, PilotError, TypeError, ValueError):
        pass
    if counts["HOLDOUT_STRESS"] == 1 and counts["HOLDOUT"] == 0:
        integrity = "CORRUPT_STRESS_WITHOUT_HOLDOUT"
    elif any(value is None for value in counts.values()):
        integrity = "UNKNOWN_INVALID_OR_PARTIAL_RECEIPT"
    else:
        integrity = "VALID_PARTIAL_OR_COMPLETE"
    return {
        "holdout_opened": (
            None if counts["HOLDOUT"] is None else bool(counts["HOLDOUT"])
        ),
        "holdout_open_count": counts["HOLDOUT"],
        "stress_open_count": counts["HOLDOUT_STRESS"],
        "open_receipt_integrity": integrity,
    }


def write_failure(root: Path, plan: Optional[Mapping[str, Any]], error: Exception) -> None:
    if (root / TERMINAL).exists():
        return
    open_state = failure_open_state(root, plan)
    try:
        write_once(
            root / TERMINAL,
            {
                "schema": SCHEMA,
                "pilot_id": None if plan is None else plan.get("pilot_id"),
                "plan_sha256": None if plan is None else plan.get("_sha256"),
                "status": "BLOCKED",
                "error": " ".join(str(error).split())[:1000],
                "holdout_authorized": (root / HOLDOUT_AUTHORIZATION).exists(),
                **open_state,
                "retry_allowed": False,
                "created_at_utc": now(),
            },
        )
    except PilotError:
        pass


def write_search_failure(
    root: Path,
    plan: Optional[Mapping[str, Any]],
    error: Exception,
    *,
    allow_completed_round: bool = False,
) -> None:
    if plan is None or (root / SEARCH_TERMINAL).exists() or (
        root / SEARCH_TERMINAL
    ).is_symlink():
        return
    try:
        with _open_search_ledger(root / SEARCH_TRIALS) as ledger:
            try:
                fcntl.flock(ledger.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return
            if (root / SEARCH_TERMINAL).exists() or (
                root / SEARCH_TERMINAL
            ).is_symlink():
                return
            records = _load_search_records(
                ledger, str(plan.get("campaign_id"))
            )
            if (
                not allow_completed_round
                and plan.get("round") == 1
                and any(
                    item.get("record_type") == "ROUND_RECEIPT"
                    and item.get("round") == 1
                    for item in records
                )
            ):
                return
            ledger.seek(0)
            ledger_bytes = ledger.read()
            write_once_atomic(
                root / SEARCH_TERMINAL,
                {
                    "schema": SEARCH_TERMINAL_SCHEMA,
                    "campaign_id": plan.get("campaign_id"),
                    "campaign_sha256": plan.get("_sha256"),
                    "contract_sha256": plan.get("_contract_sha256"),
                    "round": plan.get("round"),
                    "status": "SEARCH_BLOCKED",
                    "error": _sanitize_search_text(error, root),
                    "trials_sha256": digest(ledger_bytes),
                    "created_at_utc": now(),
                },
            )
    except PilotError:
        pass


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("check-data")
    check.add_argument("--pilot-root", required=True, type=Path)
    execute = commands.add_parser("run")
    execute.add_argument("--pilot-root", required=True, type=Path)
    execute.add_argument("--freqtrade-python", required=True, type=Path)
    execute.add_argument("--freqtrade-source", required=True, type=Path)
    execute.add_argument("--frequi-base-url", required=True)
    search = commands.add_parser(
        "screen-search",
        help="screen one frozen Search round without opening later phases",
    )
    search.add_argument("--campaign-root", required=True, type=Path)
    search.add_argument("--freqtrade-python", required=True, type=Path)
    search.add_argument("--freqtrade-source", required=True, type=Path)
    prepare = commands.add_parser(
        "prepare-search-data",
        help="slice one frozen Search window from a hash-trusted acquisition",
    )
    development = commands.add_parser(
        "prepare-development-data",
        help="slice one frozen Development window into an independent pilot root",
    )
    for command in (prepare, development):
        command.add_argument("--source-root", required=True, type=Path)
        command.add_argument("--source-provenance-sha256", required=True)
        command.add_argument("--source-receipt-sha256", required=True)
        command.add_argument("--database", required=True, type=Path)
        command.add_argument("--profile-id", required=True)
        command.add_argument("--search-timerange", required=True)
        command.add_argument("--development-timerange", required=command is development)
        command.add_argument("--pre-roll-candles", required=True, type=int)
        command.add_argument(
            "--economic-gate",
            type=Path,
            help="pre-result PROFILE_DRIVEN_ECONOMIC_GATE_V1 JSON",
        )
        command.add_argument("--output-root", required=True, type=Path)
    prepare.add_argument("--exploration-contract", type=Path, help="frozen exploration exposure contract; Development stays unknown")
    check_development = commands.add_parser(
        "check-development-data",
        help="verify one independent Profile Development pilot root",
    )
    check_development.add_argument("--pilot-root", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    if args.command in {"prepare-search-data", "prepare-development-data"}:
        try:
            economic_gate = (
                None
                if args.economic_gate is None
                else load_profile_economic_gate(args.economic_gate)
            )
            prepare_data = (
                prepare_search_data
                if args.command == "prepare-search-data"
                else prepare_development_data
            )
            result = prepare_data(
                args.source_root,
                args.output_root,
                args.source_provenance_sha256,
                args.source_receipt_sha256,
                database_path=args.database,
                profile_id=args.profile_id,
                search_timerange=args.search_timerange,
                development_timerange=args.development_timerange,
                pre_roll_candles=args.pre_roll_candles,
                economic_gate=economic_gate,
                **({"exploration": validate_exploration(load_json(args.exploration_contract, "exploration")[0])}
                   if args.command == "prepare-search-data" and args.exploration_contract is not None else {}),
            )
        except PilotError:
            raise
        except Exception as exc:
            raise PilotError(" ".join(str(exc).split()) or type(exc).__name__) from exc
        print(json.dumps(result, ensure_ascii=True, separators=(",", ":"), sort_keys=True))
        return 0
    if args.command == "check-development-data":
        root = args.pilot_root.expanduser().resolve(strict=True)
        try:
            root.relative_to(ROOT.resolve(strict=True))
        except ValueError:
            pass
        else:
            raise PilotError("pilot root must stay outside Git")
        print(
            json.dumps(
                check_development_data(root),
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            )
        )
        return 0
    root_argument = (
        args.campaign_root if args.command == "screen-search" else args.pilot_root
    )
    root = root_argument.expanduser().resolve(strict=True)
    try:
        root.relative_to(ROOT.resolve(strict=True))
    except ValueError:
        pass
    else:
        raise PilotError("pilot root must stay outside Git")
    plan: Optional[dict[str, Any]] = None
    try:
        plan = load_plan(
            root, SEARCH_CAMPAIGN if args.command == "screen-search" else PLAN
        )
        if args.command == "check-data":
            print(json.dumps(verify_data(root, plan), ensure_ascii=False, sort_keys=True))
            return 0
        if args.command == "screen-search":
            outcome = screen_search(
                root,
                plan,
                args.freqtrade_python.expanduser(),
                args.freqtrade_source.expanduser().resolve(strict=True),
            )
            print(f"Search status: {outcome['status']}")
            print(
                json.dumps(
                    outcome["brief"], ensure_ascii=False, separators=(",", ":"), sort_keys=True
                )
            )
            print(f"Round receipt SHA-256: {outcome['round_receipt_sha256']}")
            if outcome["terminal"] is not None:
                print(f"Terminal receipt: {outcome['terminal']}")
            return (
                0
                if outcome["status"]
                in {"SEARCH_ROUND_READY_FOR_CHILDREN", "SEARCH_FINALIST_FROZEN"}
                else 3
            )
        terminal = run(
            root,
            plan,
            args.freqtrade_python.expanduser(),
            args.freqtrade_source.expanduser().resolve(strict=True),
            args.frequi_base_url,
        )
    except Exception as exc:
        if args.command == "run":
            write_failure(root, plan, exc)
        elif args.command == "screen-search":
            write_search_failure(root, plan, exc)
        raise PilotError(str(exc)) from exc
    print(f"Pilot status: {terminal['status']}")
    print(f"Terminal receipt: {root / TERMINAL}")
    if terminal["status"] == "PILOT_COMPLETED_NO_VERDICT":
        print(f"Selected Candidate: {terminal['selected_candidate_id']}")
        print(f"Research run: {terminal['database_evidence']['research_run_id']}")
        if terminal.get("frequi_results_root") is None:
            print(
                "Warning: optional presentation is UNKNOWN",
                file=sys.stderr,
            )
        else:
            print(f"Strategy library command: {strategy_library_command(terminal)}")
            print(f"Strategy library URL: http://127.0.0.1:{DEFAULT_PORT}/")
    return 0 if terminal["status"] == "PILOT_COMPLETED_NO_VERDICT" else 3
