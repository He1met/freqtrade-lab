import http.client
import json
import os
import threading
import time
import traceback
from pathlib import Path
from runtime_control import ROOT, append, put, sha, verify_freeze
from lab.research_console import create_research_console_server

verify_freeze()
os.umask(0o077)
NATIVE = Path('/Users/shenjianpeng/.codex/runs/freqtrade-lab/issue-43-profile-driven-v1')
qc = json.loads((ROOT / 'source-qc-receipt.json').read_text())
assert qc['status'] == 'SOURCE_QC_AND_PHYSICAL_ISOLATION_PASS'
assert sha((ROOT / 'search-data-01/acquisition/retained-data-provenance.json').read_bytes()) == qc['S_prepared_provenance_sha256']
for name in ['console-runtime', 'unused-pilot']:
    (ROOT / name).mkdir(mode=0o700, exist_ok=False)
server = create_research_console_server(ROOT / 'lab.sqlite', ROOT / 'console-runtime', ROOT / 'unused-pilot', 0,
    search_root=ROOT / 'search-data-01',
    codex_binary='/Applications/ChatGPT.app/Contents/Resources/codex',
    freqtrade_python=NATIVE / 'venv/bin/python', freqtrade_source=NATIVE / 'freqtrade', task_timeout_seconds=900)
port = server.server_port
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
base = f'http://127.0.0.1:{port}'
put('console-entrypoint.json', {'base_url': base, 'page': base + '/console',
    'search_root': str(ROOT / 'search-data-01'), 'pilot_root': str(ROOT / 'unused-pilot'),
    'D_source_bound_to_console': False})
print(json.dumps({'page': base + '/console', 'status': 'CONSOLE_STARTED'}), flush=True)

def call(method, path, body=None):
    con = http.client.HTTPConnection('127.0.0.1', port, timeout=30)
    headers, data = {}, None
    if body is not None:
        data = json.dumps(body).encode()
        headers = {'Content-Type': 'application/json', 'Origin': base, 'X-CSRF-Token': server.research_console_csrf_token}
    con.request(method, path, body=data, headers=headers)
    response = con.getresponse()
    raw, code = response.read(), response.status
    con.close()
    value = json.loads(raw)
    if code >= 400:
        raise RuntimeError(f'{method} {path}: HTTP {code}: ' + json.dumps(value, ensure_ascii=False)[:800])
    return value

def main():
    ids = {}
    generation_calls = 0
    search_invocations = 0
    try:
        put('search-context-before-generation.json', call('GET', '/api/search/context'))
        put('generation-start-ledger.json', append({'record_type': 'NORMAL_GENERATION_START',
            'profile_id': 'sol-spot-fixed-rule-validation-f590-v2', 'S_source_sha256': qc['S_prepared_provenance_sha256'],
            'maximum_generation_invocations': 1, 'code_sha256': sha((ROOT / 'BtcWeeklyMomentumFixedStake.py').read_bytes()),
            'exploration': False, 'parent_candidate_id': None, 'D_values_read': False}))
        generation_calls += 1
        started = call('POST', '/api/generations', json.loads((ROOT / 'generation-request.json').read_text()))
        put('generation-start-api.json', started)
        gid = started['id']
        ids['generation_id'] = gid
        put('generation-identity.json', ids)
        print(json.dumps({'generation_id': gid, 'status': 'GENERATION_RUNNING'}), flush=True)
        deadline = time.monotonic() + 1000
        while True:
            current = call('GET', '/api/generations/' + gid)
            if current.get('status') != 'RUNNING' and current.get('runtime_status') not in {'STARTING', 'RUNNING'}:
                break
            if time.monotonic() > deadline:
                raise RuntimeError('Generation exceeded control deadline; no replay')
            time.sleep(2)
        put('generation-final-api.json', current)
        assert current['status'] == 'COMPLETED' and current['runtime_status'] == 'SUCCEEDED', 'Generation failed'
        candidate = current['candidate']
        assert candidate['code_sha256'] == 'e1ab5c109eded7a6bd0e4e5d7b07f6c8e3082640530129ea9a390a2f89944611'
        assert candidate['code_text'] == (ROOT / 'BtcWeeklyMomentumFixedStake.py').read_text()
        cid = candidate['id']
        ids['candidate_id'] = cid
        approved = call('POST', '/api/generations/' + gid + '/actions', {'action': 'APPROVE'})
        assert approved['candidate']['review_status'] == 'APPROVED'
        put('generation-approval-api.json', approved)
        put('S-start-ledger.json', append({'record_type': 'SEARCH_REGISTERED_PRE_RUN', **ids,
            'protocol_sha256': sha((ROOT / 'protocol.json').read_bytes()),
            'S_prepared_provenance_sha256': qc['S_prepared_provenance_sha256'],
            'maximum_actual_native_Search_runs': 1, 'D_status': 'MACHINE_QC_ONLY_NO_EXECUTION',
            'H_Stress': 'SEALED_UNREAD_UNACQUIRED', 'page': base + '/console'}))
        search_invocations += 1
        launched = call('POST', '/api/search-campaigns', {'profile_id': 'sol-spot-fixed-rule-validation-f590-v2', 'candidate_ids': [cid]})
        put('S-start-api.json', launched)
        sid = launched.get('campaign_id') or launched.get('id')
        assert isinstance(sid, str), 'Search identity unavailable'
        ids['search_campaign_id'] = sid
        put('S-identities.json', ids)
        print(json.dumps({**ids, 'status': 'SEARCH_STARTED'}), flush=True)
        deadline = time.monotonic() + 1000
        while True:
            state = call('GET', '/api/search-campaigns/' + sid)
            if state.get('status') not in {'STARTING', 'RUNNING'}:
                break
            if time.monotonic() > deadline:
                raise RuntimeError('Search exceeded control deadline; no replay')
            time.sleep(2)
        put('S-final-api.json', state)
        result = {'status': 'S_RETURNED_EXTERNAL_REVIEW_PENDING', 'project_status': state.get('status'),
            **ids, 'page': base + '/console', 'generation_invocations': generation_calls,
            'search_controller_invocations': search_invocations, 'D_H_Stress_BTC_R2_native': 0}
        put('S-controller-delivery.json', result)
        put('S-controller-ledger.json', append({'record_type': 'SEARCH_PROJECT_RETURNED', **result}))
        print(json.dumps(result), flush=True)
    except BaseException as exc:
        traceback.print_exc()
        failure = {'status': 'NORMAL_ENTRYPOINT_FAILED_STOP', 'error_type': type(exc).__name__,
            'message': str(exc)[:1000], **ids, 'page': base + '/console',
            'generation_invocations': generation_calls, 'search_controller_invocations': search_invocations,
            'no_automatic_native_or_generation_retry': True}
        put('normal-entrypoint-failure.json', failure)
        put('normal-entrypoint-failure-ledger.json', append({'record_type': 'NORMAL_ENTRYPOINT_FAILURE', **failure}))
        print(json.dumps(failure), flush=True)

main()
print('WORKFLOW_STOPPED_CONSOLE_REMAINS_FOR_READONLY_REVIEW', flush=True)
thread.join()
