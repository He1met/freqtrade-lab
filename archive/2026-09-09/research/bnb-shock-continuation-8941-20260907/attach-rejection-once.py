from pathlib import Path
from datetime import datetime, timezone
import hashlib, json, subprocess, sys
from lab.database import get_connection
r = Path(__file__).parent
sha = lambda b: hashlib.sha256(b).hexdigest()
tables = ['research_profiles','generation_runs','candidates','research_runs','backtest_executions','releases']
def snapshot():
    with get_connection(r/'lab.sqlite', read_only=True) as c:
        c.execute('BEGIN')
        assert c.execute('PRAGMA user_version').fetchone()[0] == 1
        return {t: [dict(row) for row in c.execute('SELECT * FROM '+t+' ORDER BY id')] for t in tables}
def save(name, value):
    with (r/name).open('x') as f: json.dump(value,f,sort_keys=True,indent=2,allow_nan=False); f.write('\n')
archive=r/'search-campaign/search-results-round-1/ebf9c764-6efb-41eb-b309-51833d7c6776/raw/backtest-result-2026-09-07_06-36-32.zip'
expected={'final-protocol.md':'0bac2485cbe9265e6657891cd3e94f8330945d70964bced95524aed95d454bfb',
 'BnbDailyShockContinuation48H.py':'d250751eb5314acb622266a6033e603da2c137b96592d7a16c7bd7498ddc4ba6',
 'search-protocol-review.json':'ae5aeab1124ab4558e6713521a8b6b6b21f16215a20ec74e0e34f89b92d32422',
 str(archive.relative_to(r)):'97b80e4b45e436659622c957fe2cb40dbc560f6bceb7ea668cd2a69506278dfe'}
assert subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip() == '97b5e5dd45605655e25574e0d6948acee20aacd5'
assert not subprocess.check_output(['git','status','--porcelain'],text=True).strip()
before=snapshot()
assert [len(before[t]) for t in tables] == [1,2,1,0,0,0]
assert 'search_protocol_rejection' not in json.loads(before['candidates'][0]['metadata_json'])
assert {p:sha((r/p).read_bytes()) for p in expected} == expected
save('rejection-attachment-before.json',before)
save('rejection-attachment-before-hashes.json',expected)
save('rejection-attachment-started.json',dict(at=datetime.now(timezone.utc).isoformat(),maximum_CLI_calls=1,merge_sha='97b5e5dd45605655e25574e0d6948acee20aacd5'))
command=[sys.executable,'scripts/attach_search_protocol_rejection.py','--database',str(r/'lab.sqlite'),
 '--campaign-id','a525b554-18c4-4810-8767-ac536cc13daa','--review-path',str(r/'search-protocol-review.json'),
 '--archive-path',str(archive),'--review-sha256',expected['search-protocol-review.json']]
result=subprocess.run(command,capture_output=True,text=True)
save('rejection-cli-output.json',dict(returncode=result.returncode,stdout=result.stdout,stderr=result.stderr))
assert result.returncode == 0, result.stderr
value=json.loads(result.stdout)
after=snapshot()
save('rejection-attachment-after.json',after)
assert [len(after[t]) for t in tables] == [1,2,1,0,0,0]
for t in tables:
    if t != 'candidates': assert after[t] == before[t], t
old,new=before['candidates'][0],after['candidates'][0]
changed=[k for k in old if old[k]!=new[k]]
assert set(changed)=={'metadata_json','updated_at'}
metadata=json.loads(new['metadata_json'])
assert metadata.pop('search_protocol_rejection')==value
assert metadata==json.loads(old['metadata_json'])
assert {p:sha((r/p).read_bytes()) for p in expected} == expected
save('rejection-attachment-receipt.json',dict(status='ATTACHED_ONCE',cli_calls=1,counts={t:len(after[t]) for t in tables},
 changed_candidate_fields=changed,all_other_rows_unchanged=True,original_metadata_preserved=True,frozen_hashes_unchanged=expected,
 before_sha256=sha((r/'rejection-attachment-before.json').read_bytes()),after_sha256=sha((r/'rejection-attachment-after.json').read_bytes()),
 attachment=value,merge_sha='97b5e5dd45605655e25574e0d6948acee20aacd5'))
print(json.dumps(dict(status='ATTACHED_ONCE',counts={t:len(after[t]) for t in tables},changed=changed)))
