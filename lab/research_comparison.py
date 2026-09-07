"""One immutable cost comparison per stage; diagnostic evidence, never a Run.

The native runner and sanitizer produce the inputs. This module executes no
strategy and changes no stage gate, review status, execution, or release.
"""
from contextlib import closing
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import zipfile

from lab.backtest_artifact import (
    ArtifactImportError, parse_backtest_artifact, _strict_json,
)
from lab.database import get_connection
from lab.futures_costs import CONTRACT, FuturesCostError, validate_audit, audit_native_trades, source_identity

SCHEMA = "xrp-weekly-cost-comparison-v1"
STAGES = {"S": None, "D": "DEVELOPMENT", "H": "HOLDOUT", "STRESS": "HOLDOUT_STRESS"}
SHA = re.compile(r"[0-9a-f]{64}\Z")


class ComparisonError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise ComparisonError(message)


def exact(value, keys):
    require(isinstance(value, dict) and set(value) == set(keys.split()), "comparison shape mismatch")
    return value


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def safe_read(path, maximum, label):
    # Reuse the existing descriptor-relative reader, including every parent.
    from lab.holdout_run import _read_regular_relative_at
    path = Path(path)
    require(path.is_absolute() and '..' not in path.parts, 'unsafe evidence path')
    descriptor = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        return _read_regular_relative_at(descriptor, path.relative_to('/'), label, maximum)
    finally:
        os.close(descriptor)


def read_receipt(value):
    exact(value, "path sha256")
    require(isinstance(value["sha256"], str) and SHA.fullmatch(value["sha256"]), "invalid receipt SHA")
    path = Path(value["path"])
    raw = safe_read(path, 2 * 1024 * 1024, "comparison receipt")
    require(digest(raw) == value["sha256"], "comparison receipt changed")
    return _strict_json(raw, "comparison receipt")


def validate_comparisons(values, candidate):
    """Small path-free public/strictreader validation; does not open market files."""
    require(isinstance(values, dict) and 1 <= len(values) <= 4 and set(values) <= set(STAGES), "invalid stages")
    runs = set()
    protocols = set()
    campaigns = set()
    for stage, value in values.items():
        exact(value, "schema candidate_id stage campaign_id research_run_id protocol_sha256 receipt_sha256 raw_source_sha256 stage_source_sha256 primary benchmark verdict recorded_at_utc")
        require(value["schema"] == SCHEMA and value["stage"] == stage and value["candidate_id"] == candidate["id"], "comparison identity mismatch")
        for field in ("protocol_sha256", "receipt_sha256", "raw_source_sha256", "stage_source_sha256"):
            require(isinstance(value[field], str) and SHA.fullmatch(value[field]), "invalid comparison hash")
        protocols.add(value["protocol_sha256"])
        require(isinstance(value["campaign_id"], str) and bool(value["campaign_id"]), "campaign required")
        campaigns.add(value["campaign_id"])
        if stage == "S":
            require(value["research_run_id"] is None, "Search comparison cannot be a Run")
        else:
            require(isinstance(value["research_run_id"], str) and bool(value["research_run_id"]), "real Run required")
            runs.add(value["research_run_id"])
        require(value["verdict"] in {"PASSED", "REJECTED"}, "invalid comparison verdict")
        require(isinstance(value["recorded_at_utc"], str) and datetime.fromisoformat(value["recorded_at_utc"]).utcoffset() == timezone.utc.utcoffset(None), "comparison UTC required")
        for role in ("primary", "benchmark"):
            side = exact(value[role], "archive_sha256 raw_archive_sha256 provenance_sha256 strategy_sha256 config_sha256 source_sha256 attempt_sha256 native_calls net_pct mtm_dd_pct risk_return")
            for key in side:
                if key.endswith("sha256"):
                    require(isinstance(side[key], str) and SHA.fullmatch(side[key]), "invalid evidence SHA")
            require(type(side["native_calls"]) is int and side["native_calls"] == 1, "one native call required")
            for key in ("net_pct", "mtm_dd_pct", "risk_return"):
                require(type(side[key]) in (int, float) and math.isfinite(side[key]), "finite comparison metric required")
            require(side["mtm_dd_pct"] >= 0 and math.isclose(side["risk_return"], side["net_pct"] / max(side["mtm_dd_pct"], 1.0), abs_tol=1e-12), "comparison arithmetic mismatch")
        require(value["primary"]["strategy_sha256"] == candidate["code_sha256"], "comparison Candidate source mismatch")
        passed = value["primary"]["risk_return"] >= value["benchmark"]["risk_return"]
        require(value["verdict"] == ("PASSED" if passed else "REJECTED"), "comparison verdict mismatch")
    require(len(runs) <= 1 and len(protocols) == len(campaigns) == 1, "comparison phases must share Run/protocol/campaign")


