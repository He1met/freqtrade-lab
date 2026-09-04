"""T0/T1/T2 tests for the frozen Freqtrade artifact importer."""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import stat
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional

import pytest

from lab.backtest_artifact import (
    MAX_JSON_DEPTH,
    MAX_JSON_NODES,
    SUPPORTED_FREQTRADE_COMMIT,
    ArtifactImportError,
    _load_archive,
    _scenario_execution_identity,
    _strict_json,
    import_backtest_execution,
    parse_backtest_artifact,
)
from lab.database import get_connection, init_database


PROJECT_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_ROOT = PROJECT_ROOT / "tests" / "fixtures" / "freqtrade_2026_7"
ARCHIVE_NAME = "backtest-result-2026-08-30_12-55-02.zip"
ARCHIVE_STEM = Path(ARCHIVE_NAME).stem
META_NAME = f"{ARCHIVE_STEM}.meta.json"
PROVENANCE_NAME = f"{ARCHIVE_STEM}.provenance.json"
REPORT_MEMBER = f"{ARCHIVE_STEM}.json"
CONFIG_MEMBER = f"{ARCHIVE_STEM}_config.json"
STRATEGY = "StrategyTestV3Futures"
STRATEGY_MEMBER = f"{ARCHIVE_STEM}_{STRATEGY}.py"
CLI = PROJECT_ROOT / "scripts" / "import_backtest_artifact.py"
NOW = "2026-08-30T12:00:00Z"

ARCHIVE_SHA256 = "f8a064d3910435aecbe5a612211376c390d67912b856b4a19a403af31229efe9"
META_SHA256 = "e4afe038fc5a358530fe6aff8f11dc84874d60e057d4e02da839fee6f138ee2c"
PROVENANCE_SHA256 = "132b65ebdf236940a2da645ec1ef26c1b23aedc5287416ad021b725da0648d3b"
REPORT_SHA256 = "5fd2bc38f4d583640a1795dba023fb4e83d82a55a6bd664009a51533c8b66674"
CONFIG_SHA256 = "74454e4aa319358dba1e15d506d5fe3436c00935090654cff01abbb5276a58f8"
STRATEGY_SHA256 = "db2d416b5d40daf2dcd8ef8c07a937053c846ca89a9fca1f01facab60dfadc2d"

JsonMutator = Callable[[Dict[str, Any]], None]


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _fixture_members(root: Path = FIXTURE_ROOT) -> Dict[str, bytes]:
    with zipfile.ZipFile(root / ARCHIVE_NAME) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def _copy_evidence(tmp_path: Path) -> Path:
    root = tmp_path / "artifacts"
    root.mkdir()
    for name in (ARCHIVE_NAME, META_NAME, PROVENANCE_NAME):
        shutil.copy2(FIXTURE_ROOT / name, root / name)
    return root


