#!/usr/bin/env python3
"""Prepare the single proposed short contract. Never register, GET or run native."""
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from lab.portfolio_source import check_scope,read_json,digest,SourceError
from lab.portfolio_short import continuation_allowance,configuration


def prepare():
    contract=read_json(ROOT/'docs/protocols/issue121-short-feasibility-v2.json')
    scope=read_json(ROOT/'docs/issue121-scope-snapshot.json')
    ledger=Path('/Users/shenjianpeng/Documents/freqtrade-lab-local/search-research-supervision-20260902/global-research-ledger.jsonl')
    check_scope(contract,scope,ledger.read_bytes())
    allowance=continuation_allowance(Path(contract['acquisition_budget_path']).read_bytes(),contract)
    jobs=contract['budget']['jobs']
    if len(jobs)!=20 or len({j['key'] for j in jobs})!=20 or len({j['replaces_unused_key_on_approval'] for j in jobs})!=20:
        raise SourceError('job allocation mismatch')
    consumers=[dict(key=j['key'],config=configuration(j['mode'],j['cost'])) for j in jobs]
    return dict(status='PREPARED_NOT_ACTIVATED',scope='PASS_EXACT_SNAPSHOT',
                cumulative_acquisition_remaining=allowance,new_segment_get_cap=54,
                proposed_native_jobs=len(consumers),native_remaining_after_proposed_jobs=68,
                source_qc='NOT_RUN',native_adapter='NOT_BOUND_TO_MARKET_SOURCE',
                funding_eligibility='UNKNOWN_REQUIRES_CERTIFIED_EVENTS',
                interval_evidence='UNKNOWN',settlement_rounding='UNKNOWN',
                next_gate='FIXED_PACKAGE_SUPERVISOR_REVIEW',registration_written=False,
                additional_gets=0,native_calls=0,consumer_configs=consumers)


if __name__=='__main__':
    try:print(json.dumps(prepare(),indent=2))
    except SourceError as exc:
        print(json.dumps(dict(status='BLOCKED_CONTROL',reason=str(exc))));raise SystemExit(2)
