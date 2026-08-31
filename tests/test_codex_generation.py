"""T0 contract tests for the bounded Codex Candidate generator."""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest

from lab import codex_generation
from lab import research_bundle as research_bundle_module
from lab.database import get_connection, init_database
from lab.research_bundle import import_research_bundle, validate_research_bundle


PROJECT_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_ROOT = PROJECT_ROOT / "tests" / "fixtures" / "freqtrade_2026_7"
MANIFEST_NAME = "research-bundle-v1.json"


VALID_REQUEST = {
    "profile_id": "profile-btc-5m",
    "idea": "Test a bounded EMA pullback hypothesis.",
    "strategy_family": "trend",
    "expected_failure_mode": "Sideways markets may cause repeated whipsaws.",
}


def _candidate_output(*, code: str | None = None) -> bytes:
    source = code or (
        "from freqtrade.strategy import IStrategy\n\n"
        "class BoundedEmaPullback(IStrategy):\n"
        "    timeframe = \"5m\"\n"
    )
    return json.dumps(
        {
            "display_name": "Bounded EMA Pullback",
            "class_name": "BoundedEmaPullback",
            "code_text": source,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


def _database_with_profile(tmp_path: Path) -> Path:
    database = tmp_path / "lab.sqlite"
    init_database(database)
    connection = sqlite3.connect(database)
    try:
        connection.execute(
            """
            INSERT INTO research_profiles (
                id, name, domain, pairs_json, timeframe, history_start_date,
                smoke_days, holdout_days, starting_balance, max_open_trades,
                taker_fee_rate, stress_fee_multiplier, max_drawdown_pct,
                min_development_trades, min_holdout_trades, min_profit_factor,
                created_at, updated_at
            ) VALUES (
                'profile-btc-5m', 'BTC 5m', 'OKX_CRYPTO_PERP', '["BTC/USDT:USDT"]',
                '5m', '2026-01-01', 7, 30, 1000, 1, 0.0005, 2, 20,
                10, 10, 1.1, '2026-08-31T00:00:00Z', '2026-08-31T00:00:00Z'
            )
            """
        )
        connection.commit()
    finally:
        connection.close()
    return database


def test_t0_generation_request_accepts_only_bounded_business_fields() -> None:
    parsed = codex_generation.validate_generation_request(VALID_REQUEST)
    assert parsed.profile_id == "profile-btc-5m"
    assert parsed.parent_candidate_id is None

    forbidden = ("model", "argv", "cwd", "path", "env", "prompt", "command")
    for key in forbidden:
        with pytest.raises(codex_generation.GenerationContractError):
            codex_generation.validate_generation_request({**VALID_REQUEST, key: "x"})

    invalid = (
        {"profile_id": "profile-btc-5m"},
        {**VALID_REQUEST, "idea": ""},
        {**VALID_REQUEST, "idea": "x" * (codex_generation.MAX_IDEA_CHARS + 1)},
        {**VALID_REQUEST, "profile_id": "../profile"},
        {**VALID_REQUEST, "strategy_family": "bad\x00family"},
        {**VALID_REQUEST, "expected_failure_mode": "bad\x1fmode"},
        {**VALID_REQUEST, "parent_candidate_id": 7},
    )
    for payload in invalid:
        with pytest.raises(codex_generation.GenerationContractError):
            codex_generation.validate_generation_request(payload)


def test_t0_codex_argv_is_fixed_read_only_and_prompt_uses_stdin(tmp_path: Path) -> None:
    argv = codex_generation.build_codex_argv(
        Path("/opt/codex"),
        tmp_path / "workspace",
        tmp_path / "output-schema.json",
        tmp_path / "last-message.json",
        model="gpt-fixed",
    )
    assert codex_generation.CODEX_DISABLED_FEATURES == (
        "shell_tool",
        "unified_exec",
        "shell_snapshot",
        "sleep_tool",
        "view_image",
        "code_mode",
        "code_mode_host",
        "browser_use",
        "browser_use_external",
        "browser_use_full_cdp_access",
        "in_app_browser",
        "chronicle",
        "computer_use",
        "image_generation",
        "artifact",
        "apps",
        "plugins",
        "remote_plugin",
        "hooks",
        "multi_agent",
        "multi_agent_v2",
        "collaboration_modes",
        "multi_agent_mode",
        "enable_fanout",
        "tool_suggest",
        "standalone_web_search",
        "search_tool",
        "enable_mcp_apps",
        "skill_mcp_dependency_install",
        "tool_call_mcp_elicitation",
        "workspace_dependencies",
        "memories",
        "skill_search",
    )
    expected = [
        "/opt/codex",
        "exec",
        "--cd",
        str(tmp_path / "workspace"),
        "--skip-git-repo-check",
        "--ephemeral",
        "--ignore-user-config",
        "--ignore-rules",
        "--config",
        'web_search="disabled"',
    ]
    for feature in codex_generation.CODEX_DISABLED_FEATURES:
        expected.extend(("--disable", feature))
    expected.extend(
        [
        "--sandbox",
        "read-only",
        "--output-schema",
        str(tmp_path / "output-schema.json"),
        "--output-last-message",
        str(tmp_path / "last-message.json"),
        "--json",
        "--color",
        "never",
        "--model",
        "gpt-fixed",
        "-",
        ]
    )
    assert argv == tuple(expected)
    probe_argv = codex_generation.build_codex_feature_probe_argv(Path("/opt/codex"))
    assert probe_argv[-2:] == ("features", "list")
    assert probe_argv.count("--disable") == len(
        codex_generation.CODEX_DISABLED_FEATURES
    )
    assert "--dangerously-bypass-approvals-and-sandbox" not in argv
    assert "--approve-for-me" not in argv
    assert "workspace-write" not in argv


@pytest.mark.parametrize(
    "raw",
    (
        b'{"display_name":"x","display_name":"y","class_name":"C","code_text":"class C:\\n    timeframe=\\"5m\\"\\n"}',
        b'{"display_name":"x","class_name":"C","code_text":"class C:\\n    timeframe=\\"5m\\"\\n","extra":1}',
        b"\xff",
        b'{"display_name":"x","class_name":"bad-name","code_text":"class C:\\n    timeframe=\\"5m\\"\\n"}',
        b'{"display_name":"x","class_name":"C","code_text":"class C(:\\n"}',
        b'{"display_name":"x","class_name":"C","code_text":"class Other:\\n    timeframe=\\"5m\\"\\n"}',
        b'{"display_name":"x","class_name":"C","code_text":"class C:\\n    timeframe=choose_timeframe()\\n"}',
        b'{"display_name":"x","class_name":"C","code_text":"class C:\\n    timeframe=\\"1h\\"\\n"}',
    ),
)
def test_t0_candidate_output_is_strict_json_ast_class_and_timeframe(raw: bytes) -> None:
    with pytest.raises(codex_generation.GenerationContractError):
        codex_generation.parse_candidate_output(raw, timeframe="5m")


def test_t0_candidate_sha_is_over_exact_utf8_code_bytes() -> None:
    parsed = codex_generation.parse_candidate_output(_candidate_output(), timeframe="5m")
    assert parsed.code_sha256 == hashlib.sha256(
        parsed.code_text.encode("utf-8")
    ).hexdigest()


def test_t0_jsonl_rejects_any_tool_event_and_accepts_message_only() -> None:
    safe = b"\n".join(
        (
            b'{"type":"thread.started","thread_id":"thread-1"}',
            b'{"type":"turn.started"}',
            b'{"type":"item.completed","item":{"id":"i1","type":"agent_message","text":"done"}}',
            b'{"type":"turn.completed","usage":{"input_tokens":1,"output_tokens":1}}',
        )
    )
    summary = codex_generation.validate_codex_jsonl(safe)
    assert summary["tool_event_count"] == 0
    assert summary["turn_completed"] is True
    assert summary["preturn_diagnostic_count"] == 0

    safe_with_diagnostic = b"\n".join(
        (
            b'{"type":"thread.started","thread_id":"thread-1"}',
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {
                        "id": "item-0",
                        "type": "error",
                        "message": codex_generation._SAFE_PRETURN_DIAGNOSTIC,
                    },
                },
                separators=(",", ":"),
            ).encode("utf-8"),
            b'{"type":"turn.started"}',
            b'{"type":"item.completed","item":{"id":"i1","type":"agent_message","text":"done"}}',
            b'{"type":"turn.completed","usage":{"input_tokens":1,"output_tokens":1}}',
        )
    )
    assert codex_generation.validate_codex_jsonl(safe_with_diagnostic)[
        "preturn_diagnostic_count"
    ] == 1

    for unsafe_diagnostic in (
        b'{"type":"item.completed","item":{"id":"item-0","type":"error","message":"arbitrary"}}',
        b'{"type":"item.completed","item":{"id":"item-0","type":"error","message":"Code Mode is unavailable because code-mode host is disabled.","path":"/private"}}',
    ):
        with pytest.raises(codex_generation.GenerationContractError):
            codex_generation.validate_codex_jsonl(
                b'{"type":"thread.started","thread_id":"thread-1"}\n'
                + unsafe_diagnostic
                + b'\n{"type":"turn.started"}\n{"type":"turn.completed"}'
            )

    tool_events = (
        b'{"type":"item.started","item":{"type":"command_execution"}}',
        b'{"type":"item.completed","item":{"type":"file_change"}}',
        b'{"type":"item.completed","item":{"type":"mcp_tool_call"}}',
        b'{"type":"item.completed","item":{"type":"web_search"}}',
        b'{"type":"tool.call","name":"anything"}',
        b'{"type":"computer_action","action":"click"}',
        b'{"type":"read_file","path":"secret"}',
    )
    for event in tool_events:
        with pytest.raises(codex_generation.GenerationContractError):
            codex_generation.validate_codex_jsonl(
                b'{"type":"thread.started","thread_id":"thread-1"}\n'
                + b'{"type":"turn.started"}\n'
                + event
                + b'\n{"type":"turn.completed"}'
            )

    with pytest.raises(codex_generation.GenerationContractError):
        codex_generation.validate_codex_jsonl(
            b'{"type":"thread.started"}\n'
            b'{"type":"turn.completed"}\n'
            b'{"type":"item.completed","item":{"type":"agent_message"}}'
        )


