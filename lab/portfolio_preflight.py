"""Thin metadata admission for the fixed BTC/ETH pilot; never executes a job.

The later native adapter must reuse this contract and reserve each returned job
key in the shared append-only ledger before invoking Freqtrade. Metadata alone
is not data provenance, funding completeness, or an execution authorization.
"""
from __future__ import annotations

import calendar
import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path


PROTOCOL_PATH = Path(__file__).resolve().parents[1] / "docs/protocols/btc-eth-portfolio-v1.json"
PROTOCOL_SHA256 = "4e3d107e3d0533bff1f05df6af893aab477cffbf8b9a8317503e0d7480c2de93"
SYMBOLS = ("BTCUSDT", "ETHUSDT")
MAX_JSON_BYTES = 2 * 1024 * 1024


class AdmissionError(ValueError):
    pass


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise AdmissionError("duplicate JSON key")
        result[key] = value
    return result


def read_json(path: Path):
    with path.open("rb") as source:
        raw = source.read(MAX_JSON_BYTES + 1)
    if len(raw) > MAX_JSON_BYTES:
        raise AdmissionError("metadata exceeds size bound")
    try:
        value = json.loads(raw, object_pairs_hook=_unique,
                           parse_constant=lambda _: (_ for _ in ()).throw(AdmissionError("nonfinite JSON")))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise AdmissionError("invalid JSON") from exc
    if not isinstance(value, dict):
        raise AdmissionError("metadata must be an object")
    return value, hashlib.sha256(raw).hexdigest()


def load_protocol(path=PROTOCOL_PATH):
    protocol, digest = read_json(Path(path))
    if digest != PROTOCOL_SHA256:
        raise AdmissionError("protocol differs from reviewed V1 bytes; new version required")
    return protocol


def _keys(value, keys, name):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise AdmissionError(f"invalid {name} fields")


def _day(value):
    if not isinstance(value, str):
        raise AdmissionError("date must be YYYY-MM-DD")
    try:
        result = date.fromisoformat(value)
    except ValueError as exc:
        raise AdmissionError("invalid date") from exc
    if result.isoformat() != value:
        raise AdmissionError("date must be YYYY-MM-DD")
    return result


def _sha(value):
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise AdmissionError("invalid evidence SHA-256")


def _months(day, count):
    month = day.month - 1 + count
    year = day.year + month // 12
    month = month % 12 + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def native_job_plan(protocol):
    """One job is one native invocation containing BOTH pairs, not two calls.

    Eight synthetic proofs and four technical retries share the 96-call cap.
    Cash is analytical and creates no native job. A/B/C are separate account
    simulations; B and C each require one truly shared-wallet native invocation.
    """
    _validate_protocol(protocol)
    prefix = protocol["protocol_id"]
    jobs = []

    def add(role, key):
        jobs.append({"key": f"{prefix}/{key}", "role": role, "native_calls": 1,
                     "symbols": list(SYMBOLS)})

    for n in range(8):
        add("SYNTHETIC", f"synthetic/{n + 1}")
    versions = [f"trend-{n}" for n in protocol["signals"]["trend_lookbacks"]]
    versions += [f"reversal-{n}" for n in protocol["signals"]["reversal_thresholds"]]
    portfolios = ("A-trend", "A-reversal", "B", "C", "market-exposure", "half-risk-B")
    for fold in range(1, 5):
        for version in versions:
            add("TRAINING", f"fold-{fold}/train/{version}")
        for cost in ("base", "stress"):
            for portfolio in portfolios:
                add("VALIDATION", f"fold-{fold}/validate/{cost}/{portfolio}")
    for cost in ("base", "stress"):
        for portfolio in portfolios:
            add("FINAL_DIAGNOSTIC", f"final/{cost}/{portfolio}")
    return jobs


def _validate_protocol(protocol):
    raw = (json.dumps(protocol, indent=2, ensure_ascii=False) + "\n").encode()
    if hashlib.sha256(raw).hexdigest() != PROTOCOL_SHA256:
        raise AdmissionError("protocol differs from reviewed V1 contract")


