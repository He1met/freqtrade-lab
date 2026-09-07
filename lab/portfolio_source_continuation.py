"""One authorized V2 acquisition, sharing the immutable V1 cumulative budget."""
from contextlib import contextmanager, nullcontext
from pathlib import Path
import json
import time
from lab.portfolio_source import SourceError, Budget, digest, write_json, exclusive

def continuation_allowance(parent_raw, spec):
    if digest(parent_raw)!=spec['parent_budget_sha256']:raise SourceError('parent budget drift')
    parent=json.loads(parent_raw)
    if parent['status']!='BLOCKED_DATA' or len(parent['attempts'])!=37 or parent['charged_bytes']!=7697705:
        raise SourceError('unexpected parent terminal/counters')
    spent=spec['parent_seconds_charged']
    if spent<130:raise SourceError('parent time cannot be refunded')
    return dict(gets=122-37,total_bytes=64*1024*1024-parent['charged_bytes'],seconds=1800-spent)


class ContinuationBudget(Budget):
    """Single v2 cumulative file at the same global budget root, no resets.

    Preparation never constructs this. A future specific activation must bind
    the new approval and parent SHA; original 37 attempts are copied verbatim.
    """
    def __init__(self,parent_path,spec,approval,now=time.time,*,_locked=False):
        if not approval or approval==spec['preparation_authorization']:
            raise SourceError('specific continuation activation authorization required')
        parent_path=Path(parent_path)
        parent_raw=parent_path.read_bytes();continuation_allowance(parent_raw,spec)
        self.path=parent_path.with_name('acquisition-continuation-v2.json')
        if self.path.exists():raise SourceError('continuation already started; no new-root reset')
        self.now=now;self.limits=dict(gets=91,total_bytes=64*1024*1024,response_bytes=5*1024*1024,seconds=1800)
        self.state=json.loads(parent_raw)
        self.state.update(status='CONTINUATION_STARTED',parent_budget_sha256=digest(parent_raw),
                          activation=approval,continuation_started=now(),
                          parent_seconds_charged=spec['parent_seconds_charged'],
                          segment_root=str(Path(self.state['root'])/'continuation-v2'))
        with nullcontext() if _locked else exclusive(str(parent_path)+'.lock'):
            if self.path.exists():raise SourceError('continuation already started; no new-root reset')
            if parent_path.read_bytes()!=parent_raw:raise SourceError('parent changed during activation')
            write_json(self.path,self.state)

    def remaining_time(self):
        return 1800-self.state['parent_seconds_charged']-(self.now()-self.state['continuation_started'])


@contextmanager
def locked_continuation(parent_path,spec,approval):
    # Same lock as V1 capture, held until all requests and terminal writes finish.
    with exclusive(str(parent_path)+'.lock'):
        yield ContinuationBudget(parent_path,spec,approval,_locked=True)