def _binding(connection, document, candidate):
    from lab.search_campaign import parse_finalist_projection
    row = connection.execute("SELECT * FROM generation_runs WHERE id=?", (document["campaign_id"],)).fetchone()
    require(row is not None and row["source"] == "MANUAL" and row["status"] == "COMPLETED", "completed Search campaign required")
    parsed = parse_finalist_projection(*(row[k] for k in ("request_json", "response_json", "parse_report_json")))
    identity, binding = parsed["protocol_review_identity"], parsed["binding"]
    require(identity is not None and binding["search_generation_id"] == row["id"]
            and identity["candidate_id"] == candidate["id"] and identity["source_sha256"] == candidate["code_sha256"]
            and binding["generation_run_id"] == candidate["generation_run_id"]
            and identity["protocol_sha256"] == document["protocol"]["sha256"], "immutable single baseline binding required")
    if document["stage"] == "S":
        require(document["research_run_id"] is None, "Search cannot reference a Run")
        parsed['archive_relative'] = json.loads(row['parse_report_json'])['evidence']['attempts'][0]['evidence']['archive']['path']
        return parsed, identity["raw_artifact_sha256"], None
    run = connection.execute("SELECT * FROM research_runs WHERE id=?", (document["research_run_id"],)).fetchone()
    require(run is not None and run["candidate_id"] == candidate["id"] and run["research_profile_id"] == binding["profile_id"], "wrong research Run")
    require(json.loads(run["input_snapshot_json"])["search_finalist_binding"] ==
            {**binding, "profile_snapshot": parsed["profile_snapshot"]}, "Run belongs to another Search")
    execution = connection.execute("SELECT * FROM backtest_executions WHERE research_run_id=? AND scenario=?", (run["id"], STAGES[document["stage"]])).fetchone()
    require(execution is not None and execution["status"] == "SUCCEEDED" and execution["return_code"] == 0 and execution["finished_at"] is not None, "real completed scenario required before opening artifacts")
    metrics = json.loads(execution["metrics_json"])
    parsed['archive_path'] = execution['result_archive_path']
    return parsed, None, {k: metrics["artifact"][k] for k in ("archive_sha256", "provenance_sha256")}


def _artifact_header(value):
    root = Path(value['artifact_root'])
    relative = Path(value['archive'])
    require(not relative.is_absolute() and '..' not in relative.parts, 'unsafe artifact path')
    raw = safe_read(root/relative, 4*1024*1024, 'native archive')
    provenance = read_receipt({'path':str((root/relative).with_suffix('.provenance.json')), 'sha256':value['provenance_sha256']})
    parsed = parse_backtest_artifact(root, relative, value['strategy'], '2026.7', value['provenance_sha256'], allow_zero_trades=True)
    require(digest(raw) == parsed.archive_sha256, 'artifact changed while parsing')
    return parsed, provenance, raw