def check_registry(registry, protocol, now):
    """Validate an explicit curated control snapshot, never infer a permission.

    Old free-form ledger rows require an evidence-backed normalization. Unknown
    restrictions prevent admission even when the proposed pool looks disjoint.
    This checks declarations only; native integration still verifies raw sources.
    """
    _keys(registry, ("schema", "ledger_sha256", "restrictions_complete", "pool",
                     "allowed_seen", "protected"), "registry")
    if registry["schema"] != "portfolio-window-metadata-v1":
        raise AdmissionError("unsupported registry schema")
    _sha(registry["ledger_sha256"])
    if type(registry["restrictions_complete"]) is not bool:
        raise AdmissionError("restrictions_complete must be boolean")
    if not registry["restrictions_complete"]:
        return ["REGISTRY_RESTRICTIONS_UNKNOWN"], []
    _keys(registry["pool"], ("start", "end"), "pool")
    start, end = (_day(registry["pool"][k]) for k in ("start", "end"))
    if start.day != 1 or end != _months(start, 24) or end > now.date():
        return ["POOL_REQUIRES_CLOSED_24_CALENDAR_MONTHS"], []
    warmup = start - timedelta(days=protocol["windows"]["warmup_days"])
    allowed = {symbol: [] for symbol in SYMBOLS}
    reasons = []
    for field in ("allowed_seen", "protected"):
        if not isinstance(registry[field], list) or len(registry[field]) > 1000:
            raise AdmissionError("invalid window list")
        for row in registry[field]:
            _keys(row, ("symbol", "start", "end", "evidence_sha256"), "window")
            _sha(row["evidence_sha256"])
            lo, hi = _day(row["start"]), _day(row["end"])
            if lo >= hi or not isinstance(row["symbol"], str):
                raise AdmissionError("invalid window")
            if field == "protected":
                # '*' means an explicit global restriction. Another asset's
                # protected values are not opened by this two-asset pilot.
                if row["symbol"] in (*SYMBOLS, "*") and lo < end and hi > warmup:
                    reasons.append("PROTECTED_CALENDAR_OVERLAP_INCLUDING_WARMUP")
            elif row["symbol"] not in SYMBOLS:
                raise AdmissionError("allowed_seen must name exact Binance perpetual symbols")
            else:
                allowed[row["symbol"]].append((lo, hi))
    for symbol, intervals in allowed.items():
        covered = warmup
        for lo, hi in sorted(intervals):
            if lo > covered:
                break
            covered = max(covered, hi)
        if covered < end:
            reasons.append(f"{symbol}_ALLOWED_SEEN_COVERAGE_MISSING")
    folds = [{"fold": n + 1, "training_start": _months(start, 3*n).isoformat(),
              "training_end": _months(start, 12+3*n).isoformat(),
              "validation_start": _months(start, 12+3*n).isoformat(),
              "validation_end": _months(start, 15+3*n).isoformat()}
             for n in range(4)]
    return sorted(set(reasons)), folds


def _positive(value):
    if not isinstance(value, str):
        raise AdmissionError("exchange decimal must be a string")
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise AdmissionError("invalid exchange decimal") from exc
    if not result.is_finite() or result <= 0:
        raise AdmissionError("exchange decimal must be finite and positive")
    return result


def check_exchange(snapshot, now):
    _keys(snapshot, ("schema", "observed_at", "source", "response_sha256", "symbols"), "exchange snapshot")
    if snapshot["schema"] != "portfolio-exchange-metadata-v1" or snapshot["source"] != "https://fapi.binance.com/fapi/v1/exchangeInfo":
        raise AdmissionError("exchange snapshot source/schema mismatch")
    _sha(snapshot["response_sha256"])
    try:
        observed = datetime.fromisoformat(snapshot["observed_at"].replace("Z", "+00:00"))
    except (TypeError, ValueError, AttributeError) as exc:
        raise AdmissionError("invalid exchange timestamp") from exc
    if observed.utcoffset() != timedelta(0) or not timedelta(0) <= now-observed <= timedelta(hours=24):
        return ["EXCHANGE_METADATA_STALE_OR_FUTURE"], None
    if not isinstance(snapshot["symbols"], list) or len(snapshot["symbols"]) != 2:
        raise AdmissionError("exchange snapshot requires exactly BTC and ETH")
    identities = {}
    for row in snapshot["symbols"]:
        _keys(row, ("symbol", "status", "contractType", "quoteAsset", "marginAsset",
                    "min_notional", "min_qty", "max_qty", "step_size", "tick_size"), "symbol")
        if row["symbol"] not in SYMBOLS or row["symbol"] in identities:
            raise AdmissionError("exchange symbol identity mismatch")
        if (row["status"], row["contractType"], row["quoteAsset"], row["marginAsset"]) != ("TRADING", "PERPETUAL", "USDT", "USDT"):
            return ["EXCHANGE_CONTRACT_NOT_TRADABLE"], None
        values = {k: _positive(row[k]) for k in ("min_notional", "min_qty", "max_qty", "step_size", "tick_size")}
        if values["min_qty"] > values["max_qty"] or values["step_size"] > values["max_qty"]:
            raise AdmissionError("invalid exchange quantity bounds")
        identities[row["symbol"]] = row
    return [], identities


def preflight(protocol, *, registry=None, exchange=None, now=None):
    _validate_protocol(protocol)
    now = now or datetime.now(timezone.utc)
    reasons, folds = (["REGISTERED_SEEN_TRAINING_POOL_MISSING"], []) if registry is None else check_registry(registry, protocol, now)
    exchange_reasons, identities = (["EXCHANGE_METADATA_MISSING"], None) if exchange is None else check_exchange(exchange, now)
    jobs = native_job_plan(protocol)
    return {"schema": "portfolio-admission-report-v1", "protocol_sha256": PROTOCOL_SHA256,
            "status": "BLOCKED_DATA" if reasons else ("BLOCKED_METADATA" if exchange_reasons else "METADATA_VALIDATED_ONLY"),
            "blockers": reasons + exchange_reasons + ["SHARED_WALLET_NATIVE_INTEGRATION_REQUIRED", "RAW_SOURCE_QC_REQUIRED", "SETTLEMENT_PRECISION_REQUIRED", "PERSISTENT_BUDGET_RESERVATION_REQUIRED"],
            "market_execution_allowed": False, "market_data_ready": False,
            "account_eligibility": "UNKNOWN", "economic_result": None,
            "ledger_snapshot_sha256": registry["ledger_sha256"] if registry else None,
            "folds": folds, "exchange_rules": identities,
            "budget": {"planned_calls": len(jobs), "retry_reserve": 4, "maximum": 96,
                       "calls_executed_by_this_entrypoint": 0, "global_calls_consumed": None},
            "jobs": jobs, "forward_start": None, "forward_state": "AWAITING_FINAL_ECONOMIC_FREEZE"}