def _write_zip(path: Path, members: Mapping[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        for name in (REPORT_MEMBER, CONFIG_MEMBER, STRATEGY_MEMBER):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_STORED
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            archive.writestr(info, members[name])


def _mutate_evidence(
    tmp_path: Path,
    *,
    report: Optional[JsonMutator] = None,
    config: Optional[JsonMutator] = None,
    provenance: Optional[JsonMutator] = None,
) -> Path:
    root = _copy_evidence(tmp_path)
    members = _fixture_members(root)
    report_value = json.loads(members[REPORT_MEMBER])
    config_value = json.loads(members[CONFIG_MEMBER])
    metadata_bytes = (root / META_NAME).read_bytes()
    provenance_value = json.loads((root / PROVENANCE_NAME).read_bytes())

    if report is not None:
        report(report_value)
        members[REPORT_MEMBER] = _json_bytes(report_value)
    if config is not None:
        config(config_value)
        members[CONFIG_MEMBER] = _json_bytes(config_value)
    _write_zip(root / ARCHIVE_NAME, members)

    artifact = provenance_value["artifact"]
    artifact["archive_sha256"] = _sha256((root / ARCHIVE_NAME).read_bytes())
    artifact["metadata_sha256"] = _sha256(metadata_bytes)
    artifact["raw_metadata_sha256"] = _sha256(metadata_bytes)
    artifact["members"] = {name: _sha256(value) for name, value in members.items()}
    artifact["sanitized_config_member_sha256"] = _sha256(members[CONFIG_MEMBER])
    if provenance is not None:
        provenance(provenance_value)
    (root / PROVENANCE_NAME).write_bytes(_json_bytes(provenance_value))
    return root


def _zero_trade_evidence(
    tmp_path: Path,
    *,
    mutate_zero_report: Optional[JsonMutator] = None,
    mutate_zero_config: Optional[JsonMutator] = None,
    mutate_zero_provenance: Optional[JsonMutator] = None,
) -> Path:
    def mutate_report(report: Dict[str, Any]) -> None:
        result = report["strategy"][STRATEGY]
        result["trades"] = []
        for key in ("total_trades", "wins", "draws", "losses"):
            result[key] = 0
        for key in (
            "profit_total",
            "max_drawdown_account",
            "winrate",
            "profit_factor",
            "sharpe",
            "sortino",
            "calmar",
            "profit_total_long",
            "profit_total_short",
        ):
            result[key] = 0.0
        if mutate_zero_report is not None:
            mutate_zero_report(report)

    def mutate_provenance(provenance: Dict[str, Any]) -> None:
        contract = provenance["contract"]
        for key in ("report_total_trades", "wins", "draws", "losses"):
            contract[key] = 0
        if mutate_zero_provenance is not None:
            mutate_zero_provenance(provenance)

    return _mutate_evidence(
        tmp_path,
        report=mutate_report,
        config=mutate_zero_config,
        provenance=mutate_provenance,
    )


def _zero_fee_evidence(tmp_path: Path) -> Path:
    def report_fee(report: Dict[str, Any]) -> None:
        for trade in report["strategy"][STRATEGY]["trades"]:
            trade["fee_open"] = 0.0
            trade["fee_close"] = 0.0

    def config_fee(config: Dict[str, Any]) -> None:
        config["fee"] = 0.0

    def provenance_fee(provenance: Dict[str, Any]) -> None:
        provenance["contract"]["fee"] = 0.0
        provenance["fee_evidence"]["rate"] = 0.0

    return _mutate_evidence(
        tmp_path,
        report=report_fee,
        config=config_fee,
        provenance=provenance_fee,
    )


def _parse(root: Path = FIXTURE_ROOT, *, allow_zero_trades: bool = False):
    receipt = _sha256((root / PROVENANCE_NAME).read_bytes())
    return parse_backtest_artifact(
        root,
        ARCHIVE_NAME,
        STRATEGY,
        "2026.7",
        receipt,
        allow_zero_trades=allow_zero_trades,
    )


def _strategy_source() -> str:
    return _fixture_members()[STRATEGY_MEMBER].decode("utf-8")


def _seed_database(
    tmp_path: Path,
    *,
    scenario: str = "DEVELOPMENT",
    execution_status: str = "PENDING",
    fee_rate: float = 0.0005,
    fee_multiplier: float = 1.0,
) -> Path:
    db_path = tmp_path / "lab.sqlite"
    init_database(db_path)
    source = _strategy_source()
    with get_connection(db_path) as connection:
        connection.execute(
            """
            INSERT INTO research_profiles (
                id, name, domain, exchange, trading_mode, margin_mode,
                pairs_json, timeframe, detail_timeframe, history_start_date,
                smoke_days, holdout_days, starting_balance, stake_amount,
                max_open_trades, taker_fee_rate, stress_fee_multiplier,
                max_drawdown_pct, min_development_trades, min_holdout_trades,
                min_profit_factor, is_default, created_at, updated_at
            ) VALUES (
                'profile', 'OKX parser fixture', 'OKX_CRYPTO_PERP', 'okx',
                'futures', 'isolated', '["XRP/USDT:USDT"]', '5m', NULL,
                '2026-07-01', 3, 3, 1000.0, 100.0, 1, 0.0005, 2.0,
                25.0, 0, 0, 0.0, 1, ?, ?
            )
            """,
            (NOW, NOW),
        )
        connection.execute(
            """
            INSERT INTO generation_runs (
                id, research_profile_id, source, status, request_json,
                returned_strategy_count, started_at, finished_at, created_at, updated_at
            ) VALUES ('generation', 'profile', 'MANUAL', 'COMPLETED', '{}', 1,
                      ?, ?, ?, ?)
            """,
            (NOW, NOW, NOW, NOW),
        )
        connection.execute(
            """
            INSERT INTO candidates (
                id, generation_run_id, source_item_index, display_name,
                class_name, timeframe, code_text, code_sha256,
                created_at, updated_at
            ) VALUES ('candidate', 'generation', 0, 'Fixture strategy', ?, '5m',
                      ?, ?, ?, ?)
            """,
            (STRATEGY, source, STRATEGY_SHA256, NOW, NOW),
        )
        stage = {
            "SMOKE": "SMOKE_BACKTEST",
            "DEVELOPMENT": "DEVELOPMENT_BACKTEST",
            "HOLDOUT": "HOLDOUT_BACKTEST",
            "HOLDOUT_STRESS": "HOLDOUT_STRESS_BACKTEST",
        }[scenario]
        connection.execute(
            """
            INSERT INTO research_runs (
                id, candidate_id, research_profile_id, trigger_type, status,
                stage, pipeline_version, input_snapshot_json, run_dir, created_at,
                started_at
            ) VALUES ('research', 'candidate', 'profile', 'MANUAL', 'RUNNING', ?,
                      '1', '{}', '/tmp/test-research', ?, ?)
            """,
            (stage, NOW, NOW),
        )
        _insert_execution(
            connection,
            scenario=scenario,
            sequence=1,
            status=execution_status,
            fee_rate=fee_rate,
            fee_multiplier=fee_multiplier,
        )
        connection.commit()
    return db_path


def _insert_execution(
    connection: sqlite3.Connection,
    *,
    scenario: str,
    sequence: int,
    status: str = "PENDING",
    fee_rate: float = 0.0005,
    fee_multiplier: float = 1.0,
) -> None:
    connection.execute(
        """
        INSERT INTO backtest_executions (
            id, research_run_id, scenario, status, sequence,
            timerange_start, timerange_end, timeframe, detail_timeframe,
            fee_rate, fee_multiplier, command_json, config_path, strategy_path,
            metrics_json, created_at
        ) VALUES (?, 'research', ?, ?, ?, '2026-08-01T00:00:00Z',
                  '2026-08-03T23:55:00Z', '5m', NULL, ?, ?, '[]',
                  '/tmp/config.json', '/tmp/strategy.py', '{}', ?)
        """,
        (f"execution-{scenario}", scenario, status, sequence, fee_rate, fee_multiplier, NOW),
    )


def _snapshot(db_path: Path) -> Dict[str, list[tuple[Any, ...]]]:
    tables = (
        "research_profiles",
        "generation_runs",
        "candidates",
        "research_runs",
        "backtest_executions",
        "releases",
    )
    with get_connection(db_path) as connection:
        return {
            table: [tuple(row) for row in connection.execute(f"SELECT * FROM {table} ORDER BY id")]
            for table in tables
        }


def _import(
    db_path: Path,
    *,
    root: Path = FIXTURE_ROOT,
    scenario: str = "DEVELOPMENT",
    allow_zero_trades: bool = False,
):
    return import_backtest_execution(
        db_path,
        root,
        ARCHIVE_NAME,
        "research",
        scenario,
        STRATEGY,
        "2026.7",
        _sha256((root / PROVENANCE_NAME).read_bytes()),
        allow_zero_trades=allow_zero_trades,
    )


def _run_cli(
    db_path: Path,
    *,
    root: Path = FIXTURE_ROOT,
    scenario: str = "DEVELOPMENT",
    version: str = "2026.7",
    receipt: Optional[str] = None,
) -> subprocess.CompletedProcess[str]:
    provenance_receipt = receipt or _sha256((root / PROVENANCE_NAME).read_bytes())
    return subprocess.run(
        [
            sys.executable,
            str(CLI),
            "--database",
            str(db_path),
            "--artifact-root",
            str(root),
            "--archive",
            ARCHIVE_NAME,
            "--research-run-id",
            "research",
            "--scenario",
            scenario,
            "--strategy",
            STRATEGY,
            "--freqtrade-version",
            version,
            "--provenance-sha256",
            provenance_receipt,
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def _assert_cli_failure(result: subprocess.CompletedProcess[str]) -> None:
    assert result.returncode == 2
    assert result.stderr.startswith("Backtest artifact import failed: ")
    assert "Traceback" not in result.stderr
    assert "Traceback" not in result.stdout


# T0: pure parsing and frozen-format checks.


def test_t0_strict_json_accepts_exact_depth_and_node_budgets() -> None:
    nested = b"[" * MAX_JSON_DEPTH + b"0" + b"]" * MAX_JSON_DEPTH
    assert _strict_json(nested, "bounded") is not None

    flat = ("[" + ",".join("0" for _ in range(MAX_JSON_NODES - 1)) + "]").encode()
    assert len(_strict_json(flat, "bounded")) == MAX_JSON_NODES - 1


def test_t0_strict_json_rejects_depth_over_budget() -> None:
    nested = b"[" * (MAX_JSON_DEPTH + 1) + b"0" + b"]" * (MAX_JSON_DEPTH + 1)
    with pytest.raises(ArtifactImportError, match="maximum nesting depth"):
        _strict_json(nested, "bounded")


def test_t0_strict_json_rejects_nodes_over_budget() -> None:
    flat = ("[" + ",".join("0" for _ in range(MAX_JSON_NODES)) + "]").encode()
    with pytest.raises(ArtifactImportError, match="maximum node count"):
        _strict_json(flat, "bounded")


def test_t0_parses_real_frozen_fixture_and_units() -> None:
    parsed = _parse()

    assert (parsed.freqtrade_version, parsed.freqtrade_commit) == (
        "2026.7", SUPPORTED_FREQTRADE_COMMIT)
    assert (parsed.archive_sha256, parsed.metadata_sha256, parsed.provenance_sha256) == (
        ARCHIVE_SHA256, META_SHA256, PROVENANCE_SHA256)
    assert (parsed.report_sha256, parsed.config_sha256, parsed.strategy_sha256) == (
        REPORT_SHA256, CONFIG_SHA256, STRATEGY_SHA256)
    assert (parsed.exchange, parsed.trading_mode, parsed.margin_mode) == (
        "okx", "futures", "isolated")
    assert (parsed.pairs, parsed.timeframe, parsed.detail_timeframe) == (
        ("XRP/USDT:USDT",), "5m", None)
    assert (parsed.backtest_start, parsed.backtest_end) == (
        "2026-08-01T00:00:00Z", "2026-08-03T23:55:00Z")
    assert (parsed.starting_balance, parsed.stake_amount, parsed.max_open_trades) == (
        1000.0, 100.0, 1)
    assert parsed.configured_fee == 0.0005
    assert (parsed.total_trades, parsed.wins, parsed.draws, parsed.losses) == (11, 8, 0, 3)
    assert parsed.net_profit_after_base_fees_pct == pytest.approx(parsed.profit_pct)
    assert parsed.average_holding_period_minutes == pytest.approx(77.27272727272727)
    assert parsed.roi_exit_count == 4
    assert (
        parsed.profit_pct, parsed.max_drawdown_pct, parsed.win_rate,
        parsed.long_profit_pct, parsed.short_profit_pct, parsed.profit_factor,
        parsed.sharpe, parsed.sortino, parsed.calmar,
    ) == pytest.approx((
        -0.30593600299999996, 0.4214370541505893, 72.72727272727273,
        0.07989229, -0.38582829299999995, 0.2892287571951341,
        -25.236478243392586, -16.902568083351948, -693.448650620233,
    ))


@pytest.mark.parametrize("field", ["trade_duration", "exit_reason"])
def test_t0_rejects_incomplete_economic_trade_evidence(
    tmp_path: Path, field: str
) -> None:
    def mutate(report: Dict[str, Any]) -> None:
        del report["strategy"][STRATEGY]["trades"][0][field]

    root = _mutate_evidence(tmp_path, report=mutate)
    with pytest.raises(ArtifactImportError, match=field):
        _parse(root)


def test_t0_parses_native_1d_artifact_with_daily_candle_bounds(tmp_path: Path) -> None:
    end = "2026-08-03T00:00:00Z"

    def mutate_report(report: Dict[str, Any]) -> None:
        result = report["strategy"][STRATEGY]
        result["timeframe"] = "1d"
        result["backtest_end"] = end
        result["backtest_end_ts"] = 1785715200000

    def mutate_config(config: Dict[str, Any]) -> None:
        config["timeframe"] = "1d"

    def mutate_provenance(provenance: Dict[str, Any]) -> None:
        contract = provenance["contract"]
        contract["timeframe"] = "1d"
        contract["backtest_end_utc"] = end

    root = _mutate_evidence(
        tmp_path,
        report=mutate_report,
        config=mutate_config,
        provenance=mutate_provenance,
    )

    parsed = _parse(root)

    assert parsed.timeframe == "1d"
    assert parsed.backtest_end == end


def test_t0_preserves_null_metrics_and_zero_profit_factor(tmp_path: Path) -> None:
    def mutate(report: Dict[str, Any]) -> None:
        result = report["strategy"][STRATEGY]
        for key in ("sharpe", "sortino", "calmar"):
            result[key] = None
        result["profit_factor"] = 0.0

    root = _mutate_evidence(tmp_path, report=mutate)
    parsed = _parse(root)
    assert parsed.sharpe is None
    assert parsed.sortino is None
    assert parsed.calmar is None
    assert parsed.profit_factor == 0.0


def test_t0_parser_accepts_schema_valid_zero_fee(tmp_path: Path) -> None:
    parsed = _parse(_zero_fee_evidence(tmp_path))

    assert parsed.configured_fee == 0.0


def test_t0_zero_fee_execution_identity_uses_scenario_sequence_and_multiplier() -> None:
    start = datetime(2026, 8, 4, tzinfo=timezone.utc)
    stop = datetime(2026, 8, 6, 23, 55, tzinfo=timezone.utc)
    common = (start, stop, "5m", None, 0.0)

    holdout = _scenario_execution_identity("HOLDOUT", 2, *common, 1.0)
    stress = _scenario_execution_identity("HOLDOUT_STRESS", 3, *common, 2.0)

    assert holdout != stress
    assert holdout[:2] == ("HOLDOUT", 2)
    assert stress[:2] == ("HOLDOUT_STRESS", 3)
    assert (holdout[-1], stress[-1]) == (1.0, 2.0)


@pytest.mark.parametrize("component", ["report", "config", "strategy", "metadata"])
def test_t0_rejects_content_tampered_without_provenance_refresh(
    tmp_path: Path, component: str
) -> None:
    root = _copy_evidence(tmp_path)
    if component == "metadata":
        path = root / META_NAME
        path.write_bytes(path.read_bytes() + b"\n")
    else:
        members = _fixture_members(root)
        member = {
            "report": REPORT_MEMBER,
            "config": CONFIG_MEMBER,
            "strategy": STRATEGY_MEMBER,
        }[component]
        members[member] += b"\n"
        _write_zip(root / ARCHIVE_NAME, members)
    with pytest.raises(ArtifactImportError, match="provenance|archive SHA"):
        _parse(root)


def test_t0_requires_supported_provenance_version(tmp_path: Path) -> None:
    root = _mutate_evidence(
        tmp_path,
        provenance=lambda value: value["freqtrade"].update(version="2026.8"),
    )
    with pytest.raises(ArtifactImportError, match="supported Freqtrade build"):
        _parse(root)


@pytest.mark.parametrize(
    ("field", "value"),
    [("host", "api.binance.com"), ("authentication", "api-key")],
)
def test_t0_requires_public_unauthenticated_okx_acquisition(
    tmp_path: Path, field: str, value: str
) -> None:
    root = _mutate_evidence(
        tmp_path,
        provenance=lambda receipt: receipt["acquisition"].update({field: value}),
    )
    with pytest.raises(ArtifactImportError, match="unauthenticated www.okx.com"):
        _parse(root)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("exchange", "binance"),
        ("trading_mode", "spot"),
        ("margin_mode", "cross"),
    ],
)
def test_t0_freezes_okx_futures_isolated_boundary(
    tmp_path: Path, field: str, value: str
) -> None:
    def mutate(config: Dict[str, Any]) -> None:
        if field == "exchange":
            config["exchange"]["name"] = value
        else:
            config[field] = value

    root = _mutate_evidence(tmp_path, config=mutate)
    with pytest.raises(ArtifactImportError, match="okx/futures/isolated"):
        _parse(root)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("stake_amount", 101.0, "stake_amount"),
        ("timerange", "20260802-20260804", "timerange"),
    ],
)
def test_t0_binds_report_economic_contract_fields(
    tmp_path: Path, field: str, value: Any, message: str
) -> None:
    def mutate(report: Dict[str, Any]) -> None:
        report["strategy"][STRATEGY][field] = value

    root = _mutate_evidence(tmp_path, report=mutate)
    with pytest.raises(ArtifactImportError, match=message):
        _parse(root)


