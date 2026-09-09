import json
import subprocess
from runtime_control import ROOT, append, put, sha, verify_freeze
from lab import bounded_research as br
from lab.database import get_connection

verify_freeze()
commands = json.loads((ROOT / 'commands.json').read_text())
raw = ROOT / 'source-sd-01'
bindings = {'<RAW_PROVENANCE_SHA>': 'cba9702fa2631529b599fddb66ca125902fe0998ae5e2459b3a56f2f19225a5b',
            '<RAW_RECEIPT_SHA>': '34913af2ee35a9b74adbfcf45794b5e0da6a400044d9cc37ac27502b150cb72b'}
assert sha((raw / 'retained-data-provenance.json').read_bytes()) == bindings['<RAW_PROVENANCE_SHA>']
assert sha((raw / 'retrieval_receipt.json').read_bytes()) == bindings['<RAW_RECEIPT_SHA>']
assert not (ROOT / 'search-data-01').exists() and not (ROOT / 'development-data-01').exists()
con = get_connection(ROOT / 'lab.sqlite', read_only=True, must_exist=True)
try:
    assert br.load_profile_snapshot(con, 'sol-spot-fixed-rule-validation-f590-v2') == json.loads((ROOT / 'profile.json').read_text())
finally:
    con.close()
corrected = {}
for name in ['prepare_search', 'prepare_development']:
    argv = [bindings.get(arg, arg) for arg in commands[name]]
    if name == 'prepare_search':
        assert '--development-timerange' not in argv
        argv += ['--development-timerange', '20220201-20230201']
    args = br.parse_args(argv[5:])
    assert args.search_timerange == '20210301-20220201'
    assert args.development_timerange == '20220201-20230201'
    assert args.pre_roll_candles == 29
    assert args.database == ROOT / 'lab.sqlite'
    assert args.profile_id == 'sol-spot-fixed-rule-validation-f590-v2'
    assert args.source_root == raw and not args.output_root.exists()
    economic = br.load_profile_economic_gate(args.economic_gate)
    single = br.validate_single_baseline(json.loads(args.single_baseline.read_text()))
    br.profile_acquisition_contract(args.database, args.profile_id, args.search_timerange,
                                    args.development_timerange, args.pre_roll_candles,
                                    economic, single_baseline=single)
    corrected[name] = argv
put('prepare-corrected-argv.json', corrected)
correction = {'status': 'PURE_CONTROL_VALIDATION_PASS',
    'original_commands_sha256': sha((ROOT / 'commands.json').read_bytes()),
    'original_failed_argv_sha256': sha((ROOT / 'prepare_search-command.json').read_bytes()),
    'corrected_argv_sha256': sha((ROOT / 'prepare-corrected-argv.json').read_bytes()),
    'change': 'Only append frozen --development-timerange 20220201-20230201 to Search preparation; D command unchanged; bind actual known raw receipt hashes',
    'protocol_unchanged': True, 'source_unchanged': True,
    'network_calls': 0, 'native_calls': 0, 'D_values_read': False,
    'existing_database_reused': True, 'output_roots_absent_before_attempt': True}
put('prepare-control-correction-receipt.json', correction)
put('recovery-authorization-ledger.json', append({'record_type': 'ADMINISTRATIVE_RECOVERY_BEFORE_SEARCH',
    'authorization_source_thread': '01a05dcc-17fd-7972-9177-9fed95e4b07a',
    'reason': correction['change'], 'control_receipt_sha256': sha((ROOT / 'prepare-control-correction-receipt.json').read_bytes()),
    'new_http_allowed': 0, 'maximum_Generation_remaining': 1, 'maximum_S_native_remaining': 1,
    'D_H_Stress_BTC_R2_allowed': False, 'original_failure_retained': True},
    '9a1ca424943fa03f764272a799d95d89e4f4eb3eeba6716b907aa4abc4cf7aed'))
results = {}
for name, argv in corrected.items():
    with (ROOT / (name + '-recovery.stdout')).open('x') as out, (ROOT / (name + '-recovery.stderr')).open('x') as err:
        result = subprocess.run(argv, cwd=commands['cwd'], stdout=out, stderr=err, timeout=300)
    results[name] = result.returncode
    if result.returncode:
        receipt = {'status': 'RECOVERY_PREPARATION_FAILED_STOP', 'step': name, 'return_codes': results, 'native_calls': 0}
        put('recovery-preparation-failure.json', receipt)
        put('recovery-preparation-failure-ledger.json', append({'record_type': 'SOURCE_PREPARATION_TERMINAL', **receipt}))
        raise SystemExit(result.returncode)
receipt = {'status': 'SOURCE_QC_AND_PHYSICAL_ISOLATION_PASS',
    'raw_provenance_sha256': bindings['<RAW_PROVENANCE_SHA>'], 'raw_receipt_sha256': bindings['<RAW_RECEIPT_SHA>'],
    'S_prepared_provenance_sha256': sha((ROOT / 'search-data-01/acquisition/retained-data-provenance.json').read_bytes()),
    'D_prepared_provenance_sha256': sha((ROOT / 'development-data-01/development-isolation/retained-data-provenance.json').read_bytes()),
    'S_rows': 366, 'D_rows': 394, 'source_rows': 731,
    'D_machine_QC_only': True, 'D_researcher_values_or_results_read': False,
    'H_values_acquired': False, 'native_calls': 0, 'new_http_calls': 0, 'return_codes': results}
put('source-qc-receipt.json', receipt)
put('source-qc-ledger-receipt.json', append({'record_type': 'SOURCE_QC_AND_ISOLATION', **receipt}))
print(json.dumps(receipt))