def _side(value, role, stage, protocol, stage_source, raw_sha, profile, marks, events, mark_sha, header=None):
    exact(value, "artifact_root archive strategy provenance_sha256 retained_source attempt raw_archive")
    source = read_receipt(value["retained_source"])
    attempt = read_receipt(value["attempt"])
    exact(attempt, "schema role stage native_calls return_code archive_sha256 strategy_sha256 source_sha256 raw_source_sha256")
    require(attempt["schema"] == SCHEMA and attempt["role"] == role and attempt["stage"] == stage
            and type(attempt["native_calls"]) is int and attempt["native_calls"] == 1
            and type(attempt["return_code"]) is int and attempt["return_code"] == 0, "invalid native attempt receipt")
    expected_source = protocol["strategy_sha256" if role == "primary" else "benchmark_sha256"]
    require(attempt["strategy_sha256"] == expected_source and attempt["source_sha256"] == value["retained_source"]["sha256"]
            and attempt["raw_source_sha256"] == raw_sha, "attempt provenance mismatch")
    # Both independently derived strategy manifests retain exactly the same data
    # receipts and source. Never swap the original manifest's strategy hash.
    require(source["source"] == stage_source["source"], "different funding/source identity")
    def data_files(doc):
        return {k:v for k,v in {**doc.get("local_only_files", {}), **doc["files"]}.items()
                if not k.startswith("strategies/") and k != "config.json"}
    require(data_files(source) == data_files(stage_source), "different stage data receipts")
    require(stage_source["files"]["retrieval_receipt.json"]["sha256"] == raw_sha, "wrong raw acquisition parent")
    parsed, provenance, archive_bytes = header or _artifact_header(value)
    require(provenance["acquisition"]["retained_data_provenance_sha256"] == value["retained_source"]["sha256"]
            and provenance["artifact"]["raw_archive_sha256"] == attempt["archive_sha256"]
            and parsed.strategy_sha256 == expected_source
            and provenance['generation']['scenario'] == (STAGES[stage] or 'DEVELOPMENT'), "native artifact/source binding mismatch")
    if value["raw_archive"] is not None:
        exact(value["raw_archive"], "path sha256")
        raw_path = Path(value["raw_archive"]["path"])
        raw_bytes = safe_read(raw_path, 32*1024*1024, "raw native archive")
        require(digest(raw_bytes) == value["raw_archive"]["sha256"] == attempt["archive_sha256"], "raw archive hash mismatch")
        from lab.research_candidate import _validate_raw_zip_infos
        with zipfile.ZipFile(io.BytesIO(raw_bytes)) as archive:
            _validate_raw_zip_infos(archive.infolist())
            reports = [n for n in archive.namelist() if n.endswith('.json') and not n.endswith('_config.json')]
            require(len(reports) == 1 and digest(archive.read(reports[0])) == parsed.report_sha256, "raw/sanitized native report mismatch")
    else:
        require(role == "primary" and stage != "S", "raw native evidence required")
    config_contract = provenance["contract"]
    expected_fee = profile["taker_fee_rate"] * (profile["stress_fee_multiplier"] if stage == "STRESS" else 1)
    require(config_contract["timerange"] == protocol["stages"][stage]["timerange"]
            and parsed.exchange == "binance" and parsed.pairs == ("XRP/USDT:USDT",)
            and parsed.timeframe == "1d" and parsed.detail_timeframe is None
            and parsed.trading_mode == "futures" and parsed.margin_mode == "isolated"
            and parsed.starting_balance == profile["starting_balance"] == 1000
            and parsed.stake_amount == profile["stake_amount"] == 250 and parsed.max_open_trades == 1
            and parsed.configured_fee == expected_fee == protocol["stages"][stage]["fee"], "native comparison config/window mismatch")
    require(source["source"]["funding_model"] == CONTRACT, "funding contract required")
    audit = validate_audit(parsed.funding_audit, parsed.profit_pct, parsed.starting_balance, parsed.total_trades)
    require(audit["mark_data_sha256"] == mark_sha and audit["source_events_sha256"] ==
            digest(json.dumps(events, sort_keys=True, separators=(',', ':')).encode()), "cost audit input receipt mismatch")
    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
        native_result = _strict_json(archive.read(parsed.report_member), "native report")["strategy"][parsed.strategy]
    begin, end = [int(datetime.strptime(t, '%Y%m%d').replace(tzinfo=timezone.utc).timestamp()*1000)
                  for t in protocol['stages'][stage]['timerange'].split('-')]
    recalculated = audit_native_trades(native_result['trades'], events, marks,
                                      symbol='XRPUSDT', start_ms=begin, end_ms=end, starting_balance=1000)
    require(all(audit.get(k) == v for k,v in recalculated.items()), "cost audit differs from native fills and bound funding/mark")
    require(audit["cash_executable"], "non-executable cash")
    if role == "benchmark":
        require(parsed.strategy == protocol["benchmark_class"] and parsed.total_trades == 1, "fixed buy-and-hold benchmark required")
        trade = native_result['trades'][0]
        require(trade['is_short'] is False and trade['leverage'] == 1 and trade['exit_reason'] in {'force_exit', 'liquidation'}
                and trade.get('stop_loss_abs') == 0 and trade.get('initial_stop_loss_abs') == 0, "benchmark is not no-discretionary-stop 1x long")
        opened = datetime.fromisoformat(trade['open_date']).timestamp()*1000
        closed = datetime.fromisoformat(trade['close_date']).timestamp()*1000
        require(opened == begin + 86_400_000 and (trade['exit_reason'] == 'liquidation' or closed == end - 86_400_000),
                "benchmark must use first native entry and final candle boundary")
    net, dd = audit["conservative_net_profit_pct"], audit["conservative_mtm_drawdown_pct"]
    return dict(archive_sha256=parsed.archive_sha256, raw_archive_sha256=attempt["archive_sha256"],
                provenance_sha256=parsed.provenance_sha256, strategy_sha256=parsed.strategy_sha256,
                config_sha256=parsed.config_sha256, source_sha256=value["retained_source"]["sha256"],
                attempt_sha256=value["attempt"]["sha256"], native_calls=1,
                net_pct=net, mtm_dd_pct=dd, risk_return=net/max(dd, 1.0))