def test_t0_requires_caller_trusted_provenance_hash() -> None:
    with pytest.raises(ArtifactImportError, match="trusted receipt"):
        parse_backtest_artifact(
            FIXTURE_ROOT, ARCHIVE_NAME, STRATEGY, "2026.7", "0" * 64
        )


def test_t0_rejects_extra_zip_member(tmp_path: Path) -> None:
    root = _copy_evidence(tmp_path)
    with zipfile.ZipFile(root / ARCHIVE_NAME, "a") as archive:
        archive.writestr("unexpected.bin", b"not allowed")
    with pytest.raises(ArtifactImportError, match="exactly report, config"):
        _parse(root)


@pytest.mark.parametrize(
    ("target", "payload", "message"),
    [
        (META_NAME, None, "metadata.*missing"),
        (PROVENANCE_NAME, None, "provenance.*missing"),
        (ARCHIVE_NAME, b"not-a-zip", "invalid ZIP"),
        (META_NAME, b"{", "invalid UTF-8 JSON"),
    ],
)
def test_t0_requires_valid_same_stem_evidence(
    tmp_path: Path, target: str, payload: Optional[bytes], message: str
) -> None:
    root = _copy_evidence(tmp_path)
    path = root / target
    if payload is None:
        path.unlink()
    else:
        path.write_bytes(payload)
    with pytest.raises(ArtifactImportError, match=message):
        parse_backtest_artifact(
            root, ARCHIVE_NAME, STRATEGY, "2026.7", PROVENANCE_SHA256
        )