def test_t0_ast_rejects_shadowed_strategy_and_timeframe_rewrites() -> None:
    cases = (
        "class BoundedEmaPullback(fake.IStrategy):\n    timeframe = '5m'\n",
        (
            "from freqtrade.strategy import IStrategy\n"
            "IStrategy = object\n"
            "class BoundedEmaPullback(IStrategy):\n    timeframe = '5m'\n"
        ),
        (
            "class BoundedEmaPullback(IStrategy):\n    timeframe = '5m'\n\n"
            "class HiddenStrategy(IStrategy):\n    timeframe = '5m'\n"
        ),
        (
            "from freqtrade.strategy import IStrategy\n"
            "class BoundedEmaPullback(IStrategy):\n"
            "    timeframe = '5m'\n"
            "    timeframe += 'x'\n"
        ),
        (
            "from freqtrade.strategy import IStrategy\n"
            "class BoundedEmaPullback(IStrategy):\n"
            "    timeframe = '5m'\n"
            "    del timeframe\n"
        ),
        (
            "from freqtrade.strategy import IStrategy\n"
            "class BoundedEmaPullback(IStrategy):\n"
            "    timeframe = '5m'\n"
            "    timeframe = '5m'\n"
        ),
    )
    for code in cases:
        with pytest.raises(codex_generation.GenerationContractError):
            codex_generation.parse_candidate_output(
                _candidate_output(code=code), timeframe="5m"
            )


