"""Read-only strategy library query and local HTTP presentation.

The module deliberately stays inside one process and Python's standard library.
It never initializes the database or writes business records.
"""

from __future__ import annotations

import html
import json
import math
import os
import sqlite3
import stat
from contextlib import closing
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple, Union
from urllib.parse import parse_qs, urlencode, urlsplit


SCHEMA_VERSION = 1
LOOPBACK_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
PathLike = Union[str, Path]


class StrategyLibraryError(RuntimeError):
    """Base error for read-only database and presentation failures."""


class ProfileNotFoundError(StrategyLibraryError):
    """Raised when a requested Research Profile does not exist."""


class ProfileRequiredError(StrategyLibraryError):
    """Raised when an API request cannot select one profile honestly."""


class BadRequestError(StrategyLibraryError):
    """Raised when an HTTP query is malformed or unsupported."""


STRATEGY_LIBRARY_SQL = """
WITH
scoped_candidates AS (
    SELECT
        c.id,
        c.display_name,
        c.class_name,
        c.timeframe,
        c.strategy_family,
        c.created_at
    FROM candidates AS c
    JOIN generation_runs AS g ON g.id = c.generation_run_id
    WHERE g.research_profile_id = :profile_id
),
scoped_runs AS (
    SELECT r.*
    FROM research_runs AS r
    JOIN scoped_candidates AS c ON c.id = r.candidate_id
    WHERE r.research_profile_id = :profile_id
),
status_ranked AS (
    SELECT
        r.*,
        ROW_NUMBER() OVER (
            PARTITION BY r.candidate_id
            ORDER BY r.created_at DESC, r.id DESC
        ) AS candidate_rank
    FROM scoped_runs AS r
),
run_counts AS (
    SELECT
        candidate_id,
        SUM(CASE WHEN status = 'COMPLETED' THEN 1 ELSE 0 END)
            AS completed_count,
        SUM(
            CASE
                WHEN status = 'COMPLETED' AND verdict = 'PASSED' THEN 1
                ELSE 0
            END
        ) AS passed_count
    FROM scoped_runs
    GROUP BY candidate_id
),
eligible_summaries AS (
    SELECT
        r.id AS research_run_id,
        r.candidate_id,
        r.verdict,
        r.created_at,
        r.finished_at,
        development.profit_pct AS development_profit_pct,
        holdout.profit_pct AS holdout_profit_pct,
        holdout.max_drawdown_pct AS holdout_max_drawdown_pct,
        holdout.profit_factor AS holdout_profit_factor,
        holdout.total_trades AS holdout_total_trades,
        CAST(json_extract(holdout.metrics_json, '$.losses') AS INTEGER)
            AS holdout_losses,
        stress.profit_pct AS stress_profit_pct
    FROM scoped_runs AS r
    JOIN backtest_executions AS development
      ON development.research_run_id = r.id
     AND development.scenario = 'DEVELOPMENT'
    JOIN backtest_executions AS holdout
      ON holdout.research_run_id = r.id
     AND holdout.scenario = 'HOLDOUT'
    JOIN backtest_executions AS stress
      ON stress.research_run_id = r.id
     AND stress.scenario = 'HOLDOUT_STRESS'
    WHERE r.status = 'COMPLETED'
      AND r.finished_at IS NOT NULL
      AND development.status = 'SUCCEEDED'
      AND holdout.status = 'SUCCEEDED'
      AND stress.status = 'SUCCEEDED'
      AND typeof(development.profit_pct) IN ('integer', 'real')
      AND typeof(holdout.profit_pct) IN ('integer', 'real')
      AND typeof(holdout.max_drawdown_pct) IN ('integer', 'real')
      AND typeof(holdout.profit_factor) IN ('integer', 'real')
      AND typeof(holdout.total_trades) = 'integer'
      AND typeof(stress.profit_pct) IN ('integer', 'real')
      AND development.profit_pct BETWEEN -1.7976931348623157e308
                                         AND 1.7976931348623157e308
      AND holdout.profit_pct BETWEEN -1.7976931348623157e308
                                     AND 1.7976931348623157e308
      AND stress.profit_pct BETWEEN -1.7976931348623157e308
                                    AND 1.7976931348623157e308
      AND holdout.max_drawdown_pct BETWEEN 0 AND 1.7976931348623157e308
      AND holdout.profit_factor BETWEEN 0 AND 1.7976931348623157e308
      AND holdout.total_trades >= 0
      AND json_type(holdout.metrics_json, '$.losses') = 'integer'
      AND json_extract(holdout.metrics_json, '$.losses') >= 0
),
summary_ranked AS (
    SELECT
        s.*,
        ROW_NUMBER() OVER (
            PARTITION BY s.candidate_id
            ORDER BY
                s.finished_at DESC,
                s.created_at DESC,
                s.research_run_id DESC
        ) AS candidate_rank
    FROM eligible_summaries AS s
)
SELECT
    c.id AS candidate_id,
    c.display_name,
    c.class_name,
    c.timeframe,
    c.strategy_family,
    status_run.id AS latest_status_run_id,
    status_run.status AS latest_status,
    status_run.stage AS latest_status_stage,
    status_run.verdict AS latest_status_verdict,
    status_run.created_at AS latest_status_created_at,
    status_run.started_at AS latest_status_started_at,
    status_run.finished_at AS latest_status_finished_at,
    summary.research_run_id AS latest_summary_run_id,
    summary.verdict AS latest_summary_verdict,
    summary.finished_at AS latest_summary_finished_at,
    summary.development_profit_pct,
    summary.holdout_profit_pct,
    summary.holdout_max_drawdown_pct,
    summary.holdout_profit_factor,
    summary.holdout_total_trades,
    summary.holdout_losses,
    summary.stress_profit_pct,
    COALESCE(counts.completed_count, 0) AS completed_count,
    COALESCE(counts.passed_count, 0) AS passed_count,
    CASE
        WHEN summary.research_run_id IS NOT NULL AND EXISTS (
            SELECT 1
            FROM releases AS release
            WHERE release.research_run_id = summary.research_run_id
              AND release.archived_at IS NULL
        ) THEN 1
        ELSE 0
    END AS has_release
FROM scoped_candidates AS c
LEFT JOIN status_ranked AS status_run
  ON status_run.candidate_id = c.id
 AND status_run.candidate_rank = 1
LEFT JOIN summary_ranked AS summary
  ON summary.candidate_id = c.id
 AND summary.candidate_rank = 1
LEFT JOIN run_counts AS counts ON counts.candidate_id = c.id
ORDER BY c.created_at DESC, c.id DESC
"""


