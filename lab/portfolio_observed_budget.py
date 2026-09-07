"""One-shot approved manifests share the existing append-only native budget."""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
from lab.portfolio_budget import LockedBudget, BudgetError, verify_checkpoint
from lab.portfolio_observed_prepare import jobs, SEMANTICS_SHA, RECEIPT_SHA, BUDGET_PREFIX_SHA, encoded


def validate_activation(activation,plan,plan_raw):
    if plan!=json.loads(plan_raw):raise BudgetError("plan object differs from bound bytes")
    if (activation.get('schema')!='issue125-observed-activation-v1' or
        activation.get('status')!='APPROVED_FIRST_EXPLORATION_BATCH' or
        not activation.get('approval_reference') or
        activation.get('plan_sha256')!=hashlib.sha256(plan_raw).hexdigest()):
        raise BudgetError('explicit matching batch activation required')
    if (activation.get('allowed_manifests')!={k:v['sha256'] for k,v in plan['first_batch'].items()} or
        len(activation['allowed_manifests'])!=10 or
        set(activation['allowed_manifests'])!={j['key'] for j in jobs()[:10]}):
        raise BudgetError('activation must bind the exact first ten; reserved slice sealed')
    if (plan['replacement_map']!={j['key']:j['replaces_unused_key_on_approval'] for j in jobs()} or
        len(set(plan['replacement_map'].values()))!=20 or
        plan['source_receipt_sha256']!=RECEIPT_SHA or plan['semantics_sha256']!=SEMANTICS_SHA or
        plan['native_budget_prefix_sha256']!=BUDGET_PREFIX_SHA):
        raise BudgetError('activation source, semantics or replacement map drift')
    commit=activation.get('code_commit','')
    if len(commit)!=40 or any(c not in '0123456789abcdef' for c in commit):
        raise BudgetError('activation needs reviewed code commit')


class ObservedLockedBudget(LockedBudget):
    def __init__(self,root,activation,plan,plan_raw):
        validate_activation(activation,plan,plan_raw)
        self.activation=activation;self.plan=plan
        raw=(Path(root)/'calls.jsonl').read_bytes()
        verify_checkpoint(raw,{'bytes':plan['native_budget_prefix_bytes'],'sha256':BUDGET_PREFIX_SHA})
        super().__init__(Path(root))

    def _validate_history(self):
        # Validate the unchanged legacy prefix with its own original rules.
        legacy=object.__new__(LockedBudget)
        legacy.events=[r for r in self.events if not r.get('key','').startswith('BTC_ETH_SHORT_FEASIBILITY_V2/')]
        legacy._validate_history()
        opened=set();ended=set()
        allowed=self.activation['allowed_manifests']
        for row in self.events:
            key=row['key'];event=row['event']
            if event=='RESERVED':
                if key in opened or opened-ended:raise BudgetError('duplicate or overlapping reservation')
                opened.add(key)
                if key.startswith('BTC_ETH_SHORT_FEASIBILITY_V2/'):
                    if (key not in allowed or row['input_sha256']!=allowed[key] or
                        row['source_sha256']!=RECEIPT_SHA or row.get('semantics_sha256')!=SEMANTICS_SHA):
                        raise BudgetError('unapproved market history')
            elif event in ('SUCCEEDED','FAILED','INTERRUPTED'):
                if key not in opened or key in ended:raise BudgetError('invalid terminal history')
                ended.add(key)
            elif event!='AUDIT_RECOVERED':raise BudgetError('invalid budget event')
            elif key not in {r['key'] for r in legacy.events}:raise BudgetError('market audit recovery not authorized')
        if len(opened)>96:raise BudgetError('global native budget exceeded')

    def reserve_observed(self,key,manifest_raw):
        digest=hashlib.sha256(manifest_raw).hexdigest()
        if self.activation['allowed_manifests'].get(key)!=digest:
            raise BudgetError('unapproved, retired, sealed or mismatched manifest')
        m=json.loads(manifest_raw)
        if (m['key']!=key or m['source_receipt_sha256']!=RECEIPT_SHA or m['semantics_sha256']!=SEMANTICS_SHA):
            raise BudgetError('manifest binding mismatch')
        if any(r['event'] in ('FAILED','INTERRUPTED') and r['key'] in self.activation['allowed_manifests'] for r in self.events):
            raise BudgetError('BATCH_STOPPED engineering/model-invalid failure; new review required')
        if self.pending():raise BudgetError('interrupted reservation requires terminal audit; no replay')
        if any(r['key']==key for r in self.events):raise BudgetError('key already consumed')
        if sum(r['event']=='RESERVED' for r in self.events)>=96:raise BudgetError('96-call cap')
        return self._append(dict(event='RESERVED',key=key,input_sha256=digest,
            code_sha256=m['code_bundle_sha256'],source_sha256=RECEIPT_SHA,semantics_sha256=SEMANTICS_SHA,
            code_commit=self.activation['code_commit'],retry_of=None,
            activation_sha256=hashlib.sha256(encoded(self.activation)).hexdigest()))


@contextmanager
def locked_observed(root,activation,plan,plan_raw):
    root=Path(root)
    if root.is_symlink():raise BudgetError('symlink budget root')
    fd=os.open(root/'writer.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'r+') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError as exc:raise BudgetError('another portfolio worker owns budget') from exc
        try:yield ObservedLockedBudget(root,activation,plan,plan_raw)
        finally:fcntl.flock(lock,fcntl.LOCK_UN)
