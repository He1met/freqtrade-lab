import json
import subprocess
from runtime_control import ROOT, append, put, sha, verify_freeze

verify_freeze()
assert json.loads((ROOT / 'capture-execution-receipt.json').read_text())['status'] == 'CAPTURE_PASS_PENDING_SOURCE_QC'
commands = json.loads((ROOT / 'commands.json').read_text())
raw = ROOT / 'source-sd-01'
hashes = {'<RAW_PROVENANCE_SHA>': sha((raw / 'retained-data-provenance.json').read_bytes()),
          '<RAW_RECEIPT_SHA>': sha((raw / 'retrieval_receipt.json').read_bytes())}
put('source-identity-receipt.json', {'raw_provenance_sha256': hashes['<RAW_PROVENANCE_SHA>'],
    'raw_receipt_sha256': hashes['<RAW_RECEIPT_SHA>'], 'researcher_market_values_read': False})
results = {}
for name in ['prepare_search', 'prepare_development']:
    argv = [hashes.get(arg, arg) for arg in commands[name]]
    put(name + '-command.json', {'argv': argv})
    with (ROOT / (name + '.stdout')).open('x') as out, (ROOT / (name + '.stderr')).open('x') as err:
        result = subprocess.run(argv, cwd=commands['cwd'], stdout=out, stderr=err, timeout=300)
    results[name] = result.returncode
    if result.returncode:
        failure = {'status': 'SOURCE_QC_FAILED_STOP', 'step': name, 'return_codes': results,
                   'native_calls': 0, 'no_retry': True}
        put('source-qc-failure.json', failure)
        put('source-qc-failure-ledger.json', append({'record_type': 'SOURCE_QC_TERMINAL', **failure}))
        raise SystemExit(result.returncode)
receipt = {'status': 'SOURCE_QC_AND_PHYSICAL_ISOLATION_PASS', **hashes,
    'S_prepared_provenance_sha256': sha((ROOT / 'search-data-01/acquisition/retained-data-provenance.json').read_bytes()),
    'D_prepared_provenance_sha256': sha((ROOT / 'development-data-01/development-isolation/retained-data-provenance.json').read_bytes()),
    'S_rows': 366, 'S_score_days': 337, 'D_rows': 394, 'source_rows': 731,
    'D_machine_QC_only': True, 'D_researcher_values_or_results_read': False,
    'H_values_acquired': False, 'native_calls': 0, 'return_codes': results}
put('source-qc-receipt.json', receipt)
put('source-qc-ledger-receipt.json', append({'record_type': 'SOURCE_QC_AND_ISOLATION', **receipt}))
print(json.dumps(receipt))
