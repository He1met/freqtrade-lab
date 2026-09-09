"""Authorized one-shot project HTTP Generation; no market actions."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import http.client
import json
import os
import shutil
import sys
import threading
import time

REPO = Path('/Users/shenjianpeng/.codex/worktrees/d699/freqtrade-lab')
ROOT = Path(__file__).parent
sys.path.insert(0, str(REPO))
from lab.database import init_database, get_connection
from lab.codex_generation import load_profile_snapshot
from lab.research_console import create_research_console_server

os.umask(0o077)
def put(name, value):
    with (ROOT/name).open('x') as handle:
        json.dump(value, handle, sort_keys=True, allow_nan=False)

put('generation-once-guard.json', {'started_at_utc':datetime.now(timezone.utc).isoformat(),
                                  'maximum_model_calls':1,'market_actions':0})
db=ROOT/'lab.sqlite'
assert not db.exists()
profile=json.loads((ROOT/'profile-preview.json').read_bytes())
init_database(db)
row=dict(profile);row['pairs_json']=json.dumps(row.pop('pairs'),separators=(',', ':'))
with get_connection(db) as connection:
    connection.execute('BEGIN IMMEDIATE')
    connection.execute('INSERT INTO research_profiles ('+','.join(row)+') VALUES ('+','.join('?' for _ in row)+')', tuple(row.values()))
    assert load_profile_snapshot(connection,profile['id'])==profile
    connection.commit()
put('profile-registration-receipt.json',dict(profile_id=profile['id'],
    frozen_profile_sha256=hashlib.sha256((ROOT/'profile-preview.json').read_bytes()).hexdigest(),
    registered_at_utc=datetime.now(timezone.utc).isoformat(),database=str(db),
    schema=1,profile_rows=1,market_calls=0))
runtime=ROOT/'generation-runtime';runtime.mkdir()
pilot=ROOT/'generation-empty-context';pilot.mkdir()
server=None
try:
    server=create_research_console_server(db,runtime,pilot,port=0,
        codex_binary=Path(shutil.which('codex')),check_data_python=Path(sys.executable),task_timeout_seconds=300)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    def request(path,payload=None):
        connection=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=30)
        try:
            headers={} if payload is None else {
                'Origin':f'http://127.0.0.1:{server.server_port}',
                'X-CSRF-Token':server.research_console_csrf_token,'Content-Type':'application/json'}
            connection.request('GET' if payload is None else 'POST',path,
                body=None if payload is None else json.dumps(payload).encode(),headers=headers)
            response=connection.getresponse();body=json.loads(response.read())
            return response.status,body
        finally:connection.close()
    status,created=request('/api/generations',json.loads((ROOT/'generation-request-preview.json').read_bytes()))
    put('generation-create-response.json',dict(http_status=status,response=created))
    if status!=202:raise RuntimeError('Generation HTTP start rejected: '+str(created.get('error',status)))
    gid=created['id']
    print(json.dumps({'generation_id':gid,'state':'RUNNING','actual_project_http':True}),flush=True)
    deadline=time.monotonic()+330
    while time.monotonic()<deadline:
        status,current=request('/api/generations/'+gid)
        if status!=200:raise RuntimeError('Generation read failed')
        if current['status'] in ('COMPLETED','FAILED'):break
        time.sleep(2)
    else:raise RuntimeError('Generation terminal timeout; no retry')
    put('generation-terminal-before-review.json',current)
    candidate=current.get('candidate')
    expected=json.loads((ROOT/'final-protocol.json').read_bytes())['strategy_sha256']
    if current['status']!='COMPLETED' or not candidate:raise RuntimeError('Generation did not produce a Candidate')
    if candidate['code_sha256']!=expected or hashlib.sha256(candidate['code_text'].encode()).hexdigest()!=expected:
        raise RuntimeError('FROZEN_SOURCE_HASH_MISMATCH; Candidate not approved; no retry')
    status,approved=request('/api/generations/'+gid+'/actions',{'action':'APPROVE'})
    if status!=200 or approved['candidate']['review_status']!='APPROVED':raise RuntimeError('Generation approval failed')
    put('generation-approved-api.json',approved)
    final=dict(status='GENERATION_COMPLETED_CANDIDATE_APPROVED',profile_id=profile['id'],generation_id=gid,
        candidate_id=candidate['id'],source_sha256=expected,database=str(db),actual_project_http=True,
        actual_generation_attempts=1,model_configuration='existing CLI default; no model override',
        finished_at_utc=datetime.now(timezone.utc).isoformat(),market_native_calls=0)
    put('generation-execution-receipt.json',final)
    print(json.dumps(final),flush=True)
except Exception as error:
    put('generation-phase-failure.json',dict(status='BLOCKED_GENERATION',error_type=type(error).__name__,
        message=str(error),created_at_utc=datetime.now(timezone.utc).isoformat(),retry=False,market_native_calls=0))
    print(json.dumps({'status':'BLOCKED_GENERATION','message':str(error)}),flush=True)
    raise
finally:
    if server is not None:
        server.research_console_controller.shutdown()
        server.shutdown();server.server_close()
