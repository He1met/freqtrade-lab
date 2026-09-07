"""Four bounded test groups; synthetic files and temporary SQLite only."""
import hashlib
import json
import subprocess
import sys
import threading
from pathlib import Path

import pytest
from lab import codex_generation as cg
from lab.database import get_connection
from tests.test_codex_generation import _approved_candidate


def put(root, name, value):
    data = json.dumps(value, sort_keys=True).encode()
    (root / name).parent.mkdir(parents=True, exist_ok=True)
    (root / name).write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def fixture(tmp_path):
    db, gid, cid = _approved_candidate(tmp_path)
    root = (tmp_path / 'evidence').resolve(); root.mkdir()
    with get_connection(db) as c:
        c.execute('BEGIN')
        snap = cg.load_approved_candidate_snapshot(c, cid)
    (root / 'final-protocol.md').write_bytes(b'synthetic frozen protocol')
    protocol = hashlib.sha256((root / 'final-protocol.md').read_bytes()).hexdigest()
    contract = dict(search_timerange='20230101-20240101', profile_snapshot=snap.profile, single_baseline=dict(protocol_sha256=protocol, strategy_sha256=snap.code_sha256))
    put(root, 'profile-contract.json', contract)
    source_sha = put(root, 'complete-source/retained-data-provenance.json', dict(contract={'profile_acquisition':contract}, files={'retrieval_receipt.json':dict(sha256='b'*64)}))
    search_sha = put(root, 'search-campaign/acquisition/retained-data-provenance.json', dict(local_only_files={'synthetic-futures.feather':dict(sha256='d'*64)}))
    source = dict(provenance_sha256=source_sha, retrieval_receipt_sha256='b'*64)
    qc = dict(status='SOURCE_QC_PASS', phase_qc=[dict(stage='S+D', provenance_sha256=source_sha), dict(stage='S', provenance_sha256=search_sha)])
    put(root, 'source-publication.json', source); put(root, 'source-aggregation-qc.json', qc)
    cap = dict(status='UNDERPOWERED', exposure='S_SIGNAL_EXPOSED', strategy_sha256=snap.code_sha256, source_sha256='d'*64,
               blocks=[dict(start='2023-01-01T00:00:00+00:00', end_exclusive='2024-01-01T00:00:00+00:00')],
               thresholds=dict(natural_total=snap.profile['min_development_trades']), PnL_or_future_returns_computed=False, native_backtests=0)
    cap_sha = put(root, 'signal-capacity.json', cap)
    terminal = dict(status='UNDERPOWERED', candidate_id=cid, generation_id=gid, strategy_sha256=snap.code_sha256,
                    protocol_sha256=protocol, source=qc, capacity=cap, economic_result='UNKNOWN_NOT_COMPUTED',
                    native_Search_runs=0, D_strategy_runs=0, H_Stress='SEALED_UNREAD_UNACQUIRED')
    boundary = dict(original_report_sha256=cap_sha, S_only_source_sha256='d'*64, corrected_blocks_use_entry_dates=True,
                    status='UNDERPOWERED', native_backtests=0, in_S_entry_upper_bound=2, long_upper_bound=1, short_upper_bound=1)
    args = dict(terminal_sha256=put(root, 'capacity-terminal-receipt.json', terminal), boundary_sha256=put(root, 'capacity-entry-boundary-audit.json', boundary))
    return db, gid, cid, root, args


def state(db):
    with get_connection(db, read_only=True) as c:
        return {t: [tuple(r) for r in c.execute('SELECT * FROM '+t)] for t in
                ['research_profiles', 'generation_runs', 'candidates', 'research_runs', 'backtest_executions', 'releases']}