def test_t0_prompt_serializes_only_bounded_allowlisted_context() -> None:
    request = codex_generation.validate_generation_request(VALID_REQUEST)
    profile = {
        "id": "profile-btc-5m",
        "name": "BTC 5m",
        "domain": "OKX_CRYPTO_PERP",
        "exchange": "okx",
        "trading_mode": "futures",
        "margin_mode": "isolated",
        "pairs": ["BTC/USDT:USDT"],
        "timeframe": "5m",
        "detail_timeframe": None,
        "secret_path": "/must/not/leak",
    }
    parent = {
        "id": "candidate-parent",
        "display_name": "Parent",
        "class_name": "ParentStrategy",
        "timeframe": "5m",
        "strategy_family": "trend",
        "idea": "parent idea",
        "expected_failure_mode": None,
        "code_text": "class ParentStrategy(IStrategy):\n    timeframe = '5m'\n",
        "code_sha256": "a" * 64,
        "metadata": {"credential": "must-not-leak"},
    }
    prompt = codex_generation.build_prompt(request, profile, parent)
    assert b"secret_path" not in prompt
    assert b"must/not/leak" not in prompt
    assert b"credential" not in prompt
    assert len(prompt) <= codex_generation.MAX_PROMPT_BYTES

    parent["code_text"] = "x" * codex_generation.MAX_PROMPT_BYTES
    with pytest.raises(codex_generation.GenerationContractError):
        codex_generation.build_prompt(request, profile, parent)


