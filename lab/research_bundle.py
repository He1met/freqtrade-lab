"""Atomically assemble one complete three-scenario research bundle.

The bundle is intentionally narrow: one Freqtrade 2026.7 strategy, one derived
OKX futures profile, and exactly Development, Holdout, and Holdout Stress.
Artifact parsing remains the source of all backtest facts and metrics.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
import stat
import uuid
from contextlib import closing
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Tuple, Union
from urllib.parse import quote

from lab.backtest_artifact import (
    SUPPORTED_FREQTRADE_VERSION,
    ArtifactImportError,
    ParsedBacktestArtifact,
    execution_result_values,
    parse_backtest_artifact,
)
from lab.database import get_connection


BUNDLE_SCHEMA = "freqtrade-lab-research-bundle-v1"
BUNDLE_PIPELINE_VERSION = "research-bundle-v1"
BUNDLE_SCENARIOS = ("DEVELOPMENT", "HOLDOUT", "HOLDOUT_STRESS")
MAX_MANIFEST_BYTES = 128 * 1024

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CLASS_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
PathLike = Union[str, Path]


class ResearchBundleImportError(ValueError):
    """Raised when bundle validation or its all-or-nothing import fails."""


@dataclass(frozen=True)
class ProfileSpec:
    name: str
    history_start_date: str
    smoke_days: int
    holdout_days: int
    stress_fee_multiplier: float
    max_drawdown_pct: float
    min_development_trades: int
    min_holdout_trades: int
    min_profit_factor: float


@dataclass(frozen=True)
class GenerationSpec:
    source: str
    model: Optional[str]
    returned_strategy_count: int
    source_item_index: int


@dataclass(frozen=True)
class CandidateSpec:
    display_name: str
    class_name: str
    strategy_family: Optional[str]
    idea: Optional[str]
    expected_failure_mode: Optional[str]
    metadata: Mapping[str, Any]
    generation: GenerationSpec


@dataclass(frozen=True)
class ArtifactSpec:
    scenario: str
    archive: Path
    provenance_sha256: str


@dataclass(frozen=True)
class ValidatedResearchBundle:
    root: Path
    manifest_path: Path
    manifest_sha256: str
    profile: ProfileSpec
    candidate: CandidateSpec
    artifacts: Tuple[Tuple[str, ParsedBacktestArtifact], ...]


@dataclass(frozen=True)
class ImportedResearchBundle:
    profile_id: str
    generation_run_id: str
    candidate_id: str
    research_run_id: str
    execution_ids: Tuple[str, ...]
    profile_reused: bool
    candidate_reused: bool


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def _strict_json(data: bytes, label: str) -> Any:
    def no_duplicate_keys(pairs: Iterable[Tuple[str, Any]]) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ResearchBundleImportError(
                    f"{label}: duplicate JSON key {key!r}"
                )
            result[key] = value
        return result

    def reject_constant(value: str) -> Any:
        raise ResearchBundleImportError(f"{label}: non-finite JSON value {value}")

    try:
        return json.loads(
            data.decode("utf-8", "strict"),
            object_pairs_hook=no_duplicate_keys,
            parse_constant=reject_constant,
        )
    except ResearchBundleImportError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ResearchBundleImportError(f"{label}: invalid UTF-8 JSON: {exc}") from exc


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ResearchBundleImportError(f"{label} must be a JSON object")
    return value


def _exact_keys(
    value: Mapping[str, Any], required: Sequence[str], label: str
) -> None:
    expected = set(required)
    actual = set(value)
    missing = sorted(expected - actual)
    unknown = sorted(actual - expected)
    if missing:
        raise ResearchBundleImportError(
            f"{label} is missing fields: {', '.join(missing)}"
        )
    if unknown:
        raise ResearchBundleImportError(
            f"{label} contains unknown fields: {', '.join(unknown)}"
        )


def _string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ResearchBundleImportError(f"{label} must be a non-empty string")
    return value


def _optional_string(value: Any, label: str) -> Optional[str]:
    if value is None:
        return None
    return _string(value, label)


def _integer(value: Any, label: str, *, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ResearchBundleImportError(
            f"{label} must be an integer greater than or equal to {minimum}"
        )
    return value


def _number(
    value: Any,
    label: str,
    *,
    minimum: float,
    maximum: Optional[float] = None,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ResearchBundleImportError(f"{label} must be a finite number")
    number = float(value)
    if not math.isfinite(number) or number < minimum:
        raise ResearchBundleImportError(
            f"{label} must be a finite number greater than or equal to {minimum}"
        )
    if maximum is not None and number > maximum:
        raise ResearchBundleImportError(
            f"{label} must be less than or equal to {maximum}"
        )
    return number


def _same_number(left: Any, right: Any, *, fee: bool = False) -> bool:
    try:
        left_number = float(left)
        right_number = float(right)
    except (TypeError, ValueError, OverflowError):
        return False
    if not math.isfinite(left_number) or not math.isfinite(right_number):
        return False
    return math.isclose(
        left_number,
        right_number,
        rel_tol=0.0,
        abs_tol=1e-15 if fee else 1e-12,
    )


def _resolve_root(root: PathLike) -> Path:
    try:
        value = Path(root).expanduser()
        if value.is_symlink():
            raise ResearchBundleImportError("bundle root must not be a symlink")
        resolved = value.resolve(strict=True)
    except ResearchBundleImportError:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        raise ResearchBundleImportError(
            f"bundle root cannot be resolved safely: {exc}"
        ) from exc
    if not resolved.is_dir():
        raise ResearchBundleImportError("bundle root must be a directory")
    return resolved


def _resolve_file(root: Path, relative: PathLike, label: str) -> Path:
    candidate = Path(relative)
    if candidate.is_absolute():
        raise ResearchBundleImportError(f"{label} must be relative to bundle root")
    if not candidate.parts or any(
        part in ("", ".", "..") for part in candidate.parts
    ):
        raise ResearchBundleImportError(f"{label} contains an unsafe path component")
    if "\\" in str(candidate) or "\x00" in str(candidate):
        raise ResearchBundleImportError(f"{label} contains an unsafe path character")
    current = root
    for part in candidate.parts:
        current = current / part
        if current.is_symlink():
            raise ResearchBundleImportError(f"{label} must not contain symlinks")
    try:
        unresolved = root / candidate
        resolved = unresolved.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, RuntimeError, ValueError) as exc:
        raise ResearchBundleImportError(
            f"{label} cannot be resolved inside the bundle root: {exc}"
        ) from exc
    try:
        mode = os.lstat(resolved).st_mode
    except OSError as exc:
        raise ResearchBundleImportError(f"{label} cannot be inspected safely: {exc}") from exc
    if not stat.S_ISREG(mode):
        raise ResearchBundleImportError(f"{label} must be a regular file")
    return resolved


def _read_manifest(path: Path) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(str(path), flags)
    except OSError as exc:
        raise ResearchBundleImportError(f"manifest cannot be read safely: {exc}") from exc
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise ResearchBundleImportError("manifest must be a regular file")
        if info.st_size > MAX_MANIFEST_BYTES:
            raise ResearchBundleImportError(
                f"manifest exceeds the {MAX_MANIFEST_BYTES}-byte limit"
            )
        chunks = []
        remaining = MAX_MANIFEST_BYTES + 1
        while remaining:
            chunk = os.read(descriptor, min(64 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
        if len(data) > MAX_MANIFEST_BYTES:
            raise ResearchBundleImportError(
                f"manifest exceeds the {MAX_MANIFEST_BYTES}-byte limit"
            )
        return data
    except OSError as exc:
        raise ResearchBundleImportError(f"manifest cannot be read safely: {exc}") from exc
    finally:
        os.close(descriptor)


def _parse_profile(value: Any) -> ProfileSpec:
    profile = _mapping(value, "manifest profile")
    keys = (
        "name",
        "history_start_date",
        "smoke_days",
        "holdout_days",
        "stress_fee_multiplier",
        "max_drawdown_pct",
        "min_development_trades",
        "min_holdout_trades",
        "min_profit_factor",
    )
    _exact_keys(profile, keys, "manifest profile")
    history_start_date = _string(
        profile["history_start_date"], "profile history_start_date"
    )
    try:
        parsed_history_start = date.fromisoformat(history_start_date)
    except ValueError as exc:
        raise ResearchBundleImportError(
            "profile history_start_date must use a valid YYYY-MM-DD date"
        ) from exc
    if parsed_history_start.isoformat() != history_start_date:
        raise ResearchBundleImportError(
            "profile history_start_date must use canonical YYYY-MM-DD"
        )
    stress_multiplier = _number(
        profile["stress_fee_multiplier"],
        "profile stress_fee_multiplier",
        minimum=1.0,
    )
    if stress_multiplier == 1.0:
        raise ResearchBundleImportError(
            "profile stress_fee_multiplier must be greater than 1"
        )
    max_drawdown = _number(
        profile["max_drawdown_pct"],
        "profile max_drawdown_pct",
        minimum=0.0,
        maximum=100.0,
    )
    if max_drawdown == 0.0:
        raise ResearchBundleImportError("profile max_drawdown_pct must be positive")
    return ProfileSpec(
        name=_string(profile["name"], "profile name"),
        history_start_date=history_start_date,
        smoke_days=_integer(profile["smoke_days"], "profile smoke_days", minimum=1),
        holdout_days=_integer(
            profile["holdout_days"], "profile holdout_days", minimum=1
        ),
        stress_fee_multiplier=stress_multiplier,
        max_drawdown_pct=max_drawdown,
        min_development_trades=_integer(
            profile["min_development_trades"],
            "profile min_development_trades",
            minimum=0,
        ),
        min_holdout_trades=_integer(
            profile["min_holdout_trades"],
            "profile min_holdout_trades",
            minimum=0,
        ),
        min_profit_factor=_number(
            profile["min_profit_factor"],
            "profile min_profit_factor",
            minimum=0.0,
        ),
    )


def _parse_generation(metadata: Mapping[str, Any]) -> GenerationSpec:
    if "generation" not in metadata:
        return GenerationSpec(
            source="MANUAL",
            model=None,
            returned_strategy_count=1,
            source_item_index=0,
        )

    generation = _mapping(metadata["generation"], "candidate metadata generation")
    _exact_keys(
        generation,
        ("source", "model", "returned_strategy_count", "source_item_index"),
        "candidate metadata generation",
    )
    if generation["source"] != "CODEX":
        raise ResearchBundleImportError(
            "candidate metadata generation source must be CODEX"
        )
    model = _optional_string(generation["model"], "generation model")
    returned_strategy_count = _integer(
        generation["returned_strategy_count"],
        "generation returned_strategy_count",
        minimum=1,
    )
    if returned_strategy_count > 3:
        raise ResearchBundleImportError(
            "generation returned_strategy_count must be less than or equal to 3"
        )
    source_item_index = _integer(
        generation["source_item_index"],
        "generation source_item_index",
        minimum=0,
    )
    if source_item_index >= returned_strategy_count:
        raise ResearchBundleImportError(
            "generation source_item_index must be less than returned_strategy_count"
        )
    return GenerationSpec(
        source="CODEX",
        model=model,
        returned_strategy_count=returned_strategy_count,
        source_item_index=source_item_index,
    )


def _parse_candidate(value: Any) -> CandidateSpec:
    candidate = _mapping(value, "manifest candidate")
    keys = (
        "display_name",
        "class_name",
        "strategy_family",
        "idea",
        "expected_failure_mode",
        "metadata",
    )
    _exact_keys(candidate, keys, "manifest candidate")
    class_name = _string(candidate["class_name"], "candidate class_name")
    if _CLASS_NAME.fullmatch(class_name) is None:
        raise ResearchBundleImportError(
            "candidate class_name must be a simple Python identifier"
        )
    metadata = _mapping(candidate["metadata"], "candidate metadata")
    return CandidateSpec(
        display_name=_string(candidate["display_name"], "candidate display_name"),
        class_name=class_name,
        strategy_family=_optional_string(
            candidate["strategy_family"], "candidate strategy_family"
        ),
        idea=_optional_string(candidate["idea"], "candidate idea"),
        expected_failure_mode=_optional_string(
            candidate["expected_failure_mode"],
            "candidate expected_failure_mode",
        ),
        metadata=metadata,
        generation=_parse_generation(metadata),
    )


def _parse_artifacts(value: Any) -> Tuple[ArtifactSpec, ...]:
    if not isinstance(value, list):
        raise ResearchBundleImportError("manifest artifacts must be a JSON array")
    parsed = []
    for index, item in enumerate(value):
        artifact = _mapping(item, f"manifest artifact {index}")
        _exact_keys(
            artifact,
            ("scenario", "archive", "provenance_sha256"),
            f"manifest artifact {index}",
        )
        scenario = _string(artifact["scenario"], f"artifact {index} scenario")
        archive_text = _string(artifact["archive"], f"artifact {index} archive")
        archive = Path(archive_text)
        if archive.is_absolute():
            raise ResearchBundleImportError(
                f"artifact {index} archive must be a relative path"
            )
        receipt = _string(
            artifact["provenance_sha256"],
            f"artifact {index} provenance_sha256",
        )
        if _SHA256.fullmatch(receipt) is None:
            raise ResearchBundleImportError(
                f"artifact {index} provenance_sha256 must be 64 lowercase hexadecimal characters"
            )
        parsed.append(ArtifactSpec(scenario, archive, receipt))
    scenarios = [item.scenario for item in parsed]
    if len(parsed) != 3 or set(scenarios) != set(BUNDLE_SCENARIOS):
        raise ResearchBundleImportError(
            "manifest must contain each of DEVELOPMENT, HOLDOUT, and "
            "HOLDOUT_STRESS exactly once"
        )
    if len(set(scenarios)) != len(scenarios):
        raise ResearchBundleImportError("manifest contains a duplicate scenario")
    by_scenario = {item.scenario: item for item in parsed}
    return tuple(by_scenario[scenario] for scenario in BUNDLE_SCENARIOS)


def _validate_cross_scenario(
    profile: ProfileSpec,
    artifacts: Mapping[str, ParsedBacktestArtifact],
) -> None:
    development = artifacts["DEVELOPMENT"]
    holdout = artifacts["HOLDOUT"]
    stress = artifacts["HOLDOUT_STRESS"]
    common_fields = (
        "strategy",
        "freqtrade_version",
        "freqtrade_commit",
        "strategy_sha256",
        "strategy_source",
        "exchange",
        "trading_mode",
        "margin_mode",
        "pairs",
        "timeframe",
        "detail_timeframe",
        "starting_balance",
        "stake_amount",
        "max_open_trades",
    )
    for scenario, artifact in artifacts.items():
        for field in common_fields:
            if getattr(artifact, field) != getattr(development, field):
                raise ResearchBundleImportError(
                    f"{scenario} artifact disagrees on common field {field}"
                )

    base_fee = development.configured_fee
    if not _same_number(holdout.configured_fee, base_fee, fee=True):
        raise ResearchBundleImportError(
            "DEVELOPMENT and HOLDOUT artifacts must use the same base fee"
        )
    if not _same_number(
        stress.configured_fee,
        base_fee * profile.stress_fee_multiplier,
        fee=True,
    ):
        raise ResearchBundleImportError(
            "HOLDOUT_STRESS fee must equal base fee times stress_fee_multiplier"
        )
    if (
        stress.backtest_start != holdout.backtest_start
        or stress.backtest_end != holdout.backtest_end
    ):
        raise ResearchBundleImportError(
            "HOLDOUT_STRESS must use the same timerange as HOLDOUT"
        )

    holdout_start = datetime.fromisoformat(
        holdout.backtest_start.replace("Z", "+00:00")
    )
    holdout_end_exclusive = datetime.fromisoformat(
        holdout.backtest_end.replace("Z", "+00:00")
    ) + timedelta(minutes=5)
    holdout_duration = holdout_end_exclusive - holdout_start
    if (
        holdout_duration.total_seconds() % (24 * 60 * 60) != 0
        or holdout_duration.days != profile.holdout_days
    ):
        raise ResearchBundleImportError(
            "profile holdout_days must equal the HOLDOUT artifact calendar span"
        )

    identities = {
        (
            artifact.backtest_start,
            artifact.backtest_end,
            artifact.timeframe,
            artifact.detail_timeframe,
            artifact.configured_fee,
        )
        for artifact in artifacts.values()
    }
    if len(identities) != 3:
        raise ResearchBundleImportError(
            "the three scenario timerange/timeframe/fee identities must be unique"
        )

    earliest = min(
        datetime.fromisoformat(artifact.backtest_start.replace("Z", "+00:00")).date()
        for artifact in artifacts.values()
    )
    if date.fromisoformat(profile.history_start_date) > earliest:
        raise ResearchBundleImportError(
            "profile history_start_date must not be after the first backtest date"
        )


def validate_research_bundle(
    bundle_root: PathLike,
    manifest: PathLike,
) -> ValidatedResearchBundle:
    """Validate a manifest, all three artifacts, and their shared contract."""
    root = _resolve_root(bundle_root)
    manifest_path = _resolve_file(root, manifest, "manifest")
    manifest_bytes = _read_manifest(manifest_path)
    value = _mapping(_strict_json(manifest_bytes, "manifest"), "manifest")
    _exact_keys(
        value,
        ("schema", "freqtrade_version", "profile", "candidate", "artifacts"),
        "manifest",
    )
    if value["schema"] != BUNDLE_SCHEMA:
        raise ResearchBundleImportError("unsupported research bundle schema")
    if value["freqtrade_version"] != SUPPORTED_FREQTRADE_VERSION:
        raise ResearchBundleImportError(
            f"bundle must use Freqtrade {SUPPORTED_FREQTRADE_VERSION}"
        )
    profile = _parse_profile(value["profile"])
    candidate = _parse_candidate(value["candidate"])
    artifact_specs = _parse_artifacts(value["artifacts"])

    parsed_artifacts = []
    for spec in artifact_specs:
        try:
            parsed = parse_backtest_artifact(
                root,
                spec.archive,
                candidate.class_name,
                SUPPORTED_FREQTRADE_VERSION,
                spec.provenance_sha256,
            )
        except ArtifactImportError as exc:
            raise ResearchBundleImportError(
                f"{spec.scenario} artifact failed validation: {exc}"
            ) from exc
        parsed_artifacts.append((spec.scenario, parsed))
    artifact_map = dict(parsed_artifacts)
    _validate_cross_scenario(profile, artifact_map)
    return ValidatedResearchBundle(
        root=root,
        manifest_path=manifest_path,
        manifest_sha256=_sha256(manifest_bytes),
        profile=profile,
        candidate=candidate,
        artifacts=tuple(parsed_artifacts),
    )


def _resolve_database(path_value: PathLike) -> Path:
    try:
        value = Path(path_value).expanduser()
        if value.is_symlink():
            raise ResearchBundleImportError("database path must not be a symlink")
        path = value.resolve(strict=True)
    except ResearchBundleImportError:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        raise ResearchBundleImportError(
            f"database path cannot be resolved safely: {exc}"
        ) from exc
    if not path.is_file():
        raise ResearchBundleImportError("database path must be a regular file")
    return path


def _profile_contract(bundle: ValidatedResearchBundle) -> Dict[str, Any]:
    first = bundle.artifacts[0][1]
    profile = bundle.profile
    return {
        "name": profile.name,
        "domain": "OKX_CRYPTO_PERP",
        "exchange": first.exchange,
        "trading_mode": first.trading_mode,
        "margin_mode": first.margin_mode,
        "pairs_json": _canonical_json(list(first.pairs)),
        "timeframe": first.timeframe,
        "detail_timeframe": first.detail_timeframe,
        "history_start_date": profile.history_start_date,
        "smoke_days": profile.smoke_days,
        "holdout_days": profile.holdout_days,
        "starting_balance": first.starting_balance,
        "stake_amount": first.stake_amount,
        "max_open_trades": first.max_open_trades,
        "taker_fee_rate": first.configured_fee,
        "stress_fee_multiplier": profile.stress_fee_multiplier,
        "max_drawdown_pct": profile.max_drawdown_pct,
        "min_development_trades": profile.min_development_trades,
        "min_holdout_trades": profile.min_holdout_trades,
        "min_profit_factor": profile.min_profit_factor,
    }


def _existing_json_equal(value: Any, expected: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return _strict_json(value.encode("utf-8"), "database JSON") == expected
    except ResearchBundleImportError:
        return False


def _require_profile_match(row: sqlite3.Row, contract: Mapping[str, Any]) -> None:
    text_fields = (
        "name",
        "domain",
        "exchange",
        "trading_mode",
        "margin_mode",
        "timeframe",
        "detail_timeframe",
        "history_start_date",
    )
    integer_fields = (
        "smoke_days",
        "holdout_days",
        "max_open_trades",
        "min_development_trades",
        "min_holdout_trades",
    )
    number_fields = (
        "starting_balance",
        "stake_amount",
        "taker_fee_rate",
        "stress_fee_multiplier",
        "max_drawdown_pct",
        "min_profit_factor",
    )
    for field in text_fields + integer_fields:
        if row[field] != contract[field]:
            raise ResearchBundleImportError(
                f"existing research profile {contract['name']!r} conflicts on {field}"
            )
    for field in number_fields:
        if not _same_number(
            row[field], contract[field], fee=(field == "taker_fee_rate")
        ):
            raise ResearchBundleImportError(
                f"existing research profile {contract['name']!r} conflicts on {field}"
            )
    if not _existing_json_equal(row["pairs_json"], json.loads(contract["pairs_json"])):
        raise ResearchBundleImportError(
            f"existing research profile {contract['name']!r} conflicts on pairs_json"
        )


def _require_candidate_match(
    row: sqlite3.Row,
    spec: CandidateSpec,
    artifact: ParsedBacktestArtifact,
    profile_id: str,
) -> None:
    generation = spec.generation
    if (
        row["generation_profile_id"] != profile_id
        or row["generation_source"] != generation.source
        or row["generation_model"] != generation.model
        or row["generation_returned_strategy_count"]
        != generation.returned_strategy_count
        or row["generation_status"] != "COMPLETED"
        or row["source_item_index"] != generation.source_item_index
    ):
        raise ResearchBundleImportError(
            "existing candidate generation lineage conflicts with the bundle profile"
        )
    expected = {
        "display_name": spec.display_name,
        "class_name": spec.class_name,
        "timeframe": artifact.timeframe,
        "strategy_family": spec.strategy_family,
        "idea": spec.idea,
        "expected_failure_mode": spec.expected_failure_mode,
        "code_text": artifact.strategy_source,
        "code_sha256": artifact.strategy_sha256,
    }
    for field, value in expected.items():
        if row[field] != value:
            raise ResearchBundleImportError(
                f"existing candidate {artifact.strategy_sha256!r} conflicts on {field}"
            )
    if not _existing_json_equal(row["metadata_json"], spec.metadata):
        raise ResearchBundleImportError(
            f"existing candidate {artifact.strategy_sha256!r} conflicts on metadata_json"
        )


def _zip_member_locator(path: Path, member: str) -> str:
    return f"zip+{path.as_uri()}!/{quote(member, safe='/')}"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def import_research_bundle(
    database: PathLike,
    bundle_root: PathLike,
    manifest: PathLike,
) -> ImportedResearchBundle:
    """Validate then atomically insert one complete ResearchRun."""
    bundle = validate_research_bundle(bundle_root, manifest)
    database_path = _resolve_database(database)
    timestamp = _utc_now()
    profile_contract = _profile_contract(bundle)
    first_artifact = bundle.artifacts[0][1]

    try:
        connection = get_connection(database_path)
    except (sqlite3.Error, OSError, OverflowError) as exc:
        raise ResearchBundleImportError(
            f"database cannot be opened safely: {exc}"
        ) from exc

    with closing(connection):
        try:
            connection.execute("BEGIN IMMEDIATE")
            schema_row = connection.execute("PRAGMA user_version").fetchone()
            if schema_row is None or int(schema_row[0]) != 1:
                raise ResearchBundleImportError("database schema version must be 1")

            profile_row = connection.execute(
                "SELECT * FROM research_profiles WHERE name = ?",
                (profile_contract["name"],),
            ).fetchone()
            profile_reused = profile_row is not None
            if profile_row is None:
                profile_id = str(uuid.uuid4())
                connection.execute(
                    """
                    INSERT INTO research_profiles (
                        id, name, domain, exchange, trading_mode, margin_mode,
                        pairs_json, timeframe, detail_timeframe, history_start_date,
                        smoke_days, holdout_days, starting_balance, stake_amount,
                        max_open_trades, taker_fee_rate, stress_fee_multiplier,
                        max_drawdown_pct, min_development_trades,
                        min_holdout_trades, min_profit_factor, is_default,
                        created_at, updated_at
                    ) VALUES (
                        :id, :name, :domain, :exchange, :trading_mode, :margin_mode,
                        :pairs_json, :timeframe, :detail_timeframe,
                        :history_start_date, :smoke_days, :holdout_days,
                        :starting_balance, :stake_amount, :max_open_trades,
                        :taker_fee_rate, :stress_fee_multiplier,
                        :max_drawdown_pct, :min_development_trades,
                        :min_holdout_trades, :min_profit_factor, 0,
                        :created_at, :updated_at
                    )
                    """,
                    {
                        **profile_contract,
                        "id": profile_id,
                        "created_at": timestamp,
                        "updated_at": timestamp,
                    },
                )
            else:
                _require_profile_match(profile_row, profile_contract)
                profile_id = profile_row["id"]

            candidate_row = connection.execute(
                """
                SELECT c.*,
                    gr.research_profile_id AS generation_profile_id,
                    gr.source AS generation_source,
                    gr.model AS generation_model,
                    gr.returned_strategy_count AS generation_returned_strategy_count,
                    gr.status AS generation_status
                FROM candidates AS c
                JOIN generation_runs AS gr ON gr.id = c.generation_run_id
                WHERE c.code_sha256 = ?
                """,
                (first_artifact.strategy_sha256,),
            ).fetchone()
            candidate_reused = candidate_row is not None
            if candidate_row is None:
                generation_run_id = str(uuid.uuid4())
                candidate_id = str(uuid.uuid4())
                generation = bundle.candidate.generation
                connection.execute(
                    """
                    INSERT INTO generation_runs (
                        id, research_profile_id, source, model, status,
                        request_json, response_raw_text, response_json,
                        returned_strategy_count, parse_report_json, error_message,
                        started_at, finished_at, created_at, updated_at
                    ) VALUES (
                        ?, ?, ?, ?, 'COMPLETED', ?, NULL, NULL,
                        ?, ?, NULL, ?, ?, ?, ?
                    )
                    """,
                    (
                        generation_run_id,
                        profile_id,
                        generation.source,
                        generation.model,
                        _canonical_json(
                            {
                                "kind": "research_bundle_import",
                                "manifest_sha256": bundle.manifest_sha256,
                            }
                        ),
                        generation.returned_strategy_count,
                        _canonical_json(
                            {
                                "artifact_count": 3,
                                "bundle_schema": BUNDLE_SCHEMA,
                                "validated": True,
                            }
                        ),
                        timestamp,
                        timestamp,
                        timestamp,
                        timestamp,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO candidates (
                        id, generation_run_id, source_item_index,
                        parent_candidate_id, display_name, class_name, timeframe,
                        strategy_family, idea, expected_failure_mode, code_text,
                        code_sha256, metadata_json, created_at, updated_at
                    ) VALUES (
                        ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                    )
                    """,
                    (
                        candidate_id,
                        generation_run_id,
                        generation.source_item_index,
                        bundle.candidate.display_name,
                        bundle.candidate.class_name,
                        first_artifact.timeframe,
                        bundle.candidate.strategy_family,
                        bundle.candidate.idea,
                        bundle.candidate.expected_failure_mode,
                        first_artifact.strategy_source,
                        first_artifact.strategy_sha256,
                        _canonical_json(bundle.candidate.metadata),
                        timestamp,
                        timestamp,
                    ),
                )
            else:
                _require_candidate_match(
                    candidate_row,
                    bundle.candidate,
                    first_artifact,
                    profile_id,
                )
                candidate_id = candidate_row["id"]
                generation_run_id = candidate_row["generation_run_id"]

            research_run_id = str(uuid.uuid4())
            input_snapshot = {
                "artifacts": [
                    {
                        "archive": str(parsed.archive_path.relative_to(bundle.root)),
                        "archive_sha256": parsed.archive_sha256,
                        "provenance_sha256": parsed.provenance_sha256,
                        "scenario": scenario,
                    }
                    for scenario, parsed in bundle.artifacts
                ],
                "bundle_schema": BUNDLE_SCHEMA,
                "manifest": str(bundle.manifest_path.relative_to(bundle.root)),
                "manifest_sha256": bundle.manifest_sha256,
            }
            connection.execute(
                """
                INSERT INTO research_runs (
                    id, candidate_id, research_profile_id, trigger_type,
                    status, stage, verdict, pipeline_version,
                    freqtrade_version, input_snapshot_json, checks_json,
                    run_dir, rejection_reasons_json, error_stage, error_message,
                    created_at, started_at, finished_at
                ) VALUES (
                    ?, ?, ?, 'MANUAL', 'RUNNING', 'FINALIZE', NULL, ?, ?, ?, ?,
                    ?, '[]', NULL, NULL, ?, ?, NULL
                )
                """,
                (
                    research_run_id,
                    candidate_id,
                    profile_id,
                    BUNDLE_PIPELINE_VERSION,
                    SUPPORTED_FREQTRADE_VERSION,
                    _canonical_json(input_snapshot),
                    _canonical_json(
                        {
                            "artifact_contracts": "VALIDATED",
                            "cross_scenario_binding": "VALIDATED",
                            "judge": "NOT_RUN",
                        }
                    ),
                    str(bundle.root),
                    timestamp,
                    timestamp,
                ),
            )

            execution_ids = []
            for sequence, (scenario, parsed) in enumerate(bundle.artifacts, start=1):
                execution_id = str(uuid.uuid4())
                execution_ids.append(execution_id)
                multiplier = (
                    bundle.profile.stress_fee_multiplier
                    if scenario == "HOLDOUT_STRESS"
                    else 1.0
                )
                values = execution_result_values(parsed)
                connection.execute(
                    """
                    INSERT INTO backtest_executions (
                        id, research_run_id, scenario, status, sequence,
                        timerange_start, timerange_end, timeframe,
                        detail_timeframe, fee_rate, fee_multiplier,
                        command_json, config_path, strategy_path,
                        result_archive_path, stdout_path, stderr_path,
                        return_code, total_trades, profit_pct,
                        max_drawdown_pct, win_rate, profit_factor, sharpe,
                        sortino, calmar, long_profit_pct, short_profit_pct,
                        metrics_json, scenario_passed, error_message,
                        created_at, started_at, finished_at
                    ) VALUES (
                        :id, :research_run_id, :scenario, 'SUCCEEDED', :sequence,
                        :timerange_start, :timerange_end, :timeframe,
                        :detail_timeframe, :fee_rate, :fee_multiplier,
                        '[]', :config_path, :strategy_path,
                        :result_archive_path, NULL, NULL, NULL,
                        :total_trades, :profit_pct, :max_drawdown_pct,
                        :win_rate, :profit_factor, :sharpe, :sortino, :calmar,
                        :long_profit_pct, :short_profit_pct, :metrics_json,
                        NULL, NULL, :created_at, NULL, NULL
                    )
                    """,
                    {
                        **values,
                        "id": execution_id,
                        "research_run_id": research_run_id,
                        "scenario": scenario,
                        "sequence": sequence,
                        "timerange_start": parsed.backtest_start,
                        "timerange_end": parsed.backtest_end,
                        "timeframe": parsed.timeframe,
                        "detail_timeframe": parsed.detail_timeframe,
                        "fee_rate": parsed.configured_fee,
                        "fee_multiplier": multiplier,
                        "config_path": _zip_member_locator(
                            parsed.archive_path, parsed.config_member
                        ),
                        "strategy_path": _zip_member_locator(
                            parsed.archive_path, parsed.strategy_member
                        ),
                        "created_at": timestamp,
                    },
                )

            scenario_rows = connection.execute(
                """
                SELECT scenario, status FROM backtest_executions
                WHERE research_run_id = ? ORDER BY sequence
                """,
                (research_run_id,),
            ).fetchall()
            if [row["scenario"] for row in scenario_rows] != list(BUNDLE_SCENARIOS) or any(
                row["status"] != "SUCCEEDED" for row in scenario_rows
            ):
                raise ResearchBundleImportError(
                    "database did not retain exactly three succeeded bundle scenarios"
                )
            update = connection.execute(
                """
                UPDATE research_runs
                SET status = 'COMPLETED', stage = 'COMPLETED', finished_at = ?
                WHERE id = ? AND status = 'RUNNING' AND stage = 'FINALIZE'
                  AND verdict IS NULL
                """,
                (timestamp, research_run_id),
            )
            if update.rowcount != 1:
                raise ResearchBundleImportError(
                    "research run changed before bundle finalization"
                )
            connection.commit()
        except ResearchBundleImportError:
            if connection.in_transaction:
                connection.rollback()
            raise
        except (sqlite3.Error, OSError, OverflowError, UnicodeEncodeError) as exc:
            if connection.in_transaction:
                connection.rollback()
            raise ResearchBundleImportError(
                f"database bundle import failed: {exc}"
            ) from exc

    return ImportedResearchBundle(
        profile_id=profile_id,
        generation_run_id=generation_run_id,
        candidate_id=candidate_id,
        research_run_id=research_run_id,
        execution_ids=tuple(execution_ids),
        profile_reused=profile_reused,
        candidate_reused=candidate_reused,
    )