def test_cli_roundtrip_preserves_history_and_public_projection(tmp_path):
    db, gid, cid, root, args = fixture(tmp_path); before = state(db)
    cli = Path(__file__).resolve().parents[1] / 'scripts/attach_candidate_prefilter_evidence.py'
    run = subprocess.run([sys.executable, str(cli), '--database', str(db), '--candidate-id', cid,
                          '--evidence-root', str(root), '--terminal-sha256', args['terminal_sha256'],
                          '--boundary-sha256', args['boundary_sha256']], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    receipt = json.loads(run.stdout)
    public = cg.load_generation(db, gid)
    assert public['status'] == 'COMPLETED' and public['candidate']['review_status'] == 'APPROVED'
    assert public['candidate']['prefilter_evidence'] == receipt and receipt['pnl'] is None
    assert receipt['scoring_start_utc'] == '2023-01-01T00:00:00+00:00'
    assert receipt['scoring_end_exclusive_utc'] == '2024-01-01T00:00:00+00:00'
    from lab.research_console import create_research_console_server
    from tests.test_research_console import _request
    (tmp_path/'runtime').mkdir(); (tmp_path/'pilot').mkdir()
    server = create_research_console_server(db, tmp_path/'runtime', tmp_path/'pilot', port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        status, _, _, payload = _request(server, '/api/generations/'+gid)
        assert status == 200 and payload['candidate']['prefilter_evidence'] == receipt
        status, _, html, _ = _request(server, '/console')
        assert status == 200 and b'/console.js' in html
        status, _, script, _ = _request(server, '/console.js')
        assert status == 200 and b'generationStatus.textContent = JSON.stringify(safe, null, 2)' in script
    finally:
        server.research_console_controller.shutdown()
        server.shutdown(); server.server_close(); thread.join(timeout=5)
    after = state(db)
    assert {k:v for k,v in before.items() if k != 'candidates'} == {k:v for k,v in after.items() if k != 'candidates'}
    with get_connection(db, read_only=True) as c:
        names = [r[1] for r in c.execute('PRAGMA table_info(candidates)')]
    old, new = dict(zip(names,before['candidates'][0])), dict(zip(names,after['candidates'][0]))
    assert {k:v for k,v in old.items() if k not in ('metadata_json','updated_at')} == {k:v for k,v in new.items() if k not in ('metadata_json','updated_at')}
    meta = json.loads(new['metadata_json']); meta.pop('prefilter_evidence')
    assert meta == json.loads(old['metadata_json'])
    # Existing Console renderer safely displays every returned field as text.
    console = (cli.parents[1]/'lab/research_console.py').read_text()
    assert 'generationStatus.textContent = JSON.stringify(safe, null, 2)' in console


@pytest.mark.parametrize('field', ['candidate_id','generation_id','strategy_sha256','protocol_sha256','native_Search_runs','source','receipt','profile','threshold','report_hash','window','window_timezone','window_reverse'])
def test_binding_failures_are_atomic(tmp_path, field):
    db, gid, cid, root, args = fixture(tmp_path); before = state(db)
    path = root/'capacity-terminal-receipt.json'; value = json.loads(path.read_bytes())
    if field.startswith('window'):
        p = json.loads((root/'signal-capacity.json').read_bytes())
        p['blocks'][0]['start'] = {'window':'2023-01-02T00:00:00+00:00', 'window_timezone':'2023-01-01T01:00:00+01:00', 'window_reverse':'2025-01-01T00:00:00+00:00'}[field]
        put(root,'signal-capacity.json',p)
    elif field == 'profile':
        p = json.loads((root/'profile-contract.json').read_bytes()); p['profile_snapshot']['name']='tampered'; put(root,'profile-contract.json',p)
    elif field == 'threshold':
        p = json.loads((root/'signal-capacity.json').read_bytes()); p['thresholds']['natural_total']=999; put(root,'signal-capacity.json',p)
    elif field == 'report_hash': args['terminal_sha256']='0'*64
    elif field == 'receipt':
        p=json.loads((root/'source-publication.json').read_bytes());p['retrieval_receipt_sha256']='0'*64;put(root,'source-publication.json',p)
    else:
        value[field] = False if field == 'native_Search_runs' else {}
        args['terminal_sha256']=put(root,path.name,value)
    with pytest.raises(cg.GenerationContractError): cg.attach_prefilter_evidence(db,cid,root,**args)
    assert state(db)==before


def test_same_receipt_is_noop_and_different_receipt_conflicts(tmp_path):
    db, gid, cid, root, args = fixture(tmp_path)
    first=cg.attach_prefilter_evidence(db,cid,root,**args); before=state(db)
    assert cg.attach_prefilter_evidence(db,cid,root,**args)==first and state(db)==before
    p=json.loads((root/'capacity-entry-boundary-audit.json').read_bytes());p.update(in_S_entry_upper_bound=3,long_upper_bound=2)
    args['boundary_sha256']=put(root,'capacity-entry-boundary-audit.json',p)
    with pytest.raises(cg.GenerationContractError,match='already attached'): cg.attach_prefilter_evidence(db,cid,root,**args)
    assert state(db)==before
    db2, _, cid2, root2, args2 = fixture(tmp_path/'rollback'); before2=state(db2)
    with get_connection(db2) as c:
        c.execute("CREATE TRIGGER reject_evidence BEFORE UPDATE ON candidates BEGIN SELECT RAISE(ABORT,'synthetic write failure'); END")
    with pytest.raises(cg.GenerationContractError): cg.attach_prefilter_evidence(db2,cid2,root2,**args2)
    assert state(db2)==before2


@pytest.mark.parametrize('bad', ['symlink','root_symlink','oversize','bool','nan','tampered_read'])
def test_unsafe_or_malformed_evidence_is_rejected(tmp_path,bad):
    db,gid,cid,root,args=fixture(tmp_path);before=state(db);path=root/'capacity-entry-boundary-audit.json'
    if bad=='symlink': path.rename(root/'target');path.symlink_to(root/'target')
    elif bad=='root_symlink':
        alias=tmp_path/'alias';alias.symlink_to(root,target_is_directory=True);root=alias
    elif bad=='oversize': path.write_bytes(b' '* (4*1024*1024+1))
    elif bad=='tampered_read':
        cg.attach_prefilter_evidence(db,cid,root,**args)
        with get_connection(db) as c:
            m=json.loads(c.execute('SELECT metadata_json FROM candidates WHERE id=?',(cid,)).fetchone()[0]);m['prefilter_evidence']['candidate_id']='wrong'
            c.execute('UPDATE candidates SET metadata_json=? WHERE id=?',(json.dumps(m),cid))
        with pytest.raises(cg.GenerationContractError): cg.load_generation(db,gid)
        return
    else:
        p=json.loads(path.read_bytes());p['in_S_entry_upper_bound']=True if bad=='bool' else float('nan')
        args['boundary_sha256']=put(root,path.name,p)
    with pytest.raises(cg.GenerationContractError): cg.attach_prefilter_evidence(db,cid,root,**args)
    assert state(db)==before