def _resolve_database_path(database: PathLike) -> Path:
    try:
        value = Path(database).expanduser()
        if value.is_symlink():
            raise StrategyLibraryError("database path must not be a symlink")
        path = value.resolve(strict=True)
    except StrategyLibraryError:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        raise StrategyLibraryError(
            f"database path cannot be resolved safely: {exc}"
        ) from exc
    try:
        mode = os.lstat(path).st_mode
    except OSError as exc:
        raise StrategyLibraryError(f"database cannot be inspected safely: {exc}") from exc
    if not stat.S_ISREG(mode):
        raise StrategyLibraryError("database path must be a regular file")
    return path


def _open_read_only_database(database: PathLike) -> sqlite3.Connection:
    path = _resolve_database_path(database)
    uri = f"{path.as_uri()}?mode=ro"
    try:
        connection = sqlite3.connect(uri, uri=True)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA query_only = ON")
        query_only = connection.execute("PRAGMA query_only").fetchone()
        if query_only is None or int(query_only[0]) != 1:
            raise StrategyLibraryError("SQLite query_only mode could not be enabled")
        schema_row = connection.execute("PRAGMA user_version").fetchone()
        if schema_row is None or int(schema_row[0]) != SCHEMA_VERSION:
            raise StrategyLibraryError(
                f"database schema version must be {SCHEMA_VERSION}"
            )
        return connection
    except StrategyLibraryError:
        try:
            connection.close()
        except (NameError, sqlite3.Error):
            pass
        raise
    except sqlite3.Error as exc:
        try:
            connection.close()
        except (NameError, sqlite3.Error):
            pass
        raise StrategyLibraryError(f"database cannot be opened read-only: {exc}") from exc