def test_t0_review_transition_is_one_way_and_idempotent() -> None:
    pending = codex_generation.build_candidate_metadata(
        model=None,
        parent_candidate_id=None,
        created_at="2026-08-31T00:00:00.000Z",
    )
    approved, changed = codex_generation.transition_review_metadata(
        pending,
        "APPROVED",
        decided_at="2026-08-31T00:01:00.000Z",
    )
    assert changed is True
    assert approved["review"]["status"] == "APPROVED"
    assert approved["generation"] == pending["generation"]

    repeated, changed = codex_generation.transition_review_metadata(
        approved,
        "APPROVED",
        decided_at="later-must-not-rewrite",
    )
    assert changed is False
    assert repeated == approved

    with pytest.raises(codex_generation.GenerationContractError):
        codex_generation.transition_review_metadata(
            approved,
            "REJECTED",
            decided_at="2026-08-31T00:02:00.000Z",
        )


def test_t0_public_generation_rejects_unknown_request_input_and_report_fields(
    tmp_path: Path,
) -> None:
    database = _database_with_profile(tmp_path)
    request = codex_generation.validate_generation_request(VALID_REQUEST)
    mutations = (
        ("request", lambda value: value.update({"env": {"TOKEN": "secret"}})),
        ("input", lambda value: value["input"].update({"path": "/private/leak"})),
    )
    for _label, mutate in mutations:
        generation_id = str(uuid4())
        codex_generation.start_generation(
            database,
            generation_id,
            request,
            model=None,
            started_at="2026-08-31T00:00:01.000Z",
        )
        connection = sqlite3.connect(database)
        try:
            document = json.loads(
                connection.execute(
                    "SELECT request_json FROM generation_runs WHERE id = ?",
                    (generation_id,),
                ).fetchone()[0]
            )
            mutate(document)
            connection.execute(
                "UPDATE generation_runs SET request_json = ? WHERE id = ?",
                (json.dumps(document, separators=(",", ":")), generation_id),
            )
            connection.commit()
        finally:
            connection.close()
        with pytest.raises(codex_generation.GenerationContractError) as exc_info:
            codex_generation.load_generation(database, generation_id)
        assert exc_info.value.code == "generation_state_invalid"
        assert "/private/leak" not in exc_info.value.message
        assert "TOKEN" not in exc_info.value.message

    generation_id = str(uuid4())
    codex_generation.start_generation(
        database,
        generation_id,
        request,
        model=None,
        started_at="2026-08-31T00:00:02.000Z",
    )
    connection = sqlite3.connect(database)
    try:
        connection.execute(
            "UPDATE generation_runs SET parse_report_json = ? WHERE id = ?",
            ('{"path":"/private/report"}', generation_id),
        )
        connection.commit()
    finally:
        connection.close()
    with pytest.raises(codex_generation.GenerationContractError) as exc_info:
        codex_generation.load_generation(database, generation_id)
    assert exc_info.value.code == "generation_state_invalid"
    assert "/private/report" not in exc_info.value.message