def attach_comparison(database, manifest_path, manifest_sha256, *, search_root=None, artifact_root=None):
    """Validate all evidence before the only Candidate metadata update."""
    try:
        document = read_receipt({"path": str(manifest_path), "sha256": manifest_sha256})
        exact(document, "schema candidate_id stage campaign_id research_run_id protocol raw_source stage_source marks primary benchmark")
        require(document["schema"] == SCHEMA and document["stage"] in STAGES, "unsupported comparison")
        with closing(get_connection(database, must_exist=True)) as connection:
            connection.execute("BEGIN IMMEDIATE")
            from lab.codex_generation import load_approved_candidate_snapshot
            snapshot = load_approved_candidate_snapshot(connection, document["candidate_id"])
            require(snapshot.exploration is None, "exploratory Candidate cannot attach validation comparisons")
            require(snapshot.profile['exchange'] == 'binance' and snapshot.profile['pairs'] == ['XRP/USDT:USDT']
                    and snapshot.profile['timeframe'] == '1d', 'comparison requires XRP daily Profile')
            candidate = connection.execute("SELECT * FROM candidates WHERE id=?", (document["candidate_id"],)).fetchone()
            bound, primary_raw, primary_archive = _binding(connection, document, candidate)
            require(bound['profile_snapshot'] == snapshot.profile, 'Search and Candidate Profile mismatch')
            # Bind the primary artifact and source receipt BEFORE opening any
            # supplied phase source, funding or mark values.
            main = document['primary']
            relative = Path(main['archive'])
            require(not relative.is_absolute() and '..' not in relative.parts, 'unsafe primary archive path')
            if primary_archive is not None:
                require(main['raw_archive'] is None, 'completed primary uses recorded sanitized artifact only')
                require(str(Path(main['artifact_root'])/relative) == bound['archive_path'], 'primary path differs from completed Execution')
                require(main['provenance_sha256'] == primary_archive['provenance_sha256'], 'wrong completed primary provenance')
                archive_bytes = safe_read(Path(main['artifact_root'])/main['archive'], 4*1024*1024, 'completed primary archive')
                require(digest(archive_bytes) == primary_archive['archive_sha256'], 'wrong completed primary archive')
            else:
                require(search_root is not None and artifact_root is not None, 'Search and artifact root context required')
                root = Path(search_root)
                require(root.is_absolute() and '..' not in root.parts, 'unsafe Search root')
                artifacts = Path(artifact_root)
                require(artifacts.is_absolute() and '..' not in artifacts.parts and not artifacts.is_relative_to(root), 'Search derivatives require separate artifact root')
                require(Path(main['raw_archive']['path']) == root/bound['archive_relative']
                        and Path(main['artifact_root']) == artifacts/'S'
                        and len(relative.parts) == 1, 'primary path differs from frozen Search location')
                require(Path(document['stage_source']['path']) == root/'acquisition'/'retained-data-provenance.json', 'wrong Search source location')
                from lab.bounded_research import SEARCH_TERMINAL
                terminal = safe_read(root/SEARCH_TERMINAL, 2*1024*1024, 'frozen Search terminal')
                require(digest(terminal) == bound['binding']['terminal_sha256'], 'Search root differs from completed campaign')
                raw_archive = safe_read(root/bound['archive_relative'], 32*1024*1024, 'recorded Search archive')
                require(digest(raw_archive) == primary_raw, 'recorded Search archive changed')
            primary_header = _artifact_header(main)
            require(primary_header[1]['generation']['scenario'] == (STAGES[document['stage']] or 'DEVELOPMENT'), 'wrong native primary scenario')
            if document['stage'] != 'S':
                require(document['stage_source']['sha256'] == main['retained_source']['sha256'] ==
                        primary_header[1]['acquisition']['retained_data_provenance_sha256'], 'wrong completed stage source')
            else:
                require(document['stage_source']['sha256'] == bound['protocol_review_identity']['data_provenance_sha256'], 'wrong frozen Search source')
            protocol = read_receipt(document["protocol"])
            exact(protocol, "schema strategy_sha256 benchmark_sha256 benchmark_class research_design stages")
            require(protocol["schema"] == SCHEMA and protocol["strategy_sha256"] == candidate["code_sha256"]
                    and isinstance(protocol["research_design"], str) and bool(protocol["research_design"])
                    and set(protocol["stages"]) == set(STAGES), "frozen comparison protocol mismatch")
            for details in protocol['stages'].values():
                exact(details, 'timerange fee')
            require(primary_header[1]['contract']['timerange'] == protocol['stages'][document['stage']]['timerange']
                    and primary_header[0].strategy_sha256 == protocol['strategy_sha256'], 'wrong primary stage window/strategy')
            require(protocol['stages']['S']['timerange'] == bound['binding']['search_timerange']
                    and protocol['stages']['D']['timerange'] == bound['binding']['development_timerange'], "protocol windows differ from frozen Search/D")
            h_start = datetime.strptime(protocol['stages']['D']['timerange'].split('-')[1], '%Y%m%d')
            h_end = h_start + timedelta(days=snapshot.profile['holdout_days'])
            require(protocol['stages']['H']['timerange'] == protocol['stages']['STRESS']['timerange'] == f'{h_start:%Y%m%d}-{h_end:%Y%m%d}', "H/Stress not same frozen window")
            raw = read_receipt(document["raw_source"])
            phase = read_receipt(document["stage_source"])
            source_identity(phase['source'], 'XRP/USDT:USDT')
            require(raw["host"] == "fapi.binance.com" and raw["authentication"] == "none" and raw["pair"] == "XRP/USDT:USDT", "wrong acquisition identity")
            # The CLI may only read these values after the actual stage binding
            # above succeeds. In particular, a future H attachment cannot probe H.
            exact(document['marks'], 'path sha256')
            mark_path = Path(document['marks']['path'])
            files = {**phase.get('local_only_files', {}), **phase['files']}
            mark_records = [r for n,r in files.items() if n.endswith('/XRP_USDT_USDT-1h-mark.feather')]
            require(len(mark_records) == 1 and document['marks']['sha256'] == mark_records[0]['sha256'], 'wrong stage mark source')
            mark_raw = safe_read(mark_path, 64*1024*1024, 'bound hourly marks')
            require(digest(mark_raw) == document['marks']['sha256'], 'stage mark changed')
            events = phase['source'].get('funding_events')
            if events is None:
                receipt = phase['source']['funding_events_receipt']
                events_path = Path(document['stage_source']['path']).parent/'funding-events.json'
                events = read_receipt({'path':str(events_path), 'sha256':receipt['sha256']})
            import pandas as pd
            frame = pd.read_feather(io.BytesIO(mark_raw))
            marks = [[int(r.date.value//1_000_000), r.open, r.high, r.low, r.close] for r in frame.itertuples()]
            primary = _side(document["primary"], "primary", document["stage"], protocol, phase, document["raw_source"]["sha256"], snapshot.profile, marks, events, document['marks']['sha256'], primary_header)
            benchmark = _side(document["benchmark"], "benchmark", document["stage"], protocol, phase, document["raw_source"]["sha256"], snapshot.profile, marks, events, document['marks']['sha256'])
            require((primary_raw is None or primary["raw_archive_sha256"] == primary_raw)
                    and (primary_archive is None or all(primary[k] == v for k, v in primary_archive.items())), "primary is not the recorded stage artifact")
            value = dict(schema=SCHEMA, candidate_id=candidate["id"], stage=document["stage"],
                         campaign_id=document["campaign_id"], research_run_id=document["research_run_id"],
                         protocol_sha256=document["protocol"]["sha256"], receipt_sha256=manifest_sha256,
                         raw_source_sha256=document["raw_source"]["sha256"], stage_source_sha256=document["stage_source"]["sha256"],
                         primary=primary, benchmark=benchmark,
                         verdict="PASSED" if primary["risk_return"] >= benchmark["risk_return"] else "REJECTED",
                         recorded_at_utc=datetime.now(timezone.utc).isoformat())
            metadata = json.loads(candidate["metadata_json"])
            comparisons = metadata.setdefault("cost_comparisons", {})
            previous = comparisons.get(document["stage"])
            if previous is not None:
                value["recorded_at_utc"] = previous["recorded_at_utc"]
                require(previous == value, "immutable comparison conflict")
                return previous
            comparisons[document["stage"]] = value
            validate_comparisons(comparisons, candidate)
            encoded = json.dumps(metadata, allow_nan=False, sort_keys=True, separators=(",", ":"))
            connection.execute("UPDATE candidates SET metadata_json=?,updated_at=? WHERE id=?", (encoded, value["recorded_at_utc"], candidate["id"]))
            connection.commit()
            return value
    except ComparisonError:
        raise
    except (ArtifactImportError, FuturesCostError, KeyError, TypeError, ValueError, OSError, OverflowError, sqlite3.Error) as exc:
        raise ComparisonError("invalid cost comparison evidence") from exc
