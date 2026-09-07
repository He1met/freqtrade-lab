import runpy,sys,traceback
from pathlib import Path
entry=Path('scripts/dispatch_portfolio_causal_probe.py').resolve()
def record_exception(frame,event,arg):
    if event=='exception' and Path(frame.f_code.co_filename)==entry:
        print('DISPATCH_EXCEPTION_FULL_TRACEBACK',file=sys.stderr)
        traceback.print_exception(*arg,file=sys.stderr)
    return record_exception
sys.settrace(record_exception)
sys.argv=[str(entry),'--native-source','/Users/shenjianpeng/.codex/runs/freqtrade-lab/issue-43-profile-driven-v1/freqtrade','--slot','synthetic/7','--execute-approved']
runpy.run_path(str(entry),run_name='__main__')
