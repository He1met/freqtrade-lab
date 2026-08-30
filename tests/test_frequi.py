"""T0/T1/T2 tests for the optional, fail-closed FreqUI entry."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Iterator, Mapping, Tuple
from urllib.parse import urlencode
from urllib.request import urlopen

import pytest

from lab.database import get_connection, init_database
from lab.frequi import (
    FreqUIConfigurationError,
    configure_frequi,
    probe_frequi,
)
from lab.research_bundle import import_research_bundle
from lab.strategy_library import create_strategy_library_server


PROJECT_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_ROOT = PROJECT_ROOT / "tests" / "fixtures" / "freqtrade_2026_7"
MANIFEST_NAME = "research-bundle-v1.json"
CLI = PROJECT_ROOT / "scripts" / "serve_strategy_library.py"
SUCCESS_RESPONSES = {
    "/api/v1/ping": (200, "application/json", b'{"status":"pong"}', {}),
    "/ui_version": (200, "application/json", b'{"version":"3.1.1"}', {}),
    "/backtest": (200, "text/html; charset=utf-8", b"<!doctype html><title>Backtest</title>", {}),
}
StubResponse = Tuple[int, str, bytes, Mapping[str, str]]


@contextmanager
def _stub_frequi(
    responses: Mapping[str, StubResponse],
) -> Iterator[Tuple[str, list[str]]]:
    requested: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.0"

        def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
            requested.append(self.path)
            response = responses.get(
                self.path,
                (404, "text/plain", b"not found", {}),
            )
            status, content_type, body, extra_headers = response
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            if "Content-Length" not in extra_headers:
                self.send_header("Content-Length", str(len(body)))
            for name, value in extra_headers.items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:
            return

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", requested
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@contextmanager
def _serve_library(
    database: Path,
    artifact_root: Path,
    frequi_origin: str,
    results_root: Path,
) -> Iterator[str]:
    server = create_strategy_library_server(
        database,
        0,
        artifact_root=artifact_root,
        frequi_base_url=frequi_origin,
        frequi_results_root=results_root,
    )
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _roots(tmp_path: Path) -> Tuple[Path, Path]:
    artifact_root = tmp_path / "frozen-artifacts"
    results_root = tmp_path / "frequi-results"
    artifact_root.mkdir()
    results_root.mkdir()
    return artifact_root.resolve(), results_root.resolve()


def _import_frozen_bundle(tmp_path: Path):
    artifact_root = tmp_path / "frozen-bundle"
    shutil.copytree(FIXTURE_ROOT, artifact_root)
    database = tmp_path / "lab.sqlite"
    init_database(database)
    imported = import_research_bundle(database, artifact_root, MANIFEST_NAME)
    with get_connection(database) as connection:
        rows = connection.execute(
            """
            SELECT scenario, result_archive_path
            FROM backtest_executions
            WHERE research_run_id = ?
            ORDER BY sequence
            """,
            (imported.research_run_id,),
        ).fetchall()
    archives = {str(row["scenario"]): Path(row["result_archive_path"]) for row in rows}
    return database, artifact_root.resolve(), imported, archives


def _copy_result_pair(archive: Path, results_root: Path) -> Tuple[Path, Path]:
    archive_copy = results_root / archive.name
    metadata = archive.with_suffix(".meta.json")
    metadata_copy = results_root / metadata.name
    shutil.copy2(archive, archive_copy)
    shutil.copy2(metadata, metadata_copy)
    return archive_copy, metadata_copy


def _detail_paths(base: str, imported: Any) -> Tuple[str, str]:
    query = urlencode(
        {
            "profile_id": imported.profile_id,
            "candidate_id": imported.candidate_id,
            "research_run_id": imported.research_run_id,
        }
    )
    return base + "/api/strategy?" + query, base + "/strategy?" + query


@pytest.mark.parametrize(
    "unsafe_url",
    [
        "https://127.0.0.1:8080",
        "http://localhost:8080",
        "http://127.0.0.2:8080",
        "http://[::1]:8080",
        "http://127.0.0.1",
        "http://user@127.0.0.1:8080",
        "http://127.0.0.1:8080/backtest",
        "http://127.0.0.1:8080?next=/backtest",
        "http://127.0.0.1:8080#backtest",
        "http://127.0.0.1:70000",
        " http://127.0.0.1:8080",
    ],
)
def test_configuration_accepts_only_numeric_ipv4_loopback_origin(
    tmp_path: Path, unsafe_url: str
) -> None:
    artifact_root, results_root = _roots(tmp_path)

    with pytest.raises(FreqUIConfigurationError):
        configure_frequi(
            unsafe_url,
            results_root,
            artifact_root=artifact_root,
        )


def test_configuration_normalizes_safe_origin_and_requires_paired_values(
    tmp_path: Path,
) -> None:
    artifact_root, results_root = _roots(tmp_path)
    config = configure_frequi(
        "http://127.0.0.1:8080/",
        results_root,
        artifact_root=artifact_root,
    )
    assert config.base_url == "http://127.0.0.1:8080"
    assert config.results_root == results_root

    with pytest.raises(FreqUIConfigurationError, match="configured together"):
        configure_frequi(None, results_root, artifact_root=artifact_root)
    with pytest.raises(FreqUIConfigurationError, match="configured together"):
        configure_frequi(
            "http://127.0.0.1:8080",
            None,
            artifact_root=artifact_root,
        )
    with pytest.raises(FreqUIConfigurationError, match="artifact root"):
        configure_frequi(
            "http://127.0.0.1:8080",
            results_root,
            artifact_root=None,
        )


def test_configuration_requires_a_separate_non_symlink_results_root(
    tmp_path: Path,
) -> None:
    common = tmp_path / "common"
    artifact_root = common / "artifacts"
    nested_results = artifact_root / "results"
    artifact_root.mkdir(parents=True)
    nested_results.mkdir()
    for unsafe_results in (common, artifact_root, nested_results):
        with pytest.raises(FreqUIConfigurationError, match="separate"):
            configure_frequi(
                "http://127.0.0.1:8080",
                unsafe_results,
                artifact_root=artifact_root.resolve(),
            )

    real_results = tmp_path / "real-results"
    real_results.mkdir()
    linked_results = tmp_path / "linked-results"
    linked_results.symlink_to(real_results, target_is_directory=True)
    with pytest.raises(FreqUIConfigurationError, match="symlink"):
        configure_frequi(
            "http://127.0.0.1:8080",
            linked_results,
            artifact_root=artifact_root.resolve(),
        )


def test_configuration_rejects_case_alias_of_frozen_root(tmp_path: Path) -> None:
    artifact_root = tmp_path / "FrozenArtifacts"
    artifact_root.mkdir()
    case_alias = tmp_path / "frozenartifacts"
    if not case_alias.exists() or not case_alias.samefile(artifact_root):
        pytest.skip("filesystem is case-sensitive")

    with pytest.raises(FreqUIConfigurationError, match="separate"):
        configure_frequi(
            "http://127.0.0.1:8080",
            case_alias,
            artifact_root=artifact_root,
        )


def test_public_probe_accepts_exact_ping_version_and_backtest_page(
    tmp_path: Path,
) -> None:
    artifact_root, results_root = _roots(tmp_path)
    with _stub_frequi(SUCCESS_RESPONSES) as (origin, requested):
        config = configure_frequi(origin, results_root, artifact_root=artifact_root)
        result = probe_frequi(config, timeout=1)

    assert result == {
        "configured": True,
        "reachable": True,
        "ui_installed": True,
        "available": True,
        "reason": None,
        "message": "FreqUI 通用 Backtest 入口可达",
        "version": "3.1.1",
        "url": origin + "/backtest",
        "webserver_mode": None,
    }
    assert requested == ["/api/v1/ping", "/ui_version", "/backtest"]


def test_unconfigured_probe_preserves_unknown_checks() -> None:
    result = probe_frequi(configure_frequi(None, None, artifact_root=None))

    assert result["configured"] is False
    assert result["reachable"] is None
    assert result["ui_installed"] is None
    assert result["webserver_mode"] is None
    assert result["reason"] == "NOT_CONFIGURED"
    assert result["url"] is None


def test_public_probe_rejects_unpinned_frequi_version(tmp_path: Path) -> None:
    artifact_root, results_root = _roots(tmp_path)
    responses = dict(SUCCESS_RESPONSES)
    responses["/ui_version"] = (
        200,
        "application/json",
        b'{"version":"3.2.0"}',
        {},
    )
    with _stub_frequi(responses) as (origin, requested):
        config = configure_frequi(origin, results_root, artifact_root=artifact_root)
        result = probe_frequi(config, timeout=1)

    assert result["available"] is False
    assert result["reachable"] is True
    assert result["ui_installed"] is True
    assert result["version"] == "3.2.0"
    assert result["reason"] == "FREQUI_VERSION_MISMATCH"
    assert requested == ["/api/v1/ping", "/ui_version"]


def test_public_probe_fails_closed_when_loopback_webserver_is_unreachable(
    tmp_path: Path,
) -> None:
    artifact_root, results_root = _roots(tmp_path)
    reserved = socket.socket()
    reserved.bind(("127.0.0.1", 0))
    port = int(reserved.getsockname()[1])
    try:
        config = configure_frequi(
            f"http://127.0.0.1:{port}",
            results_root,
            artifact_root=artifact_root,
        )
        result = probe_frequi(config, timeout=0.1)
    finally:
        reserved.close()

    assert result["available"] is False
    assert result["reachable"] is False
    assert result["reason"] == "WEBSERVER_UNREACHABLE"
    assert result["url"] is None


def test_public_probe_reports_ui_not_installed_without_trying_backtest(
    tmp_path: Path,
) -> None:
    artifact_root, results_root = _roots(tmp_path)
    responses = dict(SUCCESS_RESPONSES)
    responses["/ui_version"] = (
        200,
        "application/json",
        b'{"version":"not_installed"}',
        {},
    )
    with _stub_frequi(responses) as (origin, requested):
        config = configure_frequi(origin, results_root, artifact_root=artifact_root)
        result = probe_frequi(config, timeout=1)

    assert result["available"] is False
    assert result["reachable"] is True
    assert result["reason"] == "FREQUI_NOT_INSTALLED"
    assert result["url"] is None
    assert requested == ["/api/v1/ping", "/ui_version"]


def test_public_probe_does_not_follow_redirects(tmp_path: Path) -> None:
    artifact_root, results_root = _roots(tmp_path)
    responses = dict(SUCCESS_RESPONSES)
    responses["/api/v1/ping"] = (
        302,
        "text/plain",
        b"redirect",
        {"Location": "/redirect-target"},
    )
    with _stub_frequi(responses) as (origin, requested):
        config = configure_frequi(origin, results_root, artifact_root=artifact_root)
        result = probe_frequi(config, timeout=1)

    assert result["available"] is False
    assert result["reason"] == "WEBSERVER_RESPONSE_INVALID"
    assert result["url"] is None
    assert requested == ["/api/v1/ping"]


@pytest.mark.parametrize(
    ("path", "content_type", "body", "reason"),
    [
        (
            "/api/v1/ping",
            "application/json",
            b'{"status":"pong","status":"pong"}',
            "WEBSERVER_RESPONSE_INVALID",
        ),
        (
            "/api/v1/ping",
            "text/html",
            b'{"status":"pong"}',
            "WEBSERVER_RESPONSE_INVALID",
        ),
        (
            "/api/v1/ping",
            "text/application/json-evil",
            b'{"status":"pong"}',
            "WEBSERVER_RESPONSE_INVALID",
        ),
        (
            "/ui_version",
            "application/json",
            b'["3.1.1"]',
            "WEBSERVER_RESPONSE_INVALID",
        ),
        (
            "/backtest",
            "application/json",
            b'{"html":true}',
            "BACKTEST_PAGE_UNAVAILABLE",
        ),
        (
            "/backtest",
            "application/text/html-x",
            b"<!doctype html>",
            "BACKTEST_PAGE_UNAVAILABLE",
        ),
    ],
)
def test_public_probe_rejects_malformed_or_mistyped_responses(
    tmp_path: Path,
    path: str,
    content_type: str,
    body: bytes,
    reason: str,
) -> None:
    artifact_root, results_root = _roots(tmp_path)
    responses = dict(SUCCESS_RESPONSES)
    responses[path] = (200, content_type, body, {})
    with _stub_frequi(responses) as (origin, _):
        config = configure_frequi(origin, results_root, artifact_root=artifact_root)
        result = probe_frequi(config, timeout=1)

    assert result["available"] is False
    assert result["reason"] == reason
    assert result["url"] is None


def test_real_bundle_detail_exposes_only_generic_manual_frequi_entry(
    tmp_path: Path,
) -> None:
    database, artifact_root, imported, archives = _import_frozen_bundle(tmp_path)
    results_root = tmp_path / "frequi-results"
    results_root.mkdir()
    for archive in archives.values():
        _copy_result_pair(archive, results_root)

    with _stub_frequi(SUCCESS_RESPONSES) as (origin, requested):
        with _serve_library(database, artifact_root, origin, results_root) as base:
            api_url, page_url = _detail_paths(base, imported)
            with urlopen(api_url, timeout=5) as response:
                payload = json.load(response)
                assert response.status == 200
            with urlopen(page_url, timeout=5) as response:
                page = response.read().decode("utf-8")
                assert response.status == 200

    assert payload["frequi_service"]["available"] is True
    assert payload["frequi_service"]["version"] == "3.1.1"
    assert len(payload["scenarios"]) == 3
    for scenario in payload["scenarios"]:
        expected_archive = archives[scenario["scenario"]]
        frequi = scenario["frequi"]
        assert scenario["download"]["available"] is True
        assert frequi["available"] is True
        assert frequi["local_copy_ready"] is True
        assert frequi["history_visibility"] is None
        assert frequi["reason"] is None
        assert frequi["message"] == (
            "本地文件前提满足；请在 FreqUI 的 Load Results 中手动确认"
        )
        assert frequi["url"] == origin + "/backtest"
        assert frequi["artifact_filename"] == expected_archive.name
        assert frequi["filename"] == expected_archive.stem
        assert frequi["strategy"] == "StrategyTestV3Futures"
        assert frequi["version"] == "3.1.1"
        assert frequi["selection"] == "MANUAL"
        assert expected_archive.stem in page

    serialized = json.dumps(payload, ensure_ascii=False)
    assert f'href="{origin}/backtest"' in page
    assert origin + "/backtest?" not in page
    assert "StrategyTestV3Futures" in page
    assert "手动确认" in page
    assert "不会自动选中当前结果" in page
    assert 'target="_blank" rel="noopener noreferrer"' in page
    assert '"selection": "MANUAL"' in serialized
    for private_path in (artifact_root, results_root):
        assert str(private_path) not in page
        assert str(private_path) not in serialized
    assert requested == [
        "/api/v1/ping",
        "/ui_version",
        "/backtest",
        "/api/v1/ping",
        "/ui_version",
        "/backtest",
    ]


@pytest.mark.parametrize(
    ("case", "expected_reason"),
    [
        ("missing_archive", "RESULT_COPY_MISSING"),
        ("missing_metadata", "RESULT_COPY_MISSING"),
        ("tampered_archive_copy", "RESULT_COPY_INVALID"),
        ("tampered_metadata_copy", "METADATA_INVALID"),
        ("archive_symlink", "RESULT_COPY_INVALID"),
        ("metadata_symlink", "RESULT_COPY_INVALID"),
        ("archive_hardlink", "RESULT_COPY_INVALID"),
        ("metadata_hardlink", "RESULT_COPY_INVALID"),
        ("canonical_archive_tampered", "ARTIFACT_UNAVAILABLE"),
        ("root_replacement", "RESULT_COPY_INVALID"),
    ],
)
def test_result_copy_boundary_fails_closed(
    tmp_path: Path,
    case: str,
    expected_reason: str,
) -> None:
    database, artifact_root, imported, archives = _import_frozen_bundle(tmp_path)
    archive = archives["DEVELOPMENT"]
    metadata = archive.with_suffix(".meta.json")
    results_root = tmp_path / "frequi-results"
    results_root.mkdir()
    archive_copy = results_root / archive.name
    metadata_copy = results_root / metadata.name

    if case == "missing_archive":
        shutil.copy2(metadata, metadata_copy)
    elif case == "missing_metadata":
        shutil.copy2(archive, archive_copy)
    elif case == "archive_symlink":
        archive_copy.symlink_to(archive)
        shutil.copy2(metadata, metadata_copy)
    elif case == "metadata_symlink":
        shutil.copy2(archive, archive_copy)
        metadata_copy.symlink_to(metadata)
    elif case == "archive_hardlink":
        os.link(archive, archive_copy)
        shutil.copy2(metadata, metadata_copy)
    elif case == "metadata_hardlink":
        shutil.copy2(archive, archive_copy)
        os.link(metadata, metadata_copy)
    else:
        _copy_result_pair(archive, results_root)
        if case == "tampered_archive_copy":
            archive_copy.write_bytes(archive_copy.read_bytes() + b"tampered")
        elif case == "tampered_metadata_copy":
            metadata_copy.write_bytes(metadata_copy.read_bytes() + b" ")
        elif case == "canonical_archive_tampered":
            archive.write_bytes(archive.read_bytes() + b"tampered")

    with _stub_frequi(SUCCESS_RESPONSES) as (origin, _):
        with _serve_library(database, artifact_root, origin, results_root) as base:
            if case == "root_replacement":
                old_root = tmp_path / "old-frequi-results"
                results_root.rename(old_root)
                results_root.mkdir()
                _copy_result_pair(archive, results_root)
            api_url, page_url = _detail_paths(base, imported)
            with urlopen(api_url, timeout=5) as response:
                payload = json.load(response)
            with urlopen(page_url, timeout=5) as response:
                page = response.read().decode("utf-8")

    development = next(
        scenario
        for scenario in payload["scenarios"]
        if scenario["scenario"] == "DEVELOPMENT"
    )
    assert development["frequi"]["available"] is False
    assert development["frequi"]["local_copy_ready"] is False
    assert development["frequi"]["history_visibility"] is None
    assert development["frequi"]["url"] is None
    assert development["frequi"]["reason"] == expected_reason
    assert all(scenario["frequi"]["url"] is None for scenario in payload["scenarios"])
    assert f'href="{origin}/backtest"' not in page
    serialized = json.dumps(payload, ensure_ascii=False)
    assert str(artifact_root) not in serialized
    assert str(results_root) not in serialized
    assert str(artifact_root) not in page
    assert str(results_root) not in page


def test_detail_disables_entry_when_public_frequi_gate_fails(
    tmp_path: Path,
) -> None:
    database, artifact_root, imported, archives = _import_frozen_bundle(tmp_path)
    results_root = tmp_path / "frequi-results"
    results_root.mkdir()
    _copy_result_pair(archives["DEVELOPMENT"], results_root)
    responses = dict(SUCCESS_RESPONSES)
    responses["/ui_version"] = (
        200,
        "application/json",
        b'{"version":"not_installed"}',
        {},
    )

    with _stub_frequi(responses) as (origin, _):
        with _serve_library(database, artifact_root, origin, results_root) as base:
            api_url, page_url = _detail_paths(base, imported)
            with urlopen(api_url, timeout=5) as response:
                payload = json.load(response)
            with urlopen(page_url, timeout=5) as response:
                page = response.read().decode("utf-8")

    development = next(
        scenario
        for scenario in payload["scenarios"]
        if scenario["scenario"] == "DEVELOPMENT"
    )
    assert development["frequi"]["available"] is False
    assert development["frequi"]["local_copy_ready"] is None
    assert development["frequi"]["history_visibility"] is None
    assert development["frequi"]["reason"] == "FREQUI_NOT_INSTALLED"
    assert development["frequi"]["url"] is None
    assert f'href="{origin}/backtest"' not in page


@pytest.mark.parametrize(
    "case",
    ["extra_strategy", "boolean_start_time", "floating_start_time"],
)
def test_metadata_requires_exact_one_strategy_and_non_boolean_integer_start_time(
    tmp_path: Path,
    case: str,
) -> None:
    database, artifact_root, imported, archives = _import_frozen_bundle(tmp_path)
    archive = archives["DEVELOPMENT"]
    results_root = tmp_path / "frequi-results"
    results_root.mkdir()
    _, metadata_copy = _copy_result_pair(archive, results_root)
    metadata = json.loads(metadata_copy.read_text(encoding="utf-8"))
    strategy_metadata = metadata["StrategyTestV3Futures"]
    if case == "extra_strategy":
        metadata["UnexpectedStrategy"] = dict(strategy_metadata)
    elif case == "boolean_start_time":
        strategy_metadata["backtest_start_time"] = True
    else:
        strategy_metadata["backtest_start_time"] = float(
            strategy_metadata["backtest_start_time"]
        )
    metadata_bytes = json.dumps(
        metadata,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    metadata_copy.write_bytes(metadata_bytes)
    with get_connection(database) as connection:
        row = connection.execute(
            """
            SELECT id, metrics_json
            FROM backtest_executions
            WHERE research_run_id = ? AND scenario = 'DEVELOPMENT'
            """,
            (imported.research_run_id,),
        ).fetchone()
        metrics = json.loads(row["metrics_json"])
        metrics["artifact"]["metadata_sha256"] = hashlib.sha256(
            metadata_bytes
        ).hexdigest()
        connection.execute(
            "UPDATE backtest_executions SET metrics_json = ? WHERE id = ?",
            (
                json.dumps(metrics, separators=(",", ":"), sort_keys=True),
                row["id"],
            ),
        )
        connection.commit()

    with _stub_frequi(SUCCESS_RESPONSES) as (origin, _):
        with _serve_library(database, artifact_root, origin, results_root) as base:
            api_url, _ = _detail_paths(base, imported)
            with urlopen(api_url, timeout=5) as response:
                payload = json.load(response)

    development = next(
        scenario
        for scenario in payload["scenarios"]
        if scenario["scenario"] == "DEVELOPMENT"
    )
    assert development["frequi"]["available"] is False
    assert development["frequi"]["local_copy_ready"] is False
    assert development["frequi"]["history_visibility"] is None
    assert development["frequi"]["reason"] == "METADATA_INVALID"
    assert development["frequi"]["url"] is None


@pytest.mark.parametrize(
    ("flag", "value_kind"),
    [
        ("--frequi-base-url", "origin"),
        ("--frequi-results-root", "results"),
    ],
)
def test_cli_rejects_half_config_before_listening(
    tmp_path: Path,
    flag: str,
    value_kind: str,
) -> None:
    database = tmp_path / "lab.sqlite"
    init_database(database)
    artifact_root, results_root = _roots(tmp_path)
    value = (
        "http://127.0.0.1:54321"
        if value_kind == "origin"
        else str(results_root)
    )
    completed = subprocess.run(
        [
            sys.executable,
            str(CLI),
            "--database",
            str(database),
            "--artifact-root",
            str(artifact_root),
            flag,
            value,
            "--port",
            "0",
        ],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )

    assert completed.returncode == 2
    assert "Strategy library:" not in completed.stdout
    assert "configured together" in completed.stderr
