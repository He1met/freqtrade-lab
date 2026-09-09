"""Preserve original freeze; use approved read-transaction binding after checkpoint."""
import hashlib
import json
import os
import sys
from dataclasses import asdict
from datetime import datetime,timezone
from pathlib import Path
import acquire_with_budget as budget
from lab import codex_generation as generation
from lab.database import get_connection
from scripts import fetch_okx_profile_data as producer

ROOT=Path(__file__).resolve().parent
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def logical():
    frozen=json.loads((ROOT/'freeze-receipt.json').read_text())
    for n,h in frozen['files_sha256'].items():assert sha(ROOT/n)==h
    for p,h in frozen['producer_files_sha256'].items():assert sha(Path(p))==h
    assert producer.validate_runtime()==frozen['native_identity']
    c=get_connection(ROOT/'research.sqlite',read_only=True)
    try:
        c.execute('BEGIN')
        p=generation.load_profile_snapshot(c,frozen['profile_id'])
        s=generation.load_approved_candidate_snapshot(c,frozen['candidate_id'])
        counts={t:c.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in frozen['counts']}
        assert p==json.loads((ROOT/'profile-snapshot.json').read_text())
        assert s.profile==p and s.code_text==(ROOT/'AtomRegimePullbackV1.py').read_text()
        assert s.generation_run_id==frozen['generation_id'] and s.code_sha256==sha(ROOT/'AtomRegimePullbackV1.py')
        assert counts==frozen['counts']
        return {'profile':p,'approved_candidate':asdict(s),'counts':counts}
    finally:
        c.rollback();c.close()

def main():
    snapshot=logical()
    if sys.argv[1:]==['--verify']:
        assert not (ROOT/'source-attempts.jsonl').exists()
        record={'schema':'issue92-checkpoint-logical-binding-v1','created_at':datetime.now(timezone.utc).isoformat(),'original_freeze_sha256':sha(ROOT/'freeze-receipt.json'),'original_freeze_preserved':True,'reason':'Registration process exit checkpoint changed main-file SHA; original hash is not treated as WAL-inclusive proof. Approved Profile/Candidate binding is revalidated in one read-only transaction.','database_after_checkpoint_sha256':sha(ROOT/'research.sqlite'),'database_sidecars':{s:Path(str(ROOT/'research.sqlite')+s).exists() for s in ('-wal','-shm','-journal')},'execution_wrapper_sha256':sha(Path(__file__)),'logical_snapshot':snapshot}
        with (ROOT/'freeze-db-binding-addendum.json').open('xb') as f:
            f.write(producer.canonical_bytes(record));f.flush();os.fsync(f.fileno())
        print(json.dumps({'status':'LOGICAL_FREEZE_BINDING_VERIFIED','addendum_sha256':sha(ROOT/'freeze-db-binding-addendum.json'),'counts':snapshot['counts']}));return
    assert sys.argv[1:]==['--acquire']
    addendum=json.loads((ROOT/'freeze-db-binding-addendum.json').read_text())
    assert addendum['original_freeze_sha256']==sha(ROOT/'freeze-receipt.json')
    assert addendum['execution_wrapper_sha256']==sha(Path(__file__))
    assert snapshot==addendum['logical_snapshot']
    assert not (ROOT/'source').exists()
    old_guard=producer.install_request_guard
    def guard(exchange):
        assert exchange.options.get('maxRetriesOnFailure',0)==0
        assert all(x.max_retries.total==0 for x in exchange.session.adapters.values())
        old_guard(exchange)
    producer.install_request_guard=guard
    sys.argv=['fetch_okx_profile_data.py','--output-root',str(ROOT/'source'),'--profile-database',str(ROOT/'research.sqlite'),'--profile-id',snapshot['profile']['id'],'--window-spec',str(ROOT/'window-spec.json'),'--pre-roll-candles','200','--single-baseline',str(ROOT/'single-baseline.json')]
    with (ROOT/'source-attempts.jsonl').open('xb') as log:
        try:
            with budget.bounded_requests(log) as state:producer.main()
            budget.persist(log,{'event':'SOURCE_COMPLETED','attempts':state['attempts']})
        except BaseException as e:
            budget.persist(log,{'event':'SOURCE_STOPPED','error_type':type(e).__name__,'response_body_logged':False})
            raise SystemExit('SOURCE_STOPPED; no automatic retry') from None
        finally:producer.install_request_guard=old_guard

if __name__=='__main__':main()
