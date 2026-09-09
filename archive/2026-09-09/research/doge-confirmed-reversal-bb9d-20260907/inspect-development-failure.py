from pathlib import Path
import json,hashlib,zipfile,sqlite3
r=Path(__file__).parent
run='68fcd677-fd22-40e9-a6f1-78ee910b3a68'
d=r/'console-runtime/campaigns'/run
sha=lambda b:hashlib.sha256(b).hexdigest()
archive=d/'development-evidence/backtest-result-development-01.zip'
with zipfile.ZipFile(archive) as z:
 assert z.testzip() is None
 names=z.namelist()
 codes=[n for n in names if n.endswith('.py')]
 assert len(codes)==1 and sha(z.read(codes[0]))=='61488a724e54fca3dfe11a47294c3a3a02077090cb38baaef5385d16ef43d05f'
 reports=[n for n in names if n.endswith('.json') and not n.endswith('_config.json')]
 assert len(reports)==1
 report=json.loads(z.read(reports[0]))['strategy']['DogeConfirmedShockReversal3D']
 report_identity={k:report[k] for k in ('strategy_name','timeframe','backtest_start','backtest_end') if k in report}
 members={n:dict(bytes=z.getinfo(n).file_size,sha256=sha(z.read(n))) for n in names}
manifest=json.loads((d/'development-input/manifest.json').read_bytes())
for name,digest in manifest['input_hashes'].items():assert sha((d/'development-input'/name).read_bytes())==digest
c=sqlite3.connect((r/'lab.sqlite').as_uri()+'?mode=ro',uri=True);c.row_factory=sqlite3.Row
counts={t:c.execute('select count(*) from '+t).fetchone()[0] for t in ('research_profiles','generation_runs','candidates','research_runs','backtest_executions','releases')}
rr=dict(c.execute('select id,status,stage,error_stage,error_message,verdict from research_runs where id=?',(run,)).fetchone())
ex=[dict(x) for x in c.execute('select id,research_run_id,scenario,status,result_archive_path,total_trades,profit_pct,profit_factor,max_drawdown_pct,metrics_json from backtest_executions where research_run_id=?',(run,))]
c.close()
out=dict(classification='POSTPROCESSING_TECHNICAL_FAILURE_NOT_ECONOMIC_VERDICT',research_run=rr,executions=ex,six_table_counts=counts,native_invocations=1,additional_native_invocations=0,archive=dict(path=str(archive),sha256=sha(archive.read_bytes()),zip_crc_valid=True,members=members,report_identity=report_identity),manifest_input_hashes_verified=True,files={str(p.relative_to(d)):dict(bytes=p.stat().st_size,sha256=sha(p.read_bytes())) for p in d.rglob('*') if p.is_file()},runtime_removed_by_finally=True,runner_summary_persisted=False,original_native_stdout_stderr_persisted=False,provenance_persisted=False,sanitized_archive_survives=True,original_raw_archive_survives=False,metrics_not_imported=True,H_Stress='SEALED_UNREAD_UNACQUIRED',root_cause=dict(callsite='lab/research_console.py:3958',expression='Path(sys.executable).resolve(strict=True)',venv_python='/Users/shenjianpeng/.codex/runs/freqtrade-lab/issue-43-profile-driven-v1/venv/bin/python',resolved_python='/Users/shenjianpeng/.local/share/uv/python/cpython-3.13.13-macos-aarch64-none/bin/python3.13',venv_has_pandas=True,resolved_has_pandas=False,Holdout_same_pattern='lab/research_console.py:4194'))
(r/'development-failure-inspection.json').write_text(json.dumps(out,indent=2)+'\n')
print(json.dumps({k:v for k,v in out.items() if k not in ('files','archive')},ensure_ascii=False))
print(json.dumps({'archive_sha256':out['archive']['sha256'],'members':list(members),'report_identity':report_identity}))
