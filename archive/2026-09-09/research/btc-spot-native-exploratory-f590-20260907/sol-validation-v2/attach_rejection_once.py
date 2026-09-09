import json
import subprocess
import http.client
from urllib.parse import urlparse
from runtime_control import ROOT, put, append, sha
from lab.database import get_connection
from lab.search_campaign import require_no_protocol_rejection, SearchCampaignError

TABLES = ['research_profiles','generation_runs','candidates','research_runs','backtest_executions','releases']
def snapshot():
    c = get_connection(ROOT/'lab.sqlite', read_only=True, must_exist=True)
    try:
        return {t: [dict(r) for r in c.execute('SELECT * FROM '+t+' ORDER BY id')] for t in TABLES}
    finally:
        c.close()

before = snapshot()
review = ROOT/'search-protocol-rejection-review.json'
archive = ROOT/'search-data-01/search-results-round-1/99eb3df4-ebad-4d97-8dfd-0fdd2af826ce/raw/backtest-result-2026-09-07_10-08-30.zip'
assert sha(archive.read_bytes()) == '2319facb0bebe7c1cee61d48b7084e8de0e2988db618a3192ed7ec70881e7ee3'
assert 'search_protocol_rejection' not in json.loads(before['candidates'][0]['metadata_json'])
argv = ['/Users/shenjianpeng/.codex/runs/freqtrade-lab/issue-43-profile-driven-v1/venv/bin/python',
    '/Users/shenjianpeng/.codex/worktrees/f590/freqtrade-lab/scripts/attach_search_protocol_rejection.py',
    '--database', str(ROOT/'lab.sqlite'), '--campaign-id', '9b429a27-7ca0-4fcc-b5f1-3bb3da2af92c',
    '--review-path', str(review), '--archive-path', str(archive), '--review-sha256', sha(review.read_bytes())]
put('protocol-rejection-command.json', {'argv': argv, 'maximum_invocations': 1})
put('protocol-rejection-authorization-ledger.json', append({'record_type':'SEARCH_REJECTION_ATTACHMENT_AUTHORIZED',
    'authorization_source_thread':'01a05dcc-17fd-7972-9177-9fed95e4b07a',
    'review_sha256':sha(review.read_bytes()), 'native_calls':0, 'http_market_calls':0},
    '6733148cf9f294a68c591cd25e3ca030953d63cfac571fbd2273cc2a9889c884'))
with (ROOT/'protocol-rejection-cli.stdout').open('x') as out, (ROOT/'protocol-rejection-cli.stderr').open('x') as err:
    done = subprocess.run(argv, stdout=out, stderr=err, timeout=60)
assert done.returncode == 0, 'Existing rejection CLI failed; no retry or engineering'
attachment = json.loads((ROOT/'protocol-rejection-cli.stdout').read_text())
after = snapshot()
assert {t:len(rows) for t,rows in before.items()} == {t:len(rows) for t,rows in after.items()}
for t in TABLES:
    if t != 'candidates':
        assert before[t] == after[t], t
old, new = before['candidates'][0], after['candidates'][0]
assert {k:v for k,v in old.items() if k not in {'metadata_json','updated_at'}} == {k:v for k,v in new.items() if k not in {'metadata_json','updated_at'}}
old_meta, new_meta = json.loads(old['metadata_json']), json.loads(new['metadata_json'])
assert new_meta.pop('search_protocol_rejection') == attachment
assert old_meta == new_meta
c = get_connection(ROOT/'lab.sqlite', read_only=True, must_exist=True)
try:
    try:
        require_no_protocol_rejection(c, new['id'])
    except SearchCampaignError as exc:
        assert exc.code == 'search_protocol_rejected'
        exact_block = {'code':exc.code, 'reason':exc.message}
    else:
        raise AssertionError('Development guard did not block')
finally:
    c.close()
url = urlparse(json.loads((ROOT/'console-entrypoint.json').read_text())['base_url'])
checks = {}
for label,path in [('console','/console'),('search_context','/api/search/context'),('research_context','/api/research/context'),('generation','/api/generations/8aaa70fa-49bf-4e5d-a21c-476d83389429')]:
    h = http.client.HTTPConnection(url.hostname,url.port,timeout=10)
    h.request('GET',path); response=h.getresponse(); raw=response.read(); h.close()
    assert response.status == 200
    checks[label] = {'status':response.status,'sha256':sha(raw)}
    if label != 'console':
        value=json.loads(raw); put('after-rejection-'+label+'.json',value)
        checks[label]['data']=value
put('protocol-rejection-attachment-receipt.json',{
    'status':'ATTACHED_AND_READ_ONLY_GUARD_VERIFIED','review_sha256':sha(review.read_bytes()),
    'attachment':attachment,'database_counts':{t:len(rows) for t,rows in after.items()},
    'five_other_tables_byte_value_unchanged':True,'original_candidate_fields_and_metadata_preserved':True,
    'CODEX_generation_and_MANUAL_core_projection_unchanged':True,
    'exact_development_guard':exact_block,'http_checks':checks,
    'cli_invocations':1,'native_calls':0,'market_http_calls':0})
print(json.dumps({'status':'ATTACHED','guard':exact_block,'counts':{t:len(rows) for t,rows in after.items()},
    'receipt_sha256':sha((ROOT/'protocol-rejection-attachment-receipt.json').read_bytes())}))