def _profile_rows(connection: sqlite3.Connection) -> List[Dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT id, name, is_default
        FROM research_profiles
        ORDER BY is_default DESC, name COLLATE NOCASE, id
        """
    ).fetchall()
    return [
        {"id": row["id"], "name": row["name"], "is_default": bool(row["is_default"])}
        for row in rows
    ]


def _select_profile(
    profiles: List[Dict[str, Any]],
    requested_profile_id: Optional[str],
    *,
    require_unambiguous: bool,
) -> Optional[Dict[str, Any]]:
    if requested_profile_id is not None:
        for profile in profiles:
            if profile["id"] == requested_profile_id:
                return profile
        raise ProfileNotFoundError(
            f"research profile {requested_profile_id!r} was not found"
        )
    if not profiles:
        return None
    default_profiles = [profile for profile in profiles if profile["is_default"]]
    if len(default_profiles) == 1:
        return default_profiles[0]
    if len(profiles) == 1:
        return profiles[0]
    if require_unambiguous:
        raise ProfileRequiredError(
            "profile_id is required when multiple profiles have no default"
        )
    return None


def _finite_float(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise StrategyLibraryError(f"database returned a non-numeric {label}")
    number = float(value)
    if not math.isfinite(number):
        raise StrategyLibraryError(f"database returned a non-finite {label}")
    return number


def _card_from_row(row: sqlite3.Row) -> Dict[str, Any]:
    latest_status = None
    if row["latest_status_run_id"] is not None:
        latest_status = {
            "research_run_id": row["latest_status_run_id"],
            "status": row["latest_status"],
            "stage": row["latest_status_stage"],
            "verdict": row["latest_status_verdict"],
            "created_at": row["latest_status_created_at"],
            "started_at": row["latest_status_started_at"],
            "finished_at": row["latest_status_finished_at"],
        }

    latest_summary = None
    if row["latest_summary_run_id"] is not None:
        profit_factor = _finite_float(
            row["holdout_profit_factor"], "holdout profit_factor"
        )
        losses = int(row["holdout_losses"])
        latest_summary = {
            "research_run_id": row["latest_summary_run_id"],
            "verdict": row["latest_summary_verdict"],
            "finished_at": row["latest_summary_finished_at"],
            "development_profit_pct": _finite_float(
                row["development_profit_pct"], "development profit_pct"
            ),
            "holdout_profit_pct": _finite_float(
                row["holdout_profit_pct"], "holdout profit pct"
            ),
            "holdout_max_drawdown_pct": _finite_float(
                row["holdout_max_drawdown_pct"], "holdout max drawdown pct"
            ),
            "holdout_profit_factor": profit_factor,
            "holdout_total_trades": int(row["holdout_total_trades"]),
            "holdout_losses": losses,
            "stress_profit_pct": _finite_float(
                row["stress_profit_pct"], "stress profit pct"
            ),
            "profit_factor_interpretation": (
                "NO_LOSS_SAMPLE"
                if profit_factor == 0.0 and losses == 0
                else "NUMERIC"
            ),
            "has_release": bool(row["has_release"]),
        }

    if latest_summary is not None:
        summary_state = "COMPLETE"
    elif latest_status is None:
        summary_state = "NO_COMPLETE_RESULT"
    else:
        summary_state = "INCOMPLETE_DATA"
    return {
        "candidate": {
            "id": row["candidate_id"],
            "display_name": row["display_name"],
            "class_name": row["class_name"],
            "timeframe": row["timeframe"],
            "strategy_family": row["strategy_family"],
        },
        "latest_status": latest_status,
        "latest_summary": latest_summary,
        "completed_count": int(row["completed_count"]),
        "passed_count": int(row["passed_count"]),
        "summary_state": summary_state,
    }


def _query_cards(
    connection: sqlite3.Connection, profile_id: str
) -> List[Dict[str, Any]]:
    rows = connection.execute(
        STRATEGY_LIBRARY_SQL,
        {"profile_id": profile_id},
    ).fetchall()
    return [_card_from_row(row) for row in rows]


def validate_strategy_library_database(database: PathLike) -> Path:
    """Fail before listening if the database cannot serve the read model."""
    path = _resolve_database_path(database)
    with closing(_open_read_only_database(path)) as connection:
        try:
            connection.execute("BEGIN")
            _profile_rows(connection)
            _query_cards(connection, "__schema_validation__")
            connection.rollback()
        except (sqlite3.Error, StrategyLibraryError) as exc:
            if connection.in_transaction:
                connection.rollback()
            if isinstance(exc, StrategyLibraryError):
                raise
            raise StrategyLibraryError(
                f"database cannot serve the strategy library: {exc}"
            ) from exc
    return path


def load_strategy_library(
    database: PathLike,
    profile_id: Optional[str] = None,
    *,
    require_unambiguous_profile: bool = False,
) -> Dict[str, Any]:
    """Return one profile-scoped, JSON-safe strategy-library read model."""
    with closing(_open_read_only_database(database)) as connection:
        try:
            connection.execute("BEGIN")
            profiles = _profile_rows(connection)
            selected = _select_profile(
                profiles,
                profile_id,
                require_unambiguous=require_unambiguous_profile,
            )
            strategies = _query_cards(connection, selected["id"]) if selected else []
            connection.rollback()
        except (sqlite3.Error, StrategyLibraryError) as exc:
            if connection.in_transaction:
                connection.rollback()
            if isinstance(exc, StrategyLibraryError):
                raise
            raise StrategyLibraryError(f"strategy library query failed: {exc}") from exc
    return {
        "profile": selected,
        "profiles": profiles,
        "strategies": strategies,
    }


def _escape(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _format_percentage(value: float) -> str:
    return f"{value:+.2f}%"


def _status_presentation(status: Optional[Mapping[str, Any]]) -> Tuple[str, str]:
    if status is None:
        return "未研究", "neutral"
    raw_status = status["status"]
    verdict = status["verdict"]
    if raw_status == "COMPLETED":
        if verdict == "PASSED":
            return "已完成 · 通过", "positive"
        if verdict == "REJECTED":
            return "已完成 · 拒绝", "negative"
        return "已完成 · 未评审", "neutral"
    labels = {
        "PENDING": ("等待研究", "neutral"),
        "RUNNING": ("研究中", "running"),
        "FAILED": ("失败", "negative"),
        "INTERRUPTED": ("中断待确认", "warning"),
        "CANCELLED": ("已取消", "neutral"),
    }
    return labels.get(str(raw_status), ("未知状态", "warning"))


def _metric(label: str, value: str, note: str = "") -> str:
    note_html = f'<span class="metric-note">{_escape(note)}</span>' if note else ""
    return (
        '<div class="metric">'
        f'<span class="metric-label">{_escape(label)}</span>'
        f'<strong>{_escape(value)}</strong>{note_html}'
        "</div>"
    )


def _render_card(card: Mapping[str, Any]) -> str:
    candidate = card["candidate"]
    summary = card["latest_summary"]
    status_label, tone = _status_presentation(card["latest_status"])
    release = (
        '<span class="release-badge">Release</span>'
        if summary is not None and summary["has_release"]
        else ""
    )
    summary_context = ""
    if (
        summary is not None
        and card["latest_status"] is not None
        and card["latest_status"]["research_run_id"]
        != summary["research_run_id"]
    ):
        summary_context = (
            '<div class="summary-context">'
            "最近完整摘要（非当前 Run） · 完成于 "
            f'{_escape(summary["finished_at"])}</div>'
        )
    if summary is None:
        state_message = (
            "尚未研究"
            if card["summary_state"] == "NO_COMPLETE_RESULT"
            else "无完整结果 / 数据不完整"
        )
        metrics_html = (
            '<div class="empty-result">'
            f"{_escape(state_message)}"
            '<span>需要同一 ResearchRun 的三场景完整结果</span>'
            "</div>"
        )
    else:
        if summary["profit_factor_interpretation"] == "NO_LOSS_SAMPLE":
            profit_factor = _metric(
                "Holdout PF",
                "无亏损样本",
                "不可直接解释",
            )
        else:
            profit_factor = _metric(
                "Holdout PF", f"{summary['holdout_profit_factor']:.2f}"
            )
        metrics_html = (
            '<div class="metrics">'
            + _metric(
                "Holdout 收益",
                _format_percentage(summary["holdout_profit_pct"]),
            )
            + _metric(
                "Holdout 回撤",
                f"{summary['holdout_max_drawdown_pct']:.2f}%",
            )
            + profit_factor
            + _metric("Holdout 交易", str(summary["holdout_total_trades"]))
            + _metric(
                "Development 收益",
                _format_percentage(summary["development_profit_pct"]),
            )
            + _metric(
                "Stress 收益",
                _format_percentage(summary["stress_profit_pct"]),
            )
            + "</div>"
        )
    family = (
        f'<span class="family">{_escape(candidate["strategy_family"])}</span>'
        if candidate["strategy_family"]
        else ""
    )
    return (
        '<article class="strategy-card">'
        '<div class="card-heading">'
        '<div class="identity">'
        f'<h2>{_escape(candidate["display_name"])}</h2>'
        f'<p>{_escape(candidate["class_name"])} · {_escape(candidate["timeframe"])}</p>'
        "</div>"
        '<div class="badges">'
        f"{family}{release}"
        f'<span class="status {tone}">{_escape(status_label)}</span>'
        "</div></div>"
        f"{summary_context}"
        f"{metrics_html}"
        '<div class="counts">'
        f'<span>完成 <strong>{int(card["completed_count"])}</strong></span>'
        f'<span>通过 <strong>{int(card["passed_count"])}</strong></span>'
        "</div>"
        "</article>"
    )


def render_strategy_library_page(model: Mapping[str, Any]) -> bytes:
    """Render the profile-scoped list without client-side state."""
    profiles = model["profiles"]
    selected = model["profile"]
    selected_id = selected["id"] if selected else None
    options = ['<option value="">请选择 Research Profile</option>']
    for profile in profiles:
        is_selected = " selected" if profile["id"] == selected_id else ""
        suffix = " · 默认" if profile["is_default"] else ""
        options.append(
            f'<option value="{_escape(profile["id"])}"{is_selected}>'
            f'{_escape(profile["name"] + suffix)}</option>'
        )
    if not profiles:
        content = (
            '<section class="page-empty"><h2>还没有 Research Profile</h2>'
            '<p>先初始化并导入研究数据；页面不会写入业务记录。</p></section>'
        )
    elif selected is None:
        content = (
            '<section class="page-empty"><h2>请选择 Research Profile</h2>'
            '<p>存在多个 Profile 且没有默认项，策略状态和计数不会跨 Profile 混合。</p></section>'
        )
    elif not model["strategies"]:
        content = (
            '<section class="page-empty"><h2>此 Profile 尚无 Candidate</h2>'
            '<p>这里只展示已经写入研究数据库的真实记录。</p></section>'
        )
    else:
        content = '<main class="card-list">' + "".join(
            _render_card(card) for card in model["strategies"]
        ) + "</main>"
    profile_form = ""
    if profiles:
        profile_form = (
            '<form class="profile-form" method="get" action="/">'
            '<label for="profile_id">Research Profile</label>'
            '<select id="profile_id" name="profile_id">'
            + "".join(options)
            + '</select><button type="submit">查看</button></form>'
        )
    page = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>策略库 · freqtrade-lab</title>
  <style>
    :root {{ color-scheme: light; --ink:#17202a; --muted:#6b7280;
      --line:#e5e7eb; --soft:#f7f8fa; --blue:#2563eb; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; background:#fff; color:var(--ink); font:14px/1.45
      -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }}
    .shell {{ width:min(1180px,calc(100% - 32px)); margin:0 auto; padding:28px 0 48px; }}
    .topbar {{ display:flex; align-items:flex-end; justify-content:space-between;
      gap:20px; padding-bottom:18px; border-bottom:1px solid var(--line); }}
    h1 {{ margin:0; font-size:24px; letter-spacing:-.02em; }}
    .subtitle {{ margin:4px 0 0; color:var(--muted); }}
    .profile-form {{ display:flex; align-items:center; gap:8px; }}
    .profile-form label {{ color:var(--muted); font-size:12px; }}
    select,button {{ height:34px; border:1px solid #d1d5db; border-radius:7px;
      background:#fff; color:var(--ink); padding:0 10px; font:inherit; }}
    button {{ cursor:pointer; background:var(--ink); color:#fff; border-color:var(--ink); }}
    .boundary {{ margin:14px 0 18px; padding:9px 11px; border:1px solid #dbeafe;
      border-radius:7px; background:#f8fbff; color:#475569; font-size:12px; }}
    .card-list {{ display:grid; gap:10px; }}
    .strategy-card {{ border:1px solid var(--line); border-radius:10px;
      padding:16px 18px 12px; background:#fff; }}
    .card-heading {{ display:flex; justify-content:space-between; gap:16px; align-items:flex-start; }}
    .identity h2 {{ margin:0; font-size:16px; }}
    .identity p {{ margin:3px 0 0; color:var(--muted); font:12px ui-monospace,SFMono-Regular,monospace; }}
    .badges {{ display:flex; justify-content:flex-end; gap:6px; flex-wrap:wrap; }}
    .status,.family,.release-badge {{ border-radius:999px; padding:3px 8px; font-size:11px;
      white-space:nowrap; background:#f3f4f6; color:#4b5563; }}
    .status.positive {{ color:#047857; background:#ecfdf5; }}
    .status.negative {{ color:#b91c1c; background:#fef2f2; }}
    .status.running {{ color:#1d4ed8; background:#eff6ff; }}
    .status.warning {{ color:#a16207; background:#fefce8; }}
    .release-badge {{ color:#6d28d9; background:#f5f3ff; }}
    .summary-context {{ margin-top:11px; color:#92400e; font-size:11px; }}
    .metrics {{ display:grid; grid-template-columns:repeat(6,minmax(0,1fr));
      margin-top:14px; border:1px solid var(--line); border-radius:8px; overflow:hidden; }}
    .metric {{ min-height:66px; padding:10px 12px; border-right:1px solid var(--line); }}
    .metric:last-child {{ border-right:0; }}
    .metric-label,.metric-note {{ display:block; color:var(--muted); font-size:11px; }}
    .metric strong {{ display:block; margin-top:5px; font-size:15px; font-variant-numeric:tabular-nums; }}
    .metric-note {{ margin-top:1px; font-size:10px; }}
    .empty-result {{ margin-top:14px; padding:14px; border:1px dashed #d1d5db;
      border-radius:8px; color:#374151; }}
    .empty-result span {{ display:block; color:var(--muted); font-size:11px; margin-top:2px; }}
    .counts {{ display:flex; gap:18px; justify-content:flex-end; padding-top:10px;
      color:var(--muted); font-size:12px; }}
    .counts strong {{ color:var(--ink); font-variant-numeric:tabular-nums; }}
    .page-empty {{ margin-top:44px; padding:42px; text-align:center; border:1px dashed #d1d5db;
      border-radius:10px; background:var(--soft); }}
    .page-empty h2 {{ margin:0; font-size:16px; }}
    .page-empty p {{ margin:7px 0 0; color:var(--muted); }}
    footer {{ margin-top:22px; color:var(--muted); font-size:11px; text-align:center; }}
    @media (max-width:900px) {{ .metrics {{ grid-template-columns:repeat(3,1fr); }}
      .metric:nth-child(3) {{ border-right:0; }} .metric {{ border-bottom:1px solid var(--line); }} }}
    @media (max-width:640px) {{ .shell {{ width:min(100% - 20px,1180px); padding-top:18px; }}
      .topbar,.card-heading {{ align-items:stretch; flex-direction:column; }}
      .profile-form {{ display:grid; grid-template-columns:1fr auto; }} .profile-form label {{ grid-column:1/-1; }}
      .metrics {{ grid-template-columns:repeat(2,1fr); }} .metric:nth-child(3) {{ border-right:1px solid var(--line); }}
      .metric:nth-child(even) {{ border-right:0; }} }}
  </style>
</head>
<body><div class="shell">
  <header class="topbar"><div><h1>策略库</h1>
    <p class="subtitle">最近可用的三场景研究摘要</p></div>{profile_form}</header>
  <div class="boundary">只读视图 · COMPLETED 只表示结果组装完整，未评审不等于通过。</div>
  {content}
  <footer>回测摘要仅为研究记录，不代表盈利、可交易性或资金安全。</footer>
</div></body></html>"""
    return page.encode("utf-8")


def _json_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise StrategyLibraryError(f"response cannot be encoded safely: {exc}") from exc


def _profile_query(query: str) -> Optional[str]:
    if not query:
        return None
    try:
        values = parse_qs(query, keep_blank_values=True, strict_parsing=True)
    except ValueError as exc:
        raise BadRequestError("query string is malformed") from exc
    if set(values) - {"profile_id"}:
        raise BadRequestError("only profile_id is supported")
    selected = values.get("profile_id")
    if selected is None:
        return None
    if len(selected) != 1 or not selected[0]:
        raise BadRequestError("profile_id must appear exactly once and be non-empty")
    return selected[0]


class StrategyLibraryRequestHandler(BaseHTTPRequestHandler):
    """A fixed-route handler whose database is supplied by ``create_server``."""

    server_version = "freqtrade-lab"
    sys_version = ""
    database_path: Path

    def _has_expected_host(self) -> bool:
        expected = f"{LOOPBACK_HOST}:{self.server.server_port}"
        return self.headers.get_all("Host", failobj=[]) == [expected]

    def _send(
        self,
        status: int,
        body: bytes,
        content_type: str,
        *,
        head_only: bool = False,
        extra_headers: Optional[Mapping[str, str]] = None,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'none'; style-src 'unsafe-inline'; "
            "form-action 'self'; frame-ancestors 'none'",
        )
        for name, value in (extra_headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        if not head_only:
            self.wfile.write(body)

    def _error(
        self,
        status: int,
        code: str,
        message: str,
        *,
        api: bool,
        head_only: bool,
    ) -> None:
        if api:
            body = _json_bytes({"error": code, "message": message})
            content_type = "application/json; charset=utf-8"
        else:
            body = (
                "<!doctype html><html lang=\"zh-CN\"><meta charset=\"utf-8\">"
                f"<title>{status}</title><h1>{status}</h1><p>{_escape(message)}</p>"
                "</html>"
            ).encode("utf-8")
            content_type = "text/html; charset=utf-8"
        self._send(status, body, content_type, head_only=head_only)

    def _dispatch(self, *, head_only: bool) -> None:
        request = urlsplit(self.path)
        api = request.path == "/api/strategies"
        if not self._has_expected_host():
            self._error(
                400,
                "bad_host",
                "Host 必须使用服务启动时打印的 loopback 地址",
                api=api,
                head_only=head_only,
            )
            return
        if request.path not in ("/", "/api/strategies"):
            self._error(404, "not_found", "页面不存在", api=False, head_only=head_only)
            return
        try:
            profile_id = _profile_query(request.query)
            model = load_strategy_library(
                self.database_path,
                profile_id,
                require_unambiguous_profile=api,
            )
            if api:
                body = _json_bytes(model)
                content_type = "application/json; charset=utf-8"
            else:
                body = render_strategy_library_page(model)
                content_type = "text/html; charset=utf-8"
            self._send(200, body, content_type, head_only=head_only)
        except BadRequestError as exc:
            self._error(400, "bad_request", str(exc), api=api, head_only=head_only)
        except ProfileNotFoundError as exc:
            self._error(404, "profile_not_found", str(exc), api=api, head_only=head_only)
        except ProfileRequiredError as exc:
            self._error(409, "profile_required", str(exc), api=api, head_only=head_only)
        except StrategyLibraryError:
            self._error(
                500,
                "read_failed",
                "策略库暂时无法读取数据库",
                api=api,
                head_only=head_only,
            )

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        self._dispatch(head_only=False)

    def do_HEAD(self) -> None:  # noqa: N802 - stdlib handler API
        self._dispatch(head_only=True)

    def _method_not_allowed(self) -> None:
        api = urlsplit(self.path).path == "/api/strategies"
        if not self._has_expected_host():
            self._error(
                400,
                "bad_host",
                "Host 必须使用服务启动时打印的 loopback 地址",
                api=api,
                head_only=False,
            )
            return
        body = _json_bytes({"error": "method_not_allowed"}) if api else b"Method not allowed"
        self._send(
            405,
            body,
            "application/json; charset=utf-8" if api else "text/plain; charset=utf-8",
            extra_headers={"Allow": "GET, HEAD"},
        )

    do_POST = _method_not_allowed
    do_PUT = _method_not_allowed
    do_PATCH = _method_not_allowed
    do_DELETE = _method_not_allowed


def create_strategy_library_server(
    database: PathLike,
    port: int = DEFAULT_PORT,
) -> HTTPServer:
    """Validate first, then create one loopback-only single-process server."""
    if isinstance(port, bool) or not isinstance(port, int) or not 0 <= port <= 65535:
        raise StrategyLibraryError("port must be an integer from 0 to 65535")
    path = validate_strategy_library_database(database)

    class BoundHandler(StrategyLibraryRequestHandler):
        database_path = path

    try:
        return HTTPServer((LOOPBACK_HOST, port), BoundHandler)
    except OSError as exc:
        raise StrategyLibraryError(f"loopback server cannot start: {exc}") from exc