def test_t1_review_rejects_non_slice_request_and_changed_provenance_before_write(
    tmp_path: Path,
) -> None:
    database = _database_with_profile(tmp_path)
    timestamp = "2026-08-31T00:00:01.000Z"
    source = (
        "from freqtrade.strategy import IStrategy\n\n"
        "class ImportedPending(IStrategy):\n"
        "    timeframe = '5m'\n"
    )
    metadata = codex_generation.build_candidate_metadata(
        model=None,
        parent_candidate_id=None,
        created_at=timestamp,
    )
    connection = sqlite3.connect(database)
    try:
        connection.execute(
            """
            INSERT INTO generation_runs (
                id, research_profile_id, source, model, status,
                request_json, response_raw_text, response_json,
                returned_strategy_count, parse_report_json, error_message,
                started_at, finished_at, created_at, updated_at
            ) VALUES (
                'imported-run', 'profile-btc-5m', 'CODEX', NULL, 'COMPLETED',
                '{"kind":"research_bundle_import"}', NULL, NULL,
                1, '{}', NULL, ?, ?, ?, ?
            )
            """,
            (timestamp, timestamp, timestamp, timestamp),
        )
        connection.execute(
            """
            INSERT INTO candidates (
                id, generation_run_id, source_item_index, parent_candidate_id,
                display_name, class_name, timeframe, code_text, code_sha256,
                metadata_json, created_at, updated_at
            ) VALUES (
                'imported-candidate', 'imported-run', 0, NULL,
                'Imported Pending', 'ImportedPending', '5m', ?, ?, ?, ?, ?
            )
            """,
            (
                source,
                hashlib.sha256(source.encode("utf-8")).hexdigest(),
                json.dumps(metadata, separators=(",", ":")),
                timestamp,
                timestamp,
            ),
        )
        connection.commit()
    finally:
        connection.close()
    with pytest.raises(codex_generation.GenerationContractError) as exc_info:
        codex_generation.review_generation(
            database,
            "imported-run",
            "APPROVED",
            decided_at="2026-08-31T00:00:02.000Z",
        )
    assert exc_info.value.code == "generation_not_found"
    connection = sqlite3.connect(database)
    try:
        imported_metadata = json.loads(
            connection.execute(
                "SELECT metadata_json FROM candidates WHERE id = 'imported-candidate'"
            ).fetchone()[0]
        )
    finally:
        connection.close()
    assert imported_metadata["review"]["status"] == "PENDING"

    generation_id = str(uuid4())
    prepared = codex_generation.start_generation(
        database,
        generation_id,
        codex_generation.validate_generation_request(VALID_REQUEST),
        model=None,
        started_at="2026-08-31T00:00:03.000Z",
    )
    output = _candidate_output()
    generated = codex_generation.parse_candidate_output(output, timeframe="5m")
    candidate_id = codex_generation.complete_generation(
        database,
        prepared,
        generated,
        raw_output=output,
        jsonl_summary={"event_count": 4, "tool_event_count": 0},
        finished_at="2026-08-31T00:00:04.000Z",
    )
    connection = sqlite3.connect(database)
    try:
        changed = json.loads(
            connection.execute(
                "SELECT metadata_json FROM candidates WHERE id = ?", (candidate_id,)
            ).fetchone()[0]
        )
        changed["provenance"]["contract"] = "not-issue-28"
        connection.execute(
            "UPDATE candidates SET metadata_json = ? WHERE id = ?",
            (json.dumps(changed, separators=(",", ":")), candidate_id),
        )
        connection.commit()
    finally:
        connection.close()
    with pytest.raises(codex_generation.GenerationContractError) as exc_info:
        codex_generation.review_generation(
            database,
            generation_id,
            "APPROVED",
            decided_at="2026-08-31T00:00:05.000Z",
        )
    assert exc_info.value.code == "generation_state_invalid"
    connection = sqlite3.connect(database)
    try:
        unchanged = json.loads(
            connection.execute(
                "SELECT metadata_json FROM candidates WHERE id = ?", (candidate_id,)
            ).fetchone()[0]
        )
    finally:
        connection.close()
    assert unchanged["review"]["status"] == "PENDING"


