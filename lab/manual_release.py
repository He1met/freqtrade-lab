"""Explicit human Judge and immutable local Release publication.

This module owns one narrow boundary after the existing three-scenario Holdout
contract.  It does not run Freqtrade, open an exchange, or manage deployment.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shlex
import shutil
import sqlite3
import stat
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence, Tuple, Union
from uuid import uuid4

from lab.backtest_artifact import (
    ParsedBacktestArtifact,
    execution_result_values,
)
from lab.codex_generation import (
    GenerationContractError,
    load_approved_candidate_snapshot,
)
from lab.database import get_connection
from lab.holdout_run import (
    DEVELOPMENT_PIPELINE_VERSION,
    SUPPORTED_FREQTRADE_VERSION,
    HoldoutRunError,
    _ORIGINAL_CHECKS,
    _canonical,
    _load_holdout_input,
    _load_holdout_result,
    _parse_later_artifacts,
    _parsed_development,
    _profile_binding_sha256,
    _profile_spec_from_row,
    _require_execution_contract,
    _result_matches_authorized_identity,
    _schema_v1,
)
from lab.research_bundle import ResearchBundleImportError, _validate_cross_scenario


PathLike = Union[str, Path]
MANUAL_RELEASE_SCHEMA = "freqtrade-lab-manual-release-v1"
MAX_REASON_CHARS = 1000
MANUAL_ACTIONS = frozenset({"REJECT", "PASS_AND_CREATE_RELEASE"})
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_CLASS_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_FINAL_DIRECTORY = re.compile(
    r"^release-[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)


class ManualReleaseError(RuntimeError):
    """Stable, public-safe manual review error."""

    def __init__(self, code: str, message: str, *, status: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


@dataclass
class FrozenReleaseRoot:
    """Startup-frozen Git-external directory owned by the current user."""

    path: Path
    identity: Tuple[int, int]
    descriptor: int

    def unchanged(self) -> bool:
        try:
            path_info = os.lstat(self.path)
            opened = os.fstat(self.descriptor)
        except OSError:
            return False
        return (
            stat.S_ISDIR(path_info.st_mode)
            and stat.S_ISDIR(opened.st_mode)
            and (path_info.st_dev, path_info.st_ino) == self.identity
            and (opened.st_dev, opened.st_ino) == self.identity
        )

    def close(self) -> None:
        if self.descriptor >= 0:
            os.close(self.descriptor)
            self.descriptor = -1


@dataclass(frozen=True)
class EligibleManualReview:
    research_run_id: str
    candidate_id: str
    profile_id: str
    display_name: str
    class_name: str
    strategy_source: str
    strategy_sha256: str
    profile: Mapping[str, Any]
    profile_sha256: str
    freqtrade_version: str
    source_bindings: Mapping[str, Any]
    artifacts: Tuple[Mapping[str, Any], ...]
    binding_sha256: str


def freeze_release_root(
    value: PathLike,
    project_root: PathLike,
    *,
    create: bool = False,
) -> FrozenReleaseRoot:
    """Resolve one private local Release root and retain its directory handle."""
    selected = Path(value).expanduser()
    try:
        if selected.is_symlink():
            raise ManualReleaseError(
                "release_root_unsafe", "Release root must not be a symlink"
            )
        if create and not selected.exists():
            selected.mkdir(mode=0o700)
        resolved = selected.resolve(strict=True)
        project = Path(project_root).resolve(strict=True)
        info = os.lstat(resolved)
    except ManualReleaseError:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        raise ManualReleaseError(
            "release_root_unavailable", "Release root cannot be resolved safely"
        ) from exc
    try:
        resolved.relative_to(project)
    except ValueError:
        pass
    else:
        raise ManualReleaseError(
            "release_root_unsafe", "Release root must stay outside Git"
        )
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.getuid()
        or stat.S_IMODE(info.st_mode) & 0o077
    ):
        raise ManualReleaseError(
            "release_root_unsafe",
            "Release root must be a private directory owned by the current user",
        )
    descriptor = -1
    try:
        descriptor = os.open(
            resolved,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
        )
        opened = os.fstat(descriptor)
        if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
            raise OSError("Release root identity changed")
    except OSError as exc:
        try:
            os.close(descriptor)
        except OSError:
            pass
        raise ManualReleaseError(
            "release_root_unavailable", "Release root cannot be opened safely"
        ) from exc
    return FrozenReleaseRoot(
        path=resolved,
        identity=(info.st_dev, info.st_ino),
        descriptor=descriptor,
    )


def normalize_reason(value: Any) -> str:
    """Accept bounded human text only; never treat it as a command or path."""
    if not isinstance(value, str):
        raise ManualReleaseError(
            "invalid_reason", "人工理由必须是普通文本", status=400
        )
    normalized = value.replace("\r\n", "\n").replace("\r", "\n").strip()
    if (
        not normalized
        or len(normalized) > MAX_REASON_CHARS
        or any(
            (ord(character) < 0x20 and character not in {"\n", "\t"})
            or ord(character) == 0x7F
            for character in normalized
        )
    ):
        raise ManualReleaseError(
            "invalid_reason",
            f"人工理由必须为 1–{MAX_REASON_CHARS} 个普通文本字符",
            status=400,
        )
    return normalized


def _canonical_bytes(value: Any) -> bytes:
    return (_canonical(value) + "\n").encode("utf-8")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_object(raw: Any, label: str) -> dict[str, Any]:
    if not isinstance(raw, str):
        raise ManualReleaseError("run_state_conflict", f"{label} is invalid")
    try:
        value = json.loads(raw)
    except (TypeError, json.JSONDecodeError, RecursionError) as exc:
        raise ManualReleaseError("run_state_conflict", f"{label} is invalid") from exc
    if not isinstance(value, dict):
        raise ManualReleaseError("run_state_conflict", f"{label} is invalid")
    return value


def _json_list(raw: Any, label: str) -> list[Any]:
    if not isinstance(raw, str):
        raise ManualReleaseError("run_state_conflict", f"{label} is invalid")
    try:
        value = json.loads(raw)
    except (TypeError, json.JSONDecodeError, RecursionError) as exc:
        raise ManualReleaseError("run_state_conflict", f"{label} is invalid") from exc
    if not isinstance(value, list):
        raise ManualReleaseError("run_state_conflict", f"{label} is invalid")
    return value


def _timestamp(value: Optional[str]) -> str:
    if value is None:
        return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
            "+00:00", "Z"
        )
    if not isinstance(value, str) or not value:
        raise ManualReleaseError("invalid_timestamp", "manual review time is invalid")
    return value


def _artifact_binding(
    scenario: str,
    execution: sqlite3.Row,
    parsed: ParsedBacktestArtifact,
) -> Mapping[str, Any]:
    try:
        _require_execution_contract(execution, parsed)
    except HoldoutRunError as exc:
        raise ManualReleaseError(
            "run_state_conflict", "Execution contract drifted from its Artifact"
        ) from exc
    expected = execution_result_values(parsed)
    for name, value in expected.items():
        if name == "result_archive_path":
            if Path(str(execution[name])) != Path(str(value)):
                raise ManualReleaseError(
                    "run_state_conflict", "Execution Artifact path drifted"
                )
        elif execution[name] != value:
            raise ManualReleaseError(
                "run_state_conflict", "Execution metrics drifted from its Artifact"
            )
    return {
        "execution_id": execution["id"],
        "scenario": scenario,
        "archive_sha256": parsed.archive_sha256,
        "metadata_sha256": parsed.metadata_sha256,
        "provenance_sha256": parsed.provenance_sha256,
        "report_sha256": parsed.report_sha256,
        "config_sha256": parsed.config_sha256,
        "strategy_sha256": parsed.strategy_sha256,
    }


def _eligible_manual_review(
    connection: sqlite3.Connection,
    research_run_id: str,
) -> EligibleManualReview:
    """Revalidate the complete existing Holdout/Artifact/Profile contract."""
    if not connection.in_transaction:
        raise ManualReleaseError(
            "run_state_conflict", "manual review requires one SQLite snapshot"
        )
    try:
        _schema_v1(connection)
    except HoldoutRunError as exc:
        raise ManualReleaseError(exc.code, exc.message, status=exc.status) from exc
    run = connection.execute(
        """
        SELECT rr.*, c.class_name, c.code_text, c.code_sha256,
               c.display_name, c.generation_run_id,
               gr.research_profile_id AS generation_profile_id,
               gr.status AS generation_status,
               rp.*
        FROM research_runs AS rr
        JOIN candidates AS c ON c.id=rr.candidate_id
        JOIN generation_runs AS gr ON gr.id=c.generation_run_id
        JOIN research_profiles AS rp ON rp.id=rr.research_profile_id
        WHERE rr.id=?
        """,
        (research_run_id,),
    ).fetchone()
    if run is None:
        raise ManualReleaseError(
            "run_not_found", "ResearchRun 不存在", status=404
        )
    executions = connection.execute(
        "SELECT * FROM backtest_executions WHERE research_run_id=? ORDER BY sequence,id",
        (research_run_id,),
    ).fetchall()
    checks = _json_object(run["checks_json"], "manual review checks")
    snapshot = _json_object(run["input_snapshot_json"], "manual review snapshot")
    reasons = _json_list(run["rejection_reasons_json"], "manual review reasons")
    expected_checks = {
        **_ORIGINAL_CHECKS,
        "authorization": "AUTHORIZED",
        "next_phase": "HUMAN_ECONOMIC_REVIEW",
        "holdout": "SUCCEEDED",
        "holdout_stress": "SUCCEEDED",
        "judge": "NOT_RUN",
    }
    authorization = snapshot.get("holdout_authorization")
    try:
        approved = load_approved_candidate_snapshot(
            connection, str(run["candidate_id"])
        )
    except GenerationContractError as exc:
        raise ManualReleaseError(
            "run_state_conflict", "Candidate approval/source binding drifted"
        ) from exc
    if (
        run["pipeline_version"] != DEVELOPMENT_PIPELINE_VERSION
        or run["freqtrade_version"] != SUPPORTED_FREQTRADE_VERSION
        or run["status"] != "COMPLETED"
        or run["stage"] != "COMPLETED"
        or run["verdict"] is not None
        or run["finished_at"] is None
        or checks != expected_checks
        or reasons != []
        or not isinstance(authorization, dict)
        or authorization.get("candidate_code_sha256") != run["code_sha256"]
        or authorization.get("research_profile_id") != run["research_profile_id"]
        or authorization.get("profile_binding_sha256")
        != _profile_binding_sha256(connection, str(run["research_profile_id"]))
        or snapshot.get("candidate_id") != run["candidate_id"]
        or snapshot.get("candidate_code_sha256") != run["code_sha256"]
        or snapshot.get("generation_run_id") != run["generation_run_id"]
        or snapshot.get("research_profile_id") != run["research_profile_id"]
        or run["generation_profile_id"] != run["research_profile_id"]
        or run["generation_status"] != "COMPLETED"
        or approved.candidate_id != run["candidate_id"]
        or approved.profile_id != run["research_profile_id"]
        or approved.code_sha256 != run["code_sha256"]
        or len(executions) != 3
        or [(row["scenario"], row["sequence"], row["status"]) for row in executions]
        != [
            ("DEVELOPMENT", 1, "SUCCEEDED"),
            ("HOLDOUT", 2, "SUCCEEDED"),
            ("HOLDOUT_STRESS", 3, "SUCCEEDED"),
        ]
        or executions[0]["scenario_passed"] != 1
        or any(row["scenario_passed"] is not None for row in executions[1:])
        or connection.execute(
            "SELECT COUNT(*) FROM releases WHERE research_run_id=?",
            (research_run_id,),
        ).fetchone()[0]
        != 0
    ):
        raise ManualReleaseError(
            "review_not_eligible", "ResearchRun 不满足人工终态资格"
        )
    for name in (
        "pilot_spec_sha256",
        "source_provenance_sha256",
        "development_provenance_sha256",
        "config_sha256",
        "runner_sha256",
    ):
        value = snapshot.get(name)
        if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
            raise ManualReleaseError(
                "run_state_conflict", "Research source SHA binding is incomplete"
            )
    if (
        not isinstance(snapshot.get("freqtrade_source_tree"), str)
        or _GIT_SHA.fullmatch(str(snapshot["freqtrade_source_tree"])) is None
        or not isinstance(snapshot.get("freqtrade_commit"), str)
        or _GIT_SHA.fullmatch(str(snapshot["freqtrade_commit"])) is None
    ):
        raise ManualReleaseError(
            "run_state_conflict", "Freqtrade source binding is incomplete"
        )
    run_dir = Path(str(run["run_dir"]))
    try:
        directory = run_dir.resolve(strict=True)
        _holdout_manifest, holdout_authorization = _load_holdout_input(
            directory, research_run_id
        )
        result, _result_sha = _load_holdout_result(directory, research_run_id)
        if holdout_authorization != authorization or not _result_matches_authorized_identity(
            result, run, snapshot, directory
        ):
            raise HoldoutRunError(
                "artifact_invalid", "Holdout identity receipt drifted"
            )
        development = _parsed_development(
            executions[0], directory, approved.class_name
        )
        later = _parse_later_artifacts(
            directory,
            result,
            approved.class_name,
            approved.code_sha256,
            str(authorization["holdout_timerange"]),
        )
        artifacts = {
            "DEVELOPMENT": development,
            "HOLDOUT": later["HOLDOUT"],
            "HOLDOUT_STRESS": later["HOLDOUT_STRESS"],
        }
        _validate_cross_scenario(_profile_spec_from_row(run), artifacts)
    except (
        HoldoutRunError,
        ResearchBundleImportError,
        KeyError,
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
    ) as exc:
        raise ManualReleaseError(
            "artifact_invalid", "三场景 Artifact/Profile 绑定无法重新验证"
        ) from exc
    artifact_bindings = tuple(
        _artifact_binding(scenario, execution, artifacts[scenario])
        for scenario, execution in zip(
            ("DEVELOPMENT", "HOLDOUT", "HOLDOUT_STRESS"), executions
        )
    )
    profile = dict(approved.profile)
    profile_sha = _profile_binding_sha256(
        connection, str(run["research_profile_id"])
    )
    source_bindings = {
        name: snapshot.get(name)
        for name in (
            "pilot_spec_sha256",
            "source_provenance_sha256",
            "development_provenance_sha256",
            "config_sha256",
            "runner_sha256",
            "freqtrade_commit",
            "freqtrade_source_tree",
        )
    }
    binding = {
        "research_run_id": research_run_id,
        "candidate_id": approved.candidate_id,
        "profile_id": approved.profile_id,
        "strategy_sha256": approved.code_sha256,
        "profile_sha256": profile_sha,
        "source_bindings": source_bindings,
        "artifacts": artifact_bindings,
        "holdout_manifest_sha256": holdout_authorization.get(
            "input_manifest_sha256"
        ),
    }
    return EligibleManualReview(
        research_run_id=research_run_id,
        candidate_id=approved.candidate_id,
        profile_id=approved.profile_id,
        display_name=approved.display_name,
        class_name=approved.class_name,
        strategy_source=approved.code_text,
        strategy_sha256=approved.code_sha256,
        profile=profile,
        profile_sha256=profile_sha,
        freqtrade_version=str(run["freqtrade_version"]),
        source_bindings=source_bindings,
        artifacts=artifact_bindings,
        binding_sha256=_sha256(_canonical_bytes(binding)),
    )


def _release_root_state(
    connection: sqlite3.Connection,
    root: FrozenReleaseRoot,
    *,
    allow_unregistered: Sequence[str] = (),
) -> None:
    if not root.unchanged():
        raise ManualReleaseError(
            "release_state_unknown", "Release root identity changed; state is UNKNOWN"
        )
    known: set[str] = set()
    rows = connection.execute("SELECT release_dir FROM releases").fetchall()
    for row in rows:
        try:
            path = Path(str(row["release_dir"]))
            if path.parent != root.path or _FINAL_DIRECTORY.fullmatch(path.name) is None:
                raise ValueError("unsafe Release directory")
        except (TypeError, ValueError):
            raise ManualReleaseError(
                "release_state_unknown", "Release database binding is UNKNOWN"
            ) from None
        known.add(path.name)
    try:
        entries = set(os.listdir(root.descriptor))
    except OSError as exc:
        raise ManualReleaseError(
            "release_state_unknown", "Release root cannot be inspected; state is UNKNOWN"
        ) from exc
    allowed = known | set(allow_unregistered)
    if entries != allowed:
        raise ManualReleaseError(
            "release_state_unknown",
            "Release root contains an uncommitted or unknown entry; automatic retry is disabled",
        )
    for name in entries:
        try:
            info = os.stat(name, dir_fd=root.descriptor, follow_symlinks=False)
        except OSError as exc:
            raise ManualReleaseError(
                "release_state_unknown", "Release directory state is UNKNOWN"
            ) from exc
        if not stat.S_ISDIR(info.st_mode):
            raise ManualReleaseError(
                "release_state_unknown", "Release directory state is UNKNOWN"
            )


def _dry_run_config(evidence: EligibleManualReview) -> Mapping[str, Any]:
    profile = evidence.profile
    pairs = profile.get("pairs")
    stake = profile.get("stake_amount")
    if (
        not isinstance(pairs, list)
        or not pairs
        or not all(isinstance(item, str) and item for item in pairs)
        or _CLASS_NAME.fullmatch(evidence.class_name) is None
        or isinstance(stake, bool)
        or not isinstance(stake, (int, float))
        or not math.isfinite(float(stake))
        or float(stake) <= 0
    ):
        raise ManualReleaseError(
            "review_not_eligible", "Profile 无法生成受控 dry-run 配置"
        )
    return {
        "max_open_trades": profile["max_open_trades"],
        "stake_currency": "USDT",
        "stake_amount": stake,
        "tradable_balance_ratio": 0.99,
        "fiat_display_currency": "USD",
        "dry_run": True,
        "dry_run_wallet": profile["starting_balance"],
        "cancel_open_orders_on_exit": False,
        "trading_mode": profile["trading_mode"],
        "margin_mode": profile["margin_mode"],
        "timeframe": profile["timeframe"],
        "fee": profile["taker_fee_rate"],
        "unfilledtimeout": {
            "entry": 10,
            "exit": 30,
            "exit_timeout_count": 0,
            "unit": "minutes",
        },
        "entry_pricing": {
            "price_side": "same",
            "use_order_book": True,
            "order_book_top": 1,
        },
        "exit_pricing": {
            "price_side": "same",
            "use_order_book": True,
            "order_book_top": 1,
        },
        "exchange": {
            "name": profile["exchange"],
            "enable_ws": False,
            "pair_whitelist": pairs,
            "pair_blacklist": [],
        },
        "pairlists": [{"method": "StaticPairList"}],
        "strategy": evidence.class_name,
    }


def _build_release(
    evidence: EligibleManualReview,
    root: FrozenReleaseRoot,
    release_id: str,
    reason: str,
    created_at: str,
) -> Mapping[str, Any]:
    directory_name = f"release-{release_id}"
    release_dir = root.path / directory_name
    strategy_relative = f"strategies/{evidence.class_name}.py"
    strategy_bytes = evidence.strategy_source.encode("utf-8", "strict")
    if _sha256(strategy_bytes) != evidence.strategy_sha256:
        raise ManualReleaseError(
            "run_state_conflict", "Candidate source changed before Release"
        )
    config_bytes = _canonical_bytes(_dry_run_config(evidence))
    command_argv = (
        "freqtrade",
        "trade",
        "--dry-run",
        "--config",
        str(release_dir / "config-dry-run.json"),
        "--strategy-path",
        str(release_dir / "strategies"),
        "--strategy",
        evidence.class_name,
    )
    command = shlex.join(command_argv)
    readme = (
        f"# {evidence.display_name}\n\n"
        "This immutable local package is a manual dry-run handoff only. It has not "
        "been executed or deployed and does not prove profitability, robustness, "
        "tradability, or fund safety.\n\n"
        f"ResearchRun: `{evidence.research_run_id}`\n\n"
        "```sh\n"
        f"{command}\n"
        "```\n"
    ).encode("utf-8")
    manifest = {
        "schema": MANUAL_RELEASE_SCHEMA,
        "release_id": release_id,
        "research_run_id": evidence.research_run_id,
        "candidate": {
            "id": evidence.candidate_id,
            "class_name": evidence.class_name,
            "strategy_sha256": evidence.strategy_sha256,
        },
        "profile": dict(evidence.profile),
        "profile_sha256": evidence.profile_sha256,
        "source_bindings": dict(evidence.source_bindings),
        "executions": list(evidence.artifacts),
        "freqtrade_version": evidence.freqtrade_version,
        "human_review": {
            "action": "PASS_AND_CREATE_RELEASE",
            "reason": reason,
            "source": "RESEARCH_CONSOLE",
            "decided_at": created_at,
            "release_id": release_id,
        },
        "files": {
            strategy_relative: _sha256(strategy_bytes),
            "config-dry-run.json": _sha256(config_bytes),
            "README.md": _sha256(readme),
        },
        "dry_run_handoff": {
            "status": "NOT_EXECUTED",
            "argv": list(command_argv),
            "command": command,
        },
        "created_at": created_at,
    }
    manifest_bytes = _canonical_bytes(manifest)
    return {
        "release_id": release_id,
        "directory_name": directory_name,
        "release_dir": release_dir,
        "strategy_relative": strategy_relative,
        "strategy_bytes": strategy_bytes,
        "config_bytes": config_bytes,
        "readme_bytes": readme,
        "manifest": manifest,
        "manifest_bytes": manifest_bytes,
        "manifest_sha256": _sha256(manifest_bytes),
        "config_sha256": _sha256(config_bytes),
        "command": command,
    }


def _write_exclusive(path: Path, data: bytes) -> None:
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o400,
    )
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        os.close(descriptor)


def _publish_release(root: FrozenReleaseRoot, package: Mapping[str, Any]) -> None:
    if not root.unchanged():
        raise ManualReleaseError(
            "release_state_unknown", "Release root identity changed; state is UNKNOWN"
        )
    staging_name = f".{package['directory_name']}.preparing"
    staging = root.path / staging_name
    final = Path(package["release_dir"])
    published = False
    try:
        os.mkdir(staging_name, 0o700, dir_fd=root.descriptor)
        (staging / "strategies").mkdir(mode=0o700)
        _write_exclusive(
            staging / str(package["strategy_relative"]),
            package["strategy_bytes"],
        )
        _write_exclusive(staging / "config-dry-run.json", package["config_bytes"])
        _write_exclusive(staging / "README.md", package["readme_bytes"])
        _write_exclusive(staging / "manifest.json", package["manifest_bytes"])
        (staging / "strategies").chmod(0o500)
        staging.chmod(0o500)
        directories = (staging / "strategies", staging)
        for directory in directories:
            descriptor = os.open(
                directory,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
            )
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        if final.exists() or final.is_symlink():
            raise FileExistsError("Release directory already exists")
        os.rename(
            staging_name,
            str(package["directory_name"]),
            src_dir_fd=root.descriptor,
            dst_dir_fd=root.descriptor,
        )
        published = True
        os.fsync(root.descriptor)
    except (OSError, TypeError, ValueError) as exc:
        if published:
            raise ManualReleaseError(
                "release_state_unknown",
                "Release directory publication durability is UNKNOWN; automatic retry is disabled",
                status=500,
            ) from exc
        if staging.exists() and not staging.is_symlink():
            try:
                staging.chmod(0o700)
                strategies = staging / "strategies"
                if strategies.is_dir() and not strategies.is_symlink():
                    strategies.chmod(0o700)
            except OSError:
                pass
            shutil.rmtree(staging, ignore_errors=True)
        if os.path.lexists(staging):
            raise ManualReleaseError(
                "release_state_unknown",
                "Release staging cleanup is UNKNOWN; automatic retry is disabled",
                status=500,
            ) from exc
        raise ManualReleaseError(
            "release_publish_failed", "Release package could not be published", status=500
        ) from exc


def _final_checks(
    action: str,
    reason: str,
    decided_at: str,
    release_id: Optional[str],
) -> str:
    review = {
        "action": action,
        "reason": reason,
        "source": "RESEARCH_CONSOLE",
        "decided_at": decided_at,
    }
    if release_id is not None:
        review["release_id"] = release_id
    checks = {
        **_ORIGINAL_CHECKS,
        "authorization": "AUTHORIZED",
        "next_phase": (
            "TERMINAL_REJECTED" if action == "REJECT" else "MANUAL_DRY_RUN_HANDOFF"
        ),
        "holdout": "SUCCEEDED",
        "holdout_stress": "SUCCEEDED",
        "judge": "HUMAN",
        "human_review": review,
    }
    return _canonical(checks)


def reject_research_run(
    database: PathLike,
    release_root: FrozenReleaseRoot,
    research_run_id: str,
    reason: Any,
    *,
    now: Optional[str] = None,
) -> None:
    """Atomically set one exact eligible run to REJECTED; create no files."""
    normalized = normalize_reason(reason)
    timestamp = _timestamp(now)
    with closing(get_connection(database, must_exist=True)) as connection:
        try:
            connection.execute("BEGIN IMMEDIATE")
            _release_root_state(connection, release_root)
            _eligible_manual_review(connection, research_run_id)
            rejection = _canonical(
                [
                    {
                        "code": "HUMAN_REJECT",
                        "reason": normalized,
                        "source": "RESEARCH_CONSOLE",
                        "decided_at": timestamp,
                    }
                ]
            )
            changed = connection.execute(
                """
                UPDATE research_runs
                SET verdict='REJECTED', checks_json=?, rejection_reasons_json=?
                WHERE id=? AND status='COMPLETED' AND stage='COMPLETED'
                  AND verdict IS NULL
                """,
                (
                    _final_checks("REJECT", normalized, timestamp, None),
                    rejection,
                    research_run_id,
                ),
            ).rowcount
            if changed != 1:
                raise ManualReleaseError(
                    "review_conflict", "ResearchRun changed during manual REJECT"
                )
            if connection.execute(
                "SELECT COUNT(*) FROM releases WHERE research_run_id=?",
                (research_run_id,),
            ).fetchone()[0]:
                raise ManualReleaseError(
                    "review_conflict", "REJECT must not create a Release"
                )
            connection.commit()
        except ManualReleaseError:
            if connection.in_transaction:
                connection.rollback()
            raise
        except (OSError, sqlite3.Error, RuntimeError, TypeError, ValueError) as exc:
            if connection.in_transaction:
                connection.rollback()
            raise ManualReleaseError(
                "review_failed", "人工 REJECT 无法原子提交", status=500
            ) from exc


def pass_and_create_release(
    database: PathLike,
    release_root: FrozenReleaseRoot,
    research_run_id: str,
    reason: Any,
    *,
    now: Optional[str] = None,
) -> Mapping[str, Any]:
    """Publish files first, then CAS the PASSED verdict and Release row."""
    normalized = normalize_reason(reason)
    timestamp = _timestamp(now)
    with closing(get_connection(database, must_exist=True)) as connection:
        connection.execute("BEGIN")
        _release_root_state(connection, release_root)
        evidence = _eligible_manual_review(connection, research_run_id)
        connection.rollback()
    release_id = str(uuid4())
    package = _build_release(
        evidence, release_root, release_id, normalized, timestamp
    )
    _publish_release(release_root, package)
    try:
        with closing(get_connection(database, must_exist=True)) as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                _release_root_state(
                    connection,
                    release_root,
                    allow_unregistered=(str(package["directory_name"]),),
                )
                locked = _eligible_manual_review(connection, research_run_id)
                if locked.binding_sha256 != evidence.binding_sha256:
                    raise ManualReleaseError(
                        "review_conflict", "ResearchRun binding changed before Release commit"
                    )
                changed = connection.execute(
                    """
                    UPDATE research_runs
                    SET verdict='PASSED', checks_json=?, rejection_reasons_json='[]'
                    WHERE id=? AND status='COMPLETED' AND stage='COMPLETED'
                      AND verdict IS NULL
                    """,
                    (
                        _final_checks(
                            "PASS_AND_CREATE_RELEASE",
                            normalized,
                            timestamp,
                            release_id,
                        ),
                        research_run_id,
                    ),
                ).rowcount
                if changed != 1:
                    raise ManualReleaseError(
                        "review_conflict", "ResearchRun changed during PASS"
                    )
                connection.execute(
                    """
                    INSERT INTO releases (
                        id,research_run_id,display_name,release_dir,
                        strategy_sha256,config_sha256,manifest_json,
                        manifest_sha256,freqtrade_version,created_at,archived_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,NULL)
                    """,
                    (
                        release_id,
                        research_run_id,
                        evidence.display_name,
                        str(package["release_dir"]),
                        evidence.strategy_sha256,
                        package["config_sha256"],
                        _canonical(package["manifest"]),
                        package["manifest_sha256"],
                        evidence.freqtrade_version,
                        timestamp,
                    ),
                )
                connection.commit()
            except Exception:
                if connection.in_transaction:
                    connection.rollback()
                raise
    except Exception as exc:
        if isinstance(exc, ManualReleaseError) and exc.code == "release_state_unknown":
            raise
        raise ManualReleaseError(
            "release_state_unknown",
            "Release directory was published but SQLite commit is UNKNOWN/failed; automatic retry is disabled",
            status=500,
        ) from exc
    return dict(package)


def stored_manual_review(
    connection: sqlite3.Connection,
    research_run_id: str,
) -> Optional[Mapping[str, Any]]:
    """Return the stored final human verdict and Release identity, if any."""
    run = connection.execute(
        "SELECT verdict,checks_json,rejection_reasons_json FROM research_runs WHERE id=?",
        (research_run_id,),
    ).fetchone()
    if run is None:
        raise ManualReleaseError("run_not_found", "ResearchRun 不存在", status=404)
    if run["verdict"] is None:
        return None
    checks = _json_object(run["checks_json"], "manual review checks")
    if checks.get("judge") != "HUMAN":
        return None
    review = checks.get("human_review")
    if (
        not isinstance(review, dict)
        or review.get("source") != "RESEARCH_CONSOLE"
        or not isinstance(review.get("reason"), str)
        or not review["reason"]
    ):
        raise ManualReleaseError(
            "run_state_conflict", "stored manual review is invalid"
        )
    release = connection.execute(
        "SELECT * FROM releases WHERE research_run_id=?",
        (research_run_id,),
    ).fetchone()
    release_public: Optional[Mapping[str, Any]] = None
    if run["verdict"] == "REJECTED":
        reasons = _json_list(run["rejection_reasons_json"], "manual rejection reasons")
        if (
            checks.get("next_phase") != "TERMINAL_REJECTED"
            or review.get("action") != "REJECT"
            or len(reasons) != 1
            or release is not None
        ):
            raise ManualReleaseError(
                "run_state_conflict", "stored REJECT review is invalid"
            )
    elif run["verdict"] == "PASSED":
        if (
            checks.get("next_phase") != "MANUAL_DRY_RUN_HANDOFF"
            or review.get("action") != "PASS_AND_CREATE_RELEASE"
            or release is None
            or _json_list(run["rejection_reasons_json"], "manual pass reasons") != []
        ):
            raise ManualReleaseError(
                "run_state_conflict", "stored PASS review is invalid"
            )
        manifest = _json_object(release["manifest_json"], "Release manifest")
        manifest_bytes = _canonical_bytes(manifest)
        handoff = manifest.get("dry_run_handoff")
        candidate = manifest.get("candidate")
        files = manifest.get("files")
        if (
            manifest.get("schema") != MANUAL_RELEASE_SCHEMA
            or manifest.get("release_id") != release["id"]
            or manifest.get("research_run_id") != research_run_id
            or review.get("release_id") != release["id"]
            or manifest.get("human_review") != review
            or _sha256(manifest_bytes) != release["manifest_sha256"]
            or not isinstance(candidate, dict)
            or candidate.get("strategy_sha256") != release["strategy_sha256"]
            or not isinstance(files, dict)
            or files.get(f"strategies/{candidate.get('class_name')}.py")
            != release["strategy_sha256"]
            or files.get("config-dry-run.json") != release["config_sha256"]
            or not isinstance(handoff, dict)
            or handoff.get("status") != "NOT_EXECUTED"
            or not isinstance(handoff.get("command"), str)
            or not handoff["command"]
        ):
            raise ManualReleaseError(
                "run_state_conflict", "stored Release manifest is invalid"
            )
        release_public = {
            "id": release["id"],
            "display_name": release["display_name"],
            "manifest_sha256": release["manifest_sha256"],
            "strategy_sha256": release["strategy_sha256"],
            "config_sha256": release["config_sha256"],
            "freqtrade_version": release["freqtrade_version"],
            "created_at": release["created_at"],
            "dry_run_handoff": {
                "status": "NOT_EXECUTED",
                "command": handoff["command"],
            },
        }
    else:
        raise ManualReleaseError(
            "run_state_conflict", "stored manual verdict is invalid"
        )
    return {
        "status": run["verdict"],
        "can_reject": False,
        "can_pass_and_create_release": False,
        "reason": review["reason"],
        "source": review["source"],
        "decided_at": review.get("decided_at"),
        "release": release_public,
        "profitability_claim": "NOT_ESTABLISHED",
        "tradability_claim": "NOT_ESTABLISHED",
    }


def inspect_manual_review(
    database: PathLike,
    release_root: FrozenReleaseRoot,
    research_run_id: str,
) -> Mapping[str, Any]:
    """Return current manual Judge availability without changing state."""
    with closing(get_connection(database, read_only=True, must_exist=True)) as connection:
        connection.execute("BEGIN")
        stored = stored_manual_review(connection, research_run_id)
        if stored is not None:
            connection.rollback()
            return stored
        try:
            _release_root_state(connection, release_root)
            _eligible_manual_review(connection, research_run_id)
        except ManualReleaseError as exc:
            connection.rollback()
            return {
                "status": "UNKNOWN" if exc.code == "release_state_unknown" else "UNAVAILABLE",
                "can_reject": False,
                "can_pass_and_create_release": False,
                "reason": exc.message,
                "release": None,
                "profitability_claim": "NOT_ESTABLISHED",
                "tradability_claim": "NOT_ESTABLISHED",
            }
        connection.rollback()
    return {
        "status": "AVAILABLE",
        "can_reject": True,
        "can_pass_and_create_release": True,
        "reason": "同一 ResearchRun 的三场景证据已复验，可进行一次人工终态",
        "reason_max_chars": MAX_REASON_CHARS,
        "release": None,
        "profitability_claim": "NOT_ESTABLISHED",
        "tradability_claim": "NOT_ESTABLISHED",
    }


__all__ = [
    "MANUAL_ACTIONS",
    "MANUAL_RELEASE_SCHEMA",
    "MAX_REASON_CHARS",
    "FrozenReleaseRoot",
    "ManualReleaseError",
    "freeze_release_root",
    "inspect_manual_review",
    "normalize_reason",
    "pass_and_create_release",
    "reject_research_run",
    "stored_manual_review",
]