@pytest.mark.parametrize(
    ("compression", "large_report", "message"),
    [
        (zipfile.ZIP_DEFLATED, True, "compression ratio"),
        (zipfile.ZIP_BZIP2, False, "unsupported compression"),
    ],
)
def test_t0_rejects_unsupported_or_unsafe_zip_compression(
    tmp_path: Path, compression: int, large_report: bool, message: str
) -> None:
    members = _fixture_members()
    if large_report:
        members[REPORT_MEMBER] = b"0" * 100_000
    archive_path = tmp_path / ARCHIVE_NAME
    with zipfile.ZipFile(archive_path, "w", compression=compression) as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    with pytest.raises(ArtifactImportError, match=message):
        _load_archive(archive_path.read_bytes(), ARCHIVE_STEM, STRATEGY)


def test_t0_wraps_crc_failure_from_full_member_reads() -> None:
    archive_bytes = bytearray((FIXTURE_ROOT / ARCHIVE_NAME).read_bytes())
    report_bytes = _fixture_members()[REPORT_MEMBER]
    offset = archive_bytes.find(report_bytes)
    assert offset >= 0
    archive_bytes[offset] ^= 1
    with pytest.raises(ArtifactImportError, match="cannot be read safely"):
        _load_archive(bytes(archive_bytes), ARCHIVE_STEM, STRATEGY)


def test_t0_rejects_trade_fee_mismatch(tmp_path: Path) -> None:
    def mutate(report: Dict[str, Any]) -> None:
        report["strategy"][STRATEGY]["trades"][0]["fee_close"] = 0.0006

    root = _mutate_evidence(tmp_path, report=mutate)
    with pytest.raises(ArtifactImportError, match="fee_close.*configured fee"):
        _parse(root)


def test_t0_rejects_zero_trade_report(tmp_path: Path) -> None:
    root = _zero_trade_evidence(tmp_path)
    with pytest.raises(ArtifactImportError, match="zero-trade"):
        _parse(root)


