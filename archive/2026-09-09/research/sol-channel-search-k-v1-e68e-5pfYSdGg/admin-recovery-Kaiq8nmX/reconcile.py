"""Read-only DB/API/source reconciliation of this cohort's original and recovery instances."""
from pathlib import Path
import json,hashlib,datetime
from lab.database import get_connection
from lab.codex_generation import load_approved_candidate_snapshot
from http_request import request
R=Path(__file__).resolve().parent;OLD=R.parent
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
tables=('research_profiles','generation_runs','candidates','research_runs','backtest_executions','releases')
instances={}
for label,root in [('original',OLD),('recovery',R)]:
    with get_connection(root/'research.sqlite',read_only=True) as c:
        c.execute('BEGIN')
        actual=[x[0] for x in c.execute("SELECT name FROM sqlite_master WHERE type='table'")]; assert set(actual)==set(tables)
        counts={t:c.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in tables}
        assert all(counts[t]==0 for t in tables[-3:])
        gen=[dict(x) for x in c.execute('SELECT id,source,model,status,started_at,finished_at,returned_strategy_count,error_message FROM generation_runs')]
        candidates=[dict(x) for x in c.execute('SELECT id,generation_run_id,parent_candidate_id,class_name,code_sha256,strategy_family,metadata_json FROM candidates')]
        for row in candidates:
            approved=load_approved_candidate_snapshot(c,row['id'])
            assert approved.code_sha256==sha(OLD/(row['class_name']+'.py'))
            gr=root/'console-runtime/campaigns'/row['generation_run_id']
            output=json.loads((gr/'codex-output.json').read_text())
            assert output['code_text'].encode()==(OLD/(row['class_name']+'.py')).read_bytes()
            row['raw_generation_output_sha256']=sha(gr/'codex-output.json')
            row['stdout_sha256']=sha(gr/'stdout.log');row['stderr_sha256']=sha(gr/'stderr.log')
        instances[label]={'database':str(root/'research.sqlite'),'database_sha256':sha(root/'research.sqlite'),'counts':counts,'generations':gen,'candidates':candidates}
assert instances['original']['database_sha256']==json.loads((R/'administrative-recovery-initialized.json').read_text())['old_database_after_console_stop_sha256']
api={}
for label,path in [('search','/api/search/context'),('research','/api/research/context'),('generation','/api/generation/context'),('preflight','/api/control/preflight')]:
    status,value=request(path,None,'final-'+label);assert status==200;api[label]=value
terminal=json.loads((OLD/'search/search-terminal.json').read_text())
assert api['search']['state']['status']==terminal['status']
assert api['search']['state']['budget']['consumed_total']==2
assert len(api['search']['state']['attempts'])==2
assert len(list((OLD/'search').rglob('*.zip')))==2
for name,digest in json.loads((OLD/'freeze-manifest.json').read_text())['files'].items(): assert sha(OLD/name)==digest
document={'recorded_at_utc':datetime.datetime.now(datetime.UTC).isoformat(),'instances':instances,'original_records_preserved':True,'native_executions_cumulative':2,'CODEX_generations_cumulative':sum(sum(g['source']=='CODEX' for g in x['generations']) for x in instances.values()),'api':api,'terminal_sha256':sha(OLD/'search/search-terminal.json'),'trials_sha256':sha(OLD/'search/trials.jsonl'),'all_original_frozen_files_unchanged':True,'no_D_H_Stress_Judge_Release':True,'frequi_status':api['preflight']['checks']['frequi']['status']}
target=OLD/'database-api-reconciliation.json';assert not target.exists();target.write_text(json.dumps(document,indent=2)+'\n')
print(json.dumps({'counts':{k:v['counts'] for k,v in instances.items()},'native_executions':2,'CODEX_generations':document['CODEX_generations_cumulative'],'status':terminal['status'],'terminal_sha256':document['terminal_sha256'],'frequi_status':document['frequi_status']},indent=2))