def test_t1_generation_database_success_is_atomic_and_review_is_cas(
    tmp_path: Path,
) -> None:
    database = _database_with_profile(tmp_path)
    generation_id = str(uuid4())
    prepared = codex_generation.start_generation(
        database,
        generation_id,
        codex_generation.validate_generation_request(VALID_REQUEST),
        model=None,
        started_at="2026-08-31T00:00:01.000Z",
    )

    connection = sqlite3.connect(database)
    try:
        running = connection.execute(
            """
            SELECT source, model, status, response_raw_text, response_json,
                   returned_strategy_count, finished_at
            FROM generation_runs WHERE id = ?
            """,
            (generation_id,),
        ).fetchone()
        assert running == ("CODEX", None, "RUNNING", None, None, 0, None)
        assert connection.execute(
            "SELECT COUNT(*) FROM candidates WHERE generation_run_id = ?",
            (generation_id,),
        ).fetchone()[0] == 0
    finally:
        connection.close()

    output = _candidate_output()
    candidate = codex_generation.parse_candidate_output(output, timeframe="5m")
    candidate_id = codex_generation.complete_generation(
        database,
        prepared,
        candidate,
        raw_output=output,
        jsonl_summary={
            "event_count": 4,
            "thread_started": True,
            "turn_completed": True,
            "tool_event_count": 0,
        },
        finished_at="2026-08-31T00:00:02.000Z",
    )
    public = codex_generation.load_generation(database, generation_id)
    assert public["status"] == "COMPLETED"
    assert public["returned_strategy_count"] == 1
    assert public["candidate"]["id"] == candidate_id
    assert public["candidate"]["review_status"] == "PENDING"

    approved = codex_generation.review_generation(
        database,
        generation_id,
        "APPROVED",
        decided_at="2026-08-31T00:00:03.000Z",
    )
    assert approved["candidate"]["review_status"] == "APPROVED"
    assert codex_generation.review_generation(
        database,
        generation_id,
        "APPROVED",
        decided_at="must-not-rewrite",
    ) == approved
    with pytest.raises(codex_generation.GenerationContractError):
        codex_generation.review_generation(
            database,
            generation_id,
            "REJECTED",
            decided_at="2026-08-31T00:00:04.000Z",
        )

    connection = sqlite3.connect(database)
    try:
        assert connection.execute("SELECT COUNT(*) FROM research_runs").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM backtest_executions").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM releases").fetchone()[0] == 0
    finally:
        connection.close()


def test_t1_generation_failure_and_duplicate_leave_zero_candidates(
    tmp_path: Path,
) -> None:
    database = _database_with_profile(tmp_path)
    first_id = str(uuid4())
    request = codex_generation.validate_generation_request(VALID_REQUEST)
    first = codex_generation.start_generation(
        database,
        first_id,
        request,
        model="fixed-model",
        started_at="2026-08-31T00:00:01.000Z",
    )
    output = _candidate_output()
    candidate = codex_generation.parse_candidate_output(output, timeframe="5m")
    codex_generation.complete_generation(
        database,
        first,
        candidate,
        raw_output=output,
        jsonl_summary={"event_count": 1, "tool_event_count": 0},
        finished_at="2026-08-31T00:00:02.000Z",
    )

    duplicate_id = str(uuid4())
    duplicate = codex_generation.start_generation(
        database,
        duplicate_id,
        request,
        model="fixed-model",
        started_at="2026-08-31T00:00:03.000Z",
    )
    with pytest.raises(
        codex_generation.GenerationContractError, match="already exists"
    ) as exc_info:
        codex_generation.complete_generation(
            database,
            duplicate,
            candidate,
            raw_output=output,
            jsonl_summary={"event_count": 1, "tool_event_count": 0},
            finished_at="2026-08-31T00:00:04.000Z",
        )
    assert exc_info.value.status == 409
    assert exc_info.value.existing_candidate_id is not None
    duplicate_public = codex_generation.load_generation(database, duplicate_id)
    assert duplicate_public["status"] == "FAILED"
    assert duplicate_public["error_code"] == "DUPLICATE_CODE_SHA256"
    assert duplicate_public["candidate"] is None

    failed_id = str(uuid4())
    codex_generation.start_generation(
        database,
        failed_id,
        request,
        model=None,
        started_at="2026-08-31T00:00:05.000Z",
    )
    assert codex_generation.fail_generation(
        database,
        failed_id,
        error_code="CODEX_NONZERO",
        error_message="Codex process exited unsuccessfully",
        finished_at="2026-08-31T00:00:06.000Z",
    ) == "FAILED"
    assert codex_generation.fail_generation(
        database,
        failed_id,
        error_code="CODEX_NONZERO",
        error_message="must remain idempotent",
        finished_at="later",
    ) == "FAILED"
    failed = codex_generation.load_generation(database, failed_id)
    assert failed["status"] == "FAILED"
    assert failed["returned_strategy_count"] == 0
    assert failed["candidate"] is None