def test_t0_explicitly_allows_self_consistent_zero_trade_report(
    tmp_path: Path,
) -> None:
    parsed = _parse(_zero_trade_evidence(tmp_path), allow_zero_trades=True)

    assert (parsed.total_trades, parsed.wins, parsed.draws, parsed.losses) == (
        0,
        0,
        0,
        0,
    )
    assert (
        parsed.profit_pct,
        parsed.max_drawdown_pct,
        parsed.win_rate,
        parsed.profit_factor,
        parsed.sharpe,
        parsed.sortino,
        parsed.calmar,
        parsed.long_profit_pct,
        parsed.short_profit_pct,
    ) == pytest.approx((0.0,) * 9)


@pytest.mark.parametrize(
    ("key", "value", "message"),
    [
        ("wins", 1, "wins \\+ draws \\+ losses"),
        ("trades", [{}], "trade list length"),
        ("winrate", 0.5, "winrate does not agree"),
        ("profit_total", 0.1, "profit_total must be zero"),
        ("sharpe", 1.0, "sharpe must be zero or null"),
    ],
)
def test_t0_zero_trade_opt_in_still_requires_self_consistent_report(
    tmp_path: Path,
    key: str,
    value: Any,
    message: str,
) -> None:
    def mutate(report: Dict[str, Any]) -> None:
        report["strategy"][STRATEGY][key] = value

    root = _zero_trade_evidence(tmp_path, mutate_zero_report=mutate)
    with pytest.raises(ArtifactImportError, match=message):
        _parse(root, allow_zero_trades=True)


def test_t0_zero_trade_opt_in_still_validates_config(tmp_path: Path) -> None:
    def mutate(config: Dict[str, Any]) -> None:
        config["strategy"] = "OtherStrategy"

    root = _zero_trade_evidence(tmp_path, mutate_zero_config=mutate)
    with pytest.raises(ArtifactImportError, match="config strategy"):
        _parse(root, allow_zero_trades=True)


def test_t0_zero_trade_opt_in_still_validates_provenance_contract(
    tmp_path: Path,
) -> None:
    def mutate(provenance: Dict[str, Any]) -> None:
        provenance["contract"]["report_total_trades"] = 1

    root = _zero_trade_evidence(tmp_path, mutate_zero_provenance=mutate)
    with pytest.raises(ArtifactImportError, match="report_total_trades"):
        _parse(root, allow_zero_trades=True)


def test_t0_cross_checks_report_millisecond_epochs(tmp_path: Path) -> None:
    def mutate(report: Dict[str, Any]) -> None:
        report["strategy"][STRATEGY]["backtest_end_ts"] -= 300_000

    root = _mutate_evidence(tmp_path, report=mutate)
    with pytest.raises(ArtifactImportError, match="millisecond"):
        _parse(root)


def test_t0_rejects_missing_critical_metric(tmp_path: Path) -> None:
    def mutate(report: Dict[str, Any]) -> None:
        del report["strategy"][STRATEGY]["profit_total"]

    root = _mutate_evidence(tmp_path, report=mutate)
    with pytest.raises(ArtifactImportError, match="profit_total"):
        _parse(root)


def test_t0_rejects_integer_before_sqlite_overflow(tmp_path: Path) -> None:
    def mutate(report: Dict[str, Any]) -> None:
        report["strategy"][STRATEGY]["total_trades"] = 2**70

    root = _mutate_evidence(tmp_path, report=mutate)
    with pytest.raises(ArtifactImportError, match="SQLite integer"):
        _parse(root)


def test_t0_rejects_percentage_overflow(tmp_path: Path) -> None:
    def mutate_report(report: Dict[str, Any]) -> None:
        report["strategy"][STRATEGY]["profit_total"] = 1e308

    root = _mutate_evidence(tmp_path, report=mutate_report)
    with pytest.raises(ArtifactImportError, match="overflows percentage"):
        _parse(root)


