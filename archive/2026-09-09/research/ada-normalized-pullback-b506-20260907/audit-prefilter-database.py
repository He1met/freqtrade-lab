"""Read-only audit of the specifically authorized sanitized ADA database."""
import hashlib
import json
import sys
from pathlib import Path
from lab.database import get_connection

root = Path(__file__).resolve().parent
def sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()

with get_connection(root/'lab.sqlite', read_only=True) as connection:
    tables = ['research_profiles', 'generation_runs', 'candidates', 'research_runs', 'backtest_executions', 'releases']
    rows = {t: [dict(r) for r in connection.execute('SELECT * FROM '+t+' ORDER BY id')] for t in tables}
counts = {t: len(r) for t, r in rows.items()}
assert list(counts.values()) == [1, 1, 1, 0, 0, 0], counts
candidate = rows['candidates'][0]
assert candidate['id'] == 'fbf47a7c-c892-45c0-80ce-03bee437e1d9'
assert candidate['generation_run_id'] == 'ef5de524-0506-4bd6-9af5-eec9d9c59202'
metadata = json.loads(candidate['metadata_json'])
evidence = metadata.pop('prefilter_evidence', None)
protected = {k: v for k, v in candidate.items() if k not in ('metadata_json', 'updated_at')}
protected['metadata_original_subtrees'] = metadata
result = dict(counts=counts, other_tables_sha256={t:sha(r) for t,r in rows.items() if t != 'candidates'},
              candidate_protected_sha256=sha(protected), original_metadata_sha256=sha(metadata),
              candidate_id=candidate['id'], generation_id=candidate['generation_run_id'],
              prefilter_evidence=evidence, candidate_updated_at=candidate['updated_at'])
if sys.argv[1] == 'before':
    assert evidence is None
else:
    before = json.loads((root/'prefilter-database-before.json').read_text())
    for k in ('counts', 'other_tables_sha256', 'candidate_protected_sha256', 'original_metadata_sha256', 'candidate_id', 'generation_id'):
        assert result[k] == before[k], k
    assert evidence['counts'] == dict(total=14, long=5, short=9)
    assert evidence['required_total'] == 24 and evidence['pnl'] is None and evidence['native_search_runs'] == 0
    assert evidence['status'] == 'UNDERPOWERED'
    assert evidence['scoring_start_utc'] == '2023-11-06T00:00:00+00:00'
    assert evidence['scoring_end_exclusive_utc'] == '2024-11-04T00:00:00+00:00'
    assert evidence['report_sha256'] == '8f706f4271b40b325cb50ca15cbeacf951b32c1bacea86fa5576f9a2de26d9c6'
    assert evidence['entry_boundary_report_sha256'] == '38aa824122333a413ffe99044c33494fa01a100536e8a32bbb404165b0377948'
    result['protected_fields_unchanged'] = True
    if (root/'prefilter-generation-http.json').exists():
        public = json.loads((root/'prefilter-generation-http.json').read_text())
        cli = json.loads((root/'prefilter-cli-import.json').read_text())
        assert public['candidate']['prefilter_evidence'] == cli == evidence
        assert public['candidate']['review_status'] == 'APPROVED' and public['status'] == 'COMPLETED'
        context = json.loads((root/'prefilter-search-context-http.json').read_text())
        assert context['state']['attempts'] == [] and context['state']['campaign_id'] is None
        assert context['state']['budget']['consumed_total'] == 0
        result['http_cli_database_evidence_identical'] = True
        result['search_attempts'] = 0
print(json.dumps(result, indent=2, sort_keys=True))