def test_t1_approved_candidate_is_reused_exactly_by_existing_importer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle_root = tmp_path / "bundle"
    shutil.copytree(FIXTURE_ROOT, bundle_root)
    generated_source = (
        "from freqtrade.strategy import IStrategy\n\n"
        "class StrategyTestV3Futures(IStrategy):\n"
        "    timeframe = \"5m\"\n"
    )
    generated_sha256 = hashlib.sha256(generated_source.encode("utf-8")).hexdigest()
    real_parser = research_bundle_module.parse_backtest_artifact

    def parse_generated_fixture(*args, **kwargs):
        parsed = real_parser(*args, **kwargs)
        return replace(
            parsed,
            strategy_source=generated_source,
            strategy_sha256=generated_sha256,
        )

    monkeypatch.setattr(
        research_bundle_module, "parse_backtest_artifact", parse_generated_fixture
    )
    bundle = validate_research_bundle(bundle_root, MANIFEST_NAME)
    profile_contract = research_bundle_module._profile_contract(bundle)
    database = tmp_path / "lab.sqlite"
    init_database(database)
    profile_id = "profile-fixture-5m"
    created_at = "2026-09-01T00:00:00.000Z"
    with get_connection(database) as connection:
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
                :min_holdout_trades, :min_profit_factor, 1,
                :created_at, :updated_at
            )
            """,
            {
                **profile_contract,
                "id": profile_id,
                "created_at": created_at,
                "updated_at": created_at,
            },
        )
        connection.commit()

    manifest_path = bundle_root / MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    request = codex_generation.validate_generation_request(
        {
            "profile_id": profile_id,
            "idea": manifest["candidate"]["idea"],
            "strategy_family": manifest["candidate"]["strategy_family"],
            "expected_failure_mode": manifest["candidate"][
                "expected_failure_mode"
            ],
        }
    )
    generation_id = str(uuid4())
    prepared = codex_generation.start_generation(
        database,
        generation_id,
        request,
        model=None,
        started_at="2026-09-01T00:00:01.000Z",
    )
    artifact = bundle.artifacts[0][1]
    raw_output = json.dumps(
        {
            "display_name": manifest["candidate"]["display_name"],
            "class_name": manifest["candidate"]["class_name"],
            "code_text": generated_source,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    generated = codex_generation.parse_candidate_output(
        raw_output, timeframe=artifact.timeframe
    )
    candidate_id = codex_generation.complete_generation(
        database,
        prepared,
        generated,
        raw_output=raw_output,
        jsonl_summary={"event_count": 4, "tool_event_count": 0},
        finished_at="2026-09-01T00:00:02.000Z",
    )
    codex_generation.review_generation(
        database,
        generation_id,
        "APPROVED",
        decided_at="2026-09-01T00:00:03.000Z",
    )
    with get_connection(database, read_only=True) as connection:
        metadata = json.loads(
            connection.execute(
                "SELECT metadata_json FROM candidates WHERE id = ?",
                (candidate_id,),
            ).fetchone()[0]
        )
    manifest["candidate"]["metadata"] = metadata
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    imported = import_research_bundle(database, bundle_root, MANIFEST_NAME)

    assert imported.profile_reused is True
    assert imported.candidate_reused is True
    assert imported.profile_id == profile_id
    assert imported.generation_run_id == generation_id
    assert imported.candidate_id == candidate_id
    with get_connection(database, read_only=True) as connection:
        assert connection.execute("SELECT COUNT(*) FROM research_runs").fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM backtest_executions"
        ).fetchone()[0] == 3
        assert connection.execute("SELECT COUNT(*) FROM releases").fetchone()[0] == 0