def test_t0_rejects_archive_outside_controlled_root(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    with pytest.raises(ArtifactImportError, match="relative|unsafe"):
        parse_backtest_artifact(
            root, "../outside.zip", STRATEGY, "2026.7", PROVENANCE_SHA256
        )


# T2: temporary SQLite integration and transaction behavior.


def test_t2_imports_into_exact_existing_execution(tmp_path: Path) -> None:
    db_path = _seed_database(tmp_path)
    table_counts_before = {key: len(value) for key, value in _snapshot(db_path).items()}

    parsed = _import(db_path)

    with get_connection(db_path) as connection:
        run = connection.execute(
            "SELECT freqtrade_version FROM research_runs WHERE id = 'research'"
        ).fetchone()
        execution = connection.execute(
            "SELECT * FROM backtest_executions WHERE id = 'execution-DEVELOPMENT'"
        ).fetchone()
    assert run["freqtrade_version"] == "2026.7"
    assert (
        execution["status"], execution["result_archive_path"], execution["total_trades"]
    ) == ("SUCCEEDED", str(parsed.archive_path), 11)
    assert tuple(execution[key] for key in (
        "profit_pct", "max_drawdown_pct", "win_rate", "profit_factor", "sharpe",
        "sortino", "calmar", "long_profit_pct", "short_profit_pct",
    )) == pytest.approx((
        parsed.profit_pct, parsed.max_drawdown_pct, parsed.win_rate,
        parsed.profit_factor, parsed.sharpe, parsed.sortino, parsed.calmar,
        parsed.long_profit_pct, parsed.short_profit_pct,
    ))
    assert all(execution[key] is None for key in (
        "return_code", "stdout_path", "stderr_path", "finished_at", "scenario_passed",
    ))
    metrics = json.loads(execution["metrics_json"])
    assert metrics["artifact"]["strategy_sha256"] == STRATEGY_SHA256
    assert metrics["artifact"]["provenance_sha256"] == PROVENANCE_SHA256
    assert (metrics["wins"], metrics["draws"], metrics["losses"]) == (8, 0, 3)
    assert metrics["contract"] == {
        "configured_fee": 0.0005,
        "exchange": "okx",
        "margin_mode": "isolated",
        "pairs": ["XRP/USDT:USDT"],
        "trading_mode": "futures",
    }
    assert metrics["economic"] == {
        "average_holding_period_minutes": pytest.approx(77.27272727272727),
        "net_profit_after_base_fees_pct": pytest.approx(parsed.profit_pct),
        "roi_exit_count": 4,
    }
    assert {key: len(value) for key, value in _snapshot(db_path).items()} == table_counts_before


def test_t2_zero_trade_import_requires_opt_in_and_preserves_real_zeros(
    tmp_path: Path,
) -> None:
    root = _zero_trade_evidence(tmp_path)
    db_path = _seed_database(tmp_path)
    before = _snapshot(db_path)

    with pytest.raises(ArtifactImportError, match="zero-trade"):
        _import(db_path, root=root)
    assert _snapshot(db_path) == before

    parsed = _import(db_path, root=root, allow_zero_trades=True)

    assert parsed.total_trades == 0
    with get_connection(db_path) as connection:
        execution = connection.execute(
            "SELECT * FROM backtest_executions WHERE id = 'execution-DEVELOPMENT'"
        ).fetchone()
    assert execution["status"] == "SUCCEEDED"
    assert execution["total_trades"] == 0
    assert tuple(
        execution[key]
        for key in (
            "profit_pct",
            "max_drawdown_pct",
            "win_rate",
            "profit_factor",
            "sharpe",
            "sortino",
            "calmar",
            "long_profit_pct",
            "short_profit_pct",
        )
    ) == pytest.approx((0.0,) * 9)
    metrics = json.loads(execution["metrics_json"])
    assert (metrics["wins"], metrics["draws"], metrics["losses"]) == (0, 0, 0)
    assert metrics["economic"] == {
        "average_holding_period_minutes": None,
        "net_profit_after_base_fees_pct": 0.0,
        "roi_exit_count": 0,
    }


@pytest.mark.parametrize(
    ("column", "value", "message"),
    [
        ("class_name", "OtherStrategy", "candidate class"),
        ("code_sha256", "a" * 64, "code_sha256"),
        ("timeframe", "15m", "candidate timeframe"),
    ],
)
def test_t2_rejects_candidate_identity_mismatch(
    tmp_path: Path, column: str, value: str, message: str
) -> None:
    db_path = _seed_database(tmp_path)
    with get_connection(db_path) as connection:
        connection.execute(f"UPDATE candidates SET {column} = ? WHERE id = 'candidate'", (value,))
        connection.commit()
    before = _snapshot(db_path)
    with pytest.raises(ArtifactImportError, match=message):
        _import(db_path)
    assert _snapshot(db_path) == before


def test_t2_recomputes_candidate_code_text_hash(tmp_path: Path) -> None:
    db_path = _seed_database(tmp_path)
    with get_connection(db_path) as connection:
        connection.execute(
            "UPDATE candidates SET code_text = 'different source' WHERE id = 'candidate'"
        )
        connection.commit()
    before = _snapshot(db_path)
    with pytest.raises(ArtifactImportError, match="code_text"):
        _import(db_path)
    assert _snapshot(db_path) == before


@pytest.mark.parametrize(
    ("column", "value", "message", "ignore_check"),
    [
        ("domain", "OKX_STOCK_PERP", "profile domain", False),
        ("exchange", "binance", "profile exchange", False),
        ("trading_mode", "spot", "profile trading_mode", True),
        ("margin_mode", "cross", "profile margin_mode", False),
        ("pairs_json", '["BTC/USDT:USDT"]', "profile pair set", False),
        ("timeframe", "15m", "profile timeframe", False),
        ("detail_timeframe", "1m", "profile detail timeframe", False),
        ("starting_balance", 2000.0, "profile starting_balance", False),
        ("stake_amount", 200.0, "profile stake_amount", False),
        ("max_open_trades", 2, "profile max_open_trades", False),
    ],
)
def test_t2_rejects_profile_contract_mismatch(
    tmp_path: Path,
    column: str,
    value: Any,
    message: str,
    ignore_check: bool,
) -> None:
    db_path = _seed_database(tmp_path)
    with get_connection(db_path) as connection:
        if ignore_check:
            connection.execute("PRAGMA ignore_check_constraints = ON")
        connection.execute(
            f"UPDATE research_profiles SET {column} = ? WHERE id = 'profile'", (value,)
        )
        connection.commit()
    before = _snapshot(db_path)
    with pytest.raises(ArtifactImportError, match=message):
        _import(db_path)
    assert _snapshot(db_path) == before


def test_t2_rejects_execution_timerange_mismatch(tmp_path: Path) -> None:
    db_path = _seed_database(tmp_path)
    with get_connection(db_path) as connection:
        connection.execute(
            "UPDATE backtest_executions SET timerange_end = '2026-08-03T23:50:00Z'"
        )
        connection.commit()
    before = _snapshot(db_path)
    with pytest.raises(ArtifactImportError, match="timerange"):
        _import(db_path)
    assert _snapshot(db_path) == before


@pytest.mark.parametrize(
    ("target", "value", "message"),
    [
        ("profile_fee", 0.0004, "profile fee times multiplier"),
        ("execution_fee", 0.0006, "profile fee times multiplier"),
        ("multiplier", 2.0, "fee_multiplier.*scenario"),
    ],
)
def test_t2_rejects_fee_contract_mismatch(
    tmp_path: Path, target: str, value: float, message: str
) -> None:
    db_path = _seed_database(tmp_path)
    with get_connection(db_path) as connection:
        if target == "profile_fee":
            connection.execute(
                "UPDATE research_profiles SET taker_fee_rate = ?", (value,)
            )
        elif target == "execution_fee":
            connection.execute("UPDATE backtest_executions SET fee_rate = ?", (value,))
        else:
            connection.execute(
                "UPDATE backtest_executions SET fee_multiplier = ?", (value,)
            )
        connection.commit()
    before = _snapshot(db_path)
    with pytest.raises(ArtifactImportError, match=message):
        _import(db_path)
    assert _snapshot(db_path) == before


def test_t2_same_zip_cannot_succeed_for_holdout_and_stress(tmp_path: Path) -> None:
    db_path = _seed_database(tmp_path, scenario="HOLDOUT")
    with get_connection(db_path) as connection:
        _insert_execution(
            connection,
            scenario="HOLDOUT_STRESS",
            sequence=2,
            fee_rate=0.001,
            fee_multiplier=2.0,
        )
        connection.commit()

    _import(db_path, scenario="HOLDOUT")
    with get_connection(db_path) as connection:
        connection.execute(
            "UPDATE research_runs SET stage = 'HOLDOUT_STRESS_BACKTEST'"
        )
        connection.commit()
    before_stress = _snapshot(db_path)
    with pytest.raises(ArtifactImportError, match="artifact trade fees"):
        _import(db_path, scenario="HOLDOUT_STRESS")
    assert _snapshot(db_path) == before_stress
    with get_connection(db_path) as connection:
        rows = connection.execute(
            "SELECT scenario, status FROM backtest_executions ORDER BY sequence"
        ).fetchall()
    assert [tuple(row) for row in rows] == [
        ("HOLDOUT", "SUCCEEDED"),
        ("HOLDOUT_STRESS", "PENDING"),
    ]


def test_t2_scenario_distinguishes_otherwise_equal_execution_identity(
    tmp_path: Path,
) -> None:
    db_path = _seed_database(tmp_path)
    with get_connection(db_path) as connection:
        _insert_execution(
            connection,
            scenario="HOLDOUT",
            sequence=2,
            fee_rate=0.0005,
            fee_multiplier=1.0,
        )
        connection.commit()

    _import(db_path)

    with get_connection(db_path, read_only=True) as connection:
        rows = connection.execute(
            "SELECT scenario, status FROM backtest_executions ORDER BY sequence"
        ).fetchall()
    assert [tuple(row) for row in rows] == [
        ("DEVELOPMENT", "SUCCEEDED"),
        ("HOLDOUT", "PENDING"),
    ]


def test_t2_zero_fee_rejects_reusing_holdout_archive_bytes_for_stress(
    tmp_path: Path,
) -> None:
    root = _zero_fee_evidence(tmp_path)
    db_path = _seed_database(tmp_path, scenario="HOLDOUT", fee_rate=0.0)
    with get_connection(db_path) as connection:
        connection.execute("UPDATE research_profiles SET taker_fee_rate = 0.0")
        _insert_execution(
            connection,
            scenario="HOLDOUT_STRESS",
            sequence=2,
            fee_rate=0.0,
            fee_multiplier=2.0,
        )
        connection.commit()

    _import(db_path, root=root, scenario="HOLDOUT")
    with get_connection(db_path) as connection:
        connection.execute(
            "UPDATE research_runs SET stage = 'HOLDOUT_STRESS_BACKTEST'"
        )
        connection.commit()
    before_stress = _snapshot(db_path)

    with pytest.raises(ArtifactImportError, match="archive bytes were already imported"):
        _import(db_path, root=root, scenario="HOLDOUT_STRESS")

    assert _snapshot(db_path) == before_stress


@pytest.mark.parametrize(
    ("status", "stage", "verdict"),
    [
        ("COMPLETED", "COMPLETED", "REJECTED"),
        ("CANCELLED", "DEVELOPMENT_BACKTEST", None),
        ("RUNNING", "HOLDOUT_BACKTEST", None),
        ("RUNNING", "DEVELOPMENT_BACKTEST", "REJECTED"),
    ],
)
def test_t2_rejects_terminal_or_wrong_stage_parent(
    tmp_path: Path, status: str, stage: str, verdict: Optional[str]
) -> None:
    db_path = _seed_database(tmp_path)
    with get_connection(db_path) as connection:
        connection.execute(
            "UPDATE research_runs SET status = ?, stage = ?, verdict = ?",
            (status, stage, verdict),
        )
        connection.commit()
    before = _snapshot(db_path)
    with pytest.raises(ArtifactImportError, match="research run must be RUNNING"):
        _import(db_path)
    assert _snapshot(db_path) == before


def test_t2_importer_accepts_schema_valid_zero_fee_identity(tmp_path: Path) -> None:
    db_path = _seed_database(tmp_path)
    with get_connection(db_path) as connection:
        connection.execute(
            "UPDATE research_profiles SET taker_fee_rate = 0.0"
        )
        connection.execute("UPDATE backtest_executions SET fee_rate = 0.0")
        connection.commit()
    parsed = _import(db_path, root=_zero_fee_evidence(tmp_path))

    assert parsed.configured_fee == 0.0
    with get_connection(db_path, read_only=True) as connection:
        row = connection.execute(
            "SELECT status, fee_rate FROM backtest_executions "
            "WHERE id='execution-DEVELOPMENT'"
        ).fetchone()
    assert tuple(row) == ("SUCCEEDED", 0.0)


@pytest.mark.parametrize("scenario", ["DEVELOPMENT", "HOLDOUT_STRESS"])
def test_t2_allows_schema_valid_unit_stress_multiplier(
    tmp_path: Path, scenario: str
) -> None:
    db_path = _seed_database(
        tmp_path,
        scenario=scenario,
        fee_rate=0.0005,
        fee_multiplier=1.0,
    )
    with get_connection(db_path) as connection:
        connection.execute(
            "UPDATE research_profiles SET stress_fee_multiplier = 1.0"
        )
        connection.commit()

    _import(db_path, scenario=scenario)

    with get_connection(db_path) as connection:
        execution = connection.execute(
            "SELECT status, fee_rate, fee_multiplier FROM backtest_executions"
        ).fetchone()
    assert tuple(execution) == ("SUCCEEDED", 0.0005, 1.0)


def test_t2_failed_terminal_with_stale_result_state_is_immutable(tmp_path: Path) -> None:
    db_path = _seed_database(tmp_path, execution_status="FAILED")
    with get_connection(db_path) as connection:
        connection.execute(
            """
            UPDATE backtest_executions
            SET result_archive_path = '/tmp/old.zip', stdout_path = '/tmp/old.out',
                stderr_path = '/tmp/old.err', return_code = 1, total_trades = 2,
                metrics_json = '{"old":true}', scenario_passed = 0,
                error_message = 'old failure', finished_at = ?
            """,
            (NOW,),
        )
        connection.commit()
    before = _snapshot(db_path)
    with pytest.raises(ArtifactImportError, match="terminal rows remain immutable"):
        _import(db_path)
    assert _snapshot(db_path) == before


def test_t2_running_execution_with_started_at_is_immutable(tmp_path: Path) -> None:
    db_path = _seed_database(tmp_path, execution_status="RUNNING")
    with get_connection(db_path) as connection:
        connection.execute(
            "UPDATE backtest_executions SET started_at = ?",
            (NOW,),
        )
        connection.commit()
    before = _snapshot(db_path)

    with pytest.raises(ArtifactImportError, match="only PENDING"):
        _import(db_path)

    assert _snapshot(db_path) == before


def test_t2_clean_status_with_partial_result_is_not_overwritten(tmp_path: Path) -> None:
    db_path = _seed_database(tmp_path)
    with get_connection(db_path) as connection:
        connection.execute(
            "UPDATE backtest_executions SET total_trades = 1 WHERE id = 'execution-DEVELOPMENT'"
        )
        connection.commit()
    before = _snapshot(db_path)
    with pytest.raises(ArtifactImportError, match="pre-existing result state"):
        _import(db_path)
    assert _snapshot(db_path) == before


def test_t2_rolls_back_parent_version_when_execution_update_fails(tmp_path: Path) -> None:
    db_path = _seed_database(tmp_path)
    with get_connection(db_path) as connection:
        connection.execute(
            """
            CREATE TRIGGER force_execution_update_failure
            BEFORE UPDATE ON backtest_executions
            BEGIN
                SELECT RAISE(ABORT, 'forced execution update failure');
            END
            """
        )
        connection.commit()
    before = _snapshot(db_path)

    with pytest.raises(ArtifactImportError, match="forced execution update failure"):
        _import(db_path)

    assert _snapshot(db_path) == before
    with get_connection(db_path) as connection:
        version = connection.execute(
            "SELECT freqtrade_version FROM research_runs WHERE id = 'research'"
        ).fetchone()[0]
    assert version is None


def test_t2_reimport_never_overwrites_success(tmp_path: Path) -> None:
    db_path = _seed_database(tmp_path)
    _import(db_path)
    before = _snapshot(db_path)
    with pytest.raises(ArtifactImportError, match="cannot be imported"):
        _import(db_path)
    assert _snapshot(db_path) == before


# T1: actual CLI entrypoint and clear failure behavior.


def test_t1_cli_smoke_imports_real_fixture(tmp_path: Path) -> None:
    db_path = _seed_database(tmp_path)
    result = _run_cli(db_path)
    assert result.returncode == 0, result.stderr
    assert "Backtest artifact imported" in result.stdout
    assert "Trades: 11" in result.stdout
    assert f"Archive SHA-256: {ARCHIVE_SHA256}" in result.stdout
    assert result.stderr == ""
    with get_connection(db_path) as connection:
        version = connection.execute(
            "SELECT freqtrade_version FROM research_runs WHERE id = 'research'"
        ).fetchone()[0]
        execution = connection.execute(
            "SELECT status, result_archive_path, total_trades, profit_pct "
            "FROM backtest_executions WHERE id = 'execution-DEVELOPMENT'"
        ).fetchone()
    assert version == "2026.7"
    assert execution["status"] == "SUCCEEDED"
    assert execution["result_archive_path"] == str(FIXTURE_ROOT / ARCHIVE_NAME)
    assert execution["total_trades"] == 11
    assert execution["profit_pct"] == pytest.approx(-0.30593600299999996)


def test_t1_cli_candidate_mismatch_is_exit_2_without_traceback(tmp_path: Path) -> None:
    db_path = _seed_database(tmp_path)
    with get_connection(db_path) as connection:
        connection.execute("UPDATE candidates SET code_sha256 = ?", ("a" * 64,))
        connection.commit()
    before = _snapshot(db_path)
    result = _run_cli(db_path)
    _assert_cli_failure(result)
    assert "code_sha256" in result.stderr
    assert _snapshot(db_path) == before


def test_t1_cli_timerange_mismatch_is_exit_2_without_traceback(tmp_path: Path) -> None:
    db_path = _seed_database(tmp_path)
    with get_connection(db_path) as connection:
        connection.execute(
            "UPDATE backtest_executions SET timerange_start = '2026-08-01T00:05:00Z'"
        )
        connection.commit()
    before = _snapshot(db_path)
    result = _run_cli(db_path)
    _assert_cli_failure(result)
    assert "timerange" in result.stderr
    assert _snapshot(db_path) == before


def test_t1_cli_extreme_zoned_timestamp_is_exit_2_without_traceback(
    tmp_path: Path,
) -> None:
    db_path = _seed_database(tmp_path)
    with get_connection(db_path) as connection:
        connection.execute(
            "UPDATE backtest_executions SET timerange_start = ?",
            ("0001-01-01T00:00:00+14:00",),
        )
        connection.commit()
    before = _snapshot(db_path)

    result = _run_cli(db_path)

    _assert_cli_failure(result)
    assert "not a valid ISO timestamp" in result.stderr
    assert _snapshot(db_path) == before


def test_t1_cli_fee_mismatch_is_exit_2_without_traceback(tmp_path: Path) -> None:
    db_path = _seed_database(tmp_path, fee_rate=0.0006)
    before = _snapshot(db_path)
    result = _run_cli(db_path)
    _assert_cli_failure(result)
    assert "profile fee times multiplier" in result.stderr
    assert _snapshot(db_path) == before


def test_t1_cli_bad_version_is_exit_2_without_traceback(tmp_path: Path) -> None:
    db_path = _seed_database(tmp_path)
    before = _snapshot(db_path)
    result = _run_cli(db_path, version="2026.8")
    _assert_cli_failure(result)
    assert "unsupported Freqtrade version" in result.stderr
    assert _snapshot(db_path) == before


def test_t1_cli_bad_expanduser_path_is_exit_2_without_traceback(tmp_path: Path) -> None:
    db_path = _seed_database(tmp_path)
    before = _snapshot(db_path)
    result = _run_cli(
        db_path,
        root=Path("~codex_user_that_does_not_exist_987654"),
        receipt=PROVENANCE_SHA256,
    )
    _assert_cli_failure(result)
    assert "artifact root cannot be resolved safely" in result.stderr
    assert _snapshot(db_path) == before


def test_t1_cli_deep_json_is_exit_2_without_traceback(tmp_path: Path) -> None:
    root = _copy_evidence(tmp_path)
    path = root / PROVENANCE_NAME
    original = path.read_text(encoding="utf-8").rstrip()
    assert original.endswith("}")
    deep = original[:-1] + ',"deep":' + "[" * 1500 + "0" + "]" * 1500 + "}"
    path.write_text(deep, encoding="utf-8")
    db_path = _seed_database(tmp_path)
    before = _snapshot(db_path)
    result = _run_cli(db_path, root=root)
    _assert_cli_failure(result)
    assert "invalid UTF-8 JSON" in result.stderr
    assert _snapshot(db_path) == before
