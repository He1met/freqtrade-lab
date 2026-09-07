"""One bounded correction batch; reuses the observed consumer and global budget."""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

from lab.portfolio_budget import LockedBudget, BudgetError, verify_checkpoint, verify_anchor
from lab import portfolio_observed_prepare as old
from lab.portfolio_observed_budget import ObservedLockedBudget, validate_activation as validate_old
from lab.portfolio_short import RESERVE_SEMANTICS_VERSION
from lab.portfolio_source import SourceError

ROOT = old.ROOT
RUNTIME = old.RUNTIME_ROOT
PREPARED = RUNTIME/'issue131-corrected-prepared'
ACTIVATION = RUNTIME/'corrected-exploration-activation.json'
OUTPUT = RUNTIME/'corrected-exploration-jobs'
PROTOCOL = ROOT/'docs/protocols/issue131-corrected-exploration-v1.json'
PROTOCOL_SHA = 'df83beb6e030fa6039ad2757dc7eaecb503c96353df3fa2171e1186f9b3559d7'
encoded, sha = old.encoded, old.sha


def protocol():
    if sha(PROTOCOL) != PROTOCOL_SHA:
        raise SourceError('corrected protocol drift')
    spec = json.loads(PROTOCOL.read_bytes())
    if RESERVE_SEMANTICS_VERSION != spec['repair_semantics']:
        raise SourceError('repair semantics drift')
    return spec


def original():
    spec = protocol()
    raw = (old.PREPARED/'plan.json').read_bytes()
    act_raw = old.ACTIVATION.read_bytes()
    if hashlib.sha256(raw).hexdigest() != spec['original_plan_sha256'] or hashlib.sha256(act_raw).hexdigest() != spec['original_activation_sha256']:
        raise SourceError('original plan/activation drift')
    plan, activation = json.loads(raw), json.loads(act_raw)
    validate_old(activation, plan, raw)
    return plan, activation


def mapping():
    spec = protocol()
    from lab.portfolio_preflight import PROTOCOL_PATH, native_job_plan
    catalog = {j['key'] for j in native_job_plan(json.loads(PROTOCOL_PATH.read_bytes())) if j['role'] != 'SYNTHETIC'}
    occupied = {j['replaces_unused_key_on_approval'] for j in old.jobs()}
    targets = [j['replaces_unused_key_on_approval'] for j in spec['jobs']]
    if len(targets) != 10 or len(set(targets)) != 10 or not set(targets) <= catalog-occupied:
        raise SourceError('new mapping overlaps old/reserved or unknown resources')
    return spec['jobs']


def original_manifest(job):
    plan, _ = original()
    item = plan['first_batch'][job['original_key']]
    raw = Path(item['path']).read_bytes()
    if hashlib.sha256(raw).hexdigest() != item['sha256']:
        raise SourceError('original manifest drift')
    return json.loads(raw), item['sha256']


def original_evidence():
    path=ROOT/'docs/issue127-input-manifest.json'
    if sha(path)!=protocol()['original_evidence_manifest_sha256']:
        raise SourceError('original evidence manifest drift')
    files=json.loads(path.read_bytes())['files']
    return {p:h for p,h in files.items() if str(RUNTIME/'observed-jobs')+'/' in p}


def corrected_manifest(job, index, bundle, env):
    base, old_sha = original_manifest(job)
    # Preserve every original model, config, input and scoring field.
    result = dict(base, schema='issue131-corrected-job-v1', key=job['key'],
        replaces_unused_key_on_approval=job['replaces_unused_key_on_approval'],
        original_key=job['original_key'], original_manifest_sha256=old_sha,
        original_evidence={p:h for p,h in original_evidence().items() if f'/observed-jobs/{index:02d}/' in p},
        correction_protocol_sha256=PROTOCOL_SHA, reserve_semantics=RESERVE_SEMANTICS_VERSION,
        code_files=bundle, code_bundle_sha256=hashlib.sha256(encoded(bundle)).hexdigest(),
        environment=env, prepared_root=str(PREPARED), output_root=str(OUTPUT/f'{index:02d}'),
        command=[sys.executable,str(ROOT/'scripts/run_portfolio_corrected.py'),'--run-key',job['key']],
        native_budget_prefix_bytes=protocol()['budget_prefix_bytes'],
        native_budget_prefix_sha256=protocol()['budget_prefix_sha256'])
    return result


def expected_plan(manifests):
    spec = protocol()
    return dict(schema='issue131-corrected-plan-v1', status='PREPARED_NOT_AUTHORIZED',
        batch=spec['batch'], correction_protocol_sha256=PROTOCOL_SHA,
        native_total=96, consumed=18, proposed_jobs=10, consumed_if_completed=28,
        remaining_if_completed=68, unallocated_after_activation=58,
        native_budget_prefix_bytes=spec['budget_prefix_bytes'],
        native_budget_prefix_sha256=spec['budget_prefix_sha256'],
        first_batch=manifests, reserved_keys=spec['original_reserved_keys'],
        replacement_map={j['key']:j['replaces_unused_key_on_approval'] for j in mapping()},
        old_plan_sha256=spec['original_plan_sha256'], old_activation_sha256=spec['original_activation_sha256'],
        native_calls_executed=0, activation_authority=None)


def prepare():
    if PREPARED.exists() or ACTIVATION.exists() or OUTPUT.exists():
        raise SourceError('corrected output/control exists; never overwrite')
    spec = protocol(); original(); verify_anchor()
    env = old.environment(); bundle = old.code_files()
    raw = (RUNTIME/'calls.jsonl').read_bytes()
    if len(raw) != spec['budget_prefix_bytes'] or hashlib.sha256(raw).hexdigest() != spec['budget_prefix_sha256']:
        raise BudgetError('18-call budget changed before preparation')
    rows = [json.loads(line) for line in raw.splitlines()]
    if sum(r['event']=='RESERVED' for r in rows) != 18:
        raise BudgetError('18-call prefix required')
    legacy = object.__new__(ObservedLockedBudget)
    legacy.events=rows; legacy.activation=original()[1]; legacy._validate_history()
    if legacy.pending():
        raise BudgetError('old prefix pending')
    for path,digest in original_evidence().items():
        if sha(path)!=digest:raise SourceError('original execution evidence drift')
    jobs = mapping()
    manifests = [corrected_manifest(j,i+1,bundle,env) for i,j in enumerate(jobs)]
    # Copy approved bytes only; no source conversion, native imports or scoring.
    inputs = {f'data/{n}':h for n,h in manifests[0]['data_files'].items()}
    inputs.update({'assembly.json':manifests[0]['assembly_sha256'],
                   'events.json':manifests[0]['funding_event_table_sha256']})
    for name, digest in inputs.items():
        if sha(old.PREPARED/name) != digest:
            raise SourceError('old input view drift')
    PREPARED.mkdir(parents=True); (PREPARED/'jobs').mkdir(); (PREPARED/'data').mkdir()
    for name, digest in inputs.items():
        target=PREPARED/name; target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(old.PREPARED/name,target)
        if sha(target) != digest:
            raise SourceError('copied view differs')
    entries={}
    for i,m in enumerate(manifests):
        p=PREPARED/'jobs'/f'{i+1:02d}.json'; p.write_bytes(encoded(m))
        entries[m['key']]=dict(path=str(p),sha256=sha(p))
    plan=expected_plan(entries); (PREPARED/'plan.json').write_bytes(encoded(plan))
    template=dict(schema='issue131-corrected-activation-v1',status='NOT_APPROVED',
        approval_reference=None,code_commit=None,correction_protocol_sha256=PROTOCOL_SHA,
        plan_sha256=sha(PREPARED/'plan.json'),allowed_manifests={k:v['sha256'] for k,v in entries.items()})
    (PREPARED/'activation-template.json').write_bytes(encoded(template))
    if (RUNTIME/'calls.jsonl').read_bytes()!=raw:
        raise BudgetError('budget changed during preparation')
    return dict(prepared_root=str(PREPARED),plan_sha256=sha(PREPARED/'plan.json'),
                native_calls=0,new_gets=0,jobs=10,sealed=10)


def validate_activation(activation, plan, raw):
    protocol(); original()
    if plan != json.loads(raw) or plan != expected_plan(plan.get('first_batch',{})):
        raise BudgetError('corrected plan drift')
    allowed={k:v['sha256'] for k,v in plan['first_batch'].items()}
    if set(allowed)!={j['key'] for j in mapping()}:
        raise BudgetError('exact new ten required; old and reserved sealed')
    for i,j in enumerate(mapping()):
        item=plan['first_batch'][j['key']]
        if item['path']!=str(PREPARED/'jobs'/f'{i+1:02d}.json'):
            raise BudgetError('corrected manifest path drift')
    if (activation.get('schema')!='issue131-corrected-activation-v1' or
        activation.get('status')!='APPROVED_CORRECTED_EXPLORATORY_BATCH' or
        not activation.get('approval_reference') or
        activation.get('correction_protocol_sha256')!=PROTOCOL_SHA or
        activation.get('plan_sha256')!=hashlib.sha256(raw).hexdigest() or
        activation.get('allowed_manifests')!=allowed):
        raise BudgetError('explicit corrected batch approval required')
    commit=activation.get('code_commit')
    if not isinstance(commit,str) or len(commit)!=40 or any(c not in '0123456789abcdef' for c in commit):
        raise BudgetError('reviewed execution commit required')


def verify_manifest(manifest, *, source=True):
    jobs=mapping()
    index=next((i for i,j in enumerate(jobs) if j['key']==manifest.get('key')),None)
    if index is None or manifest!=corrected_manifest(jobs[index],index+1,old.code_files(),old.environment()):
        raise SourceError('corrected manifest/code/environment drift')
    for name,digest in manifest['data_files'].items():
        if sha(PREPARED/'data'/name)!=digest:raise SourceError('corrected data view drift')
    for name,field in [('assembly.json','assembly_sha256'),('events.json','funding_event_table_sha256')]:
        if sha(PREPARED/name)!=manifest[field]:raise SourceError('corrected assembly/events drift')
    if source:
        # Original source/protection/config checks, with current code identity.
        projection,_=original_manifest(jobs[index])
        projection.update(code_files=manifest['code_files'],environment=manifest['environment'])
        old.verify_prepared(old.PREPARED,projection)


class CorrectedBudget(LockedBudget):
    def __init__(self,root,activation,plan,raw):
        validate_activation(activation,plan,raw)
        self.activation=activation;self.plan=plan
        self.prefix=protocol()['budget_prefix_bytes']
        data=(Path(root)/'calls.jsonl').read_bytes()
        verify_checkpoint(data,{'bytes':self.prefix,'sha256':protocol()['budget_prefix_sha256']})
        self.prefix_rows=len(data[:self.prefix].splitlines())
        super().__init__(Path(root))

    def _validate_history(self):
        legacy=object.__new__(ObservedLockedBudget)
        legacy.events=self.events[:self.prefix_rows];legacy.activation=original()[1]
        legacy._validate_history()
        if legacy.pending() or sum(r['event']=='RESERVED' for r in legacy.events)!=18:
            raise BudgetError('original 18-call prefix not complete')
        opened=set();ended=set();allowed=self.activation['allowed_manifests']
        stopped=False
        for row in self.events[self.prefix_rows:]:
            key=row['key'];event=row['event']
            if event=='RESERVED':
                if stopped or key not in allowed or key in opened or opened-ended:
                    raise BudgetError('invalid corrected history or batch stopped')
                if (row['input_sha256']!=allowed[key] or row.get('correction_protocol_sha256')!=PROTOCOL_SHA or
                    row.get('source_sha256')!=old.RECEIPT_SHA or row.get('semantics_sha256')!=old.SEMANTICS_SHA or
                    row.get('retry_of') is not None or row.get('code_commit')!=self.activation['code_commit'] or
                    row.get('activation_sha256')!=hashlib.sha256(encoded(self.activation)).hexdigest() or
                    row.get('replaces_unused_key_on_approval')!=self.plan['replacement_map'][key]):
                    raise BudgetError('corrected reservation binding drift')
                opened.add(key)
            elif event in ('SUCCEEDED','FAILED','INTERRUPTED'):
                if key not in opened or key in ended:raise BudgetError('invalid corrected terminal')
                ended.add(key);stopped=stopped or event!='SUCCEEDED'
            else:raise BudgetError('corrected retry/audit recovery prohibited')
        if len(opened)>10 or sum(r['event']=='RESERVED' for r in self.events)>96:
            raise BudgetError('cumulative budget exceeded')

    def reserve_corrected(self,key,raw):
        digest=hashlib.sha256(raw).hexdigest()
        if self.activation['allowed_manifests'].get(key)!=digest:
            raise BudgetError('unapproved old/sealed/mismatched key')
        m=json.loads(raw)
        if (m.get('key')!=key or m.get('correction_protocol_sha256')!=PROTOCOL_SHA or
            m.get('source_receipt_sha256')!=old.RECEIPT_SHA or m.get('semantics_sha256')!=old.SEMANTICS_SHA):
            raise BudgetError('corrected manifest binding mismatch')
        recent=self.events[self.prefix_rows:]
        if any(r['event'] in ('FAILED','INTERRUPTED') for r in recent):
            raise BudgetError('BATCH_STOPPED first engineering failure')
        if self.pending() or any(r['key']==key for r in self.events):
            raise BudgetError('pending or consumed; no replay')
        index=sum(r['event']=='RESERVED' for r in recent)
        if index>=10 or key!=mapping()[index]['key']:
            raise BudgetError('fixed ten-job order required')
        if m.get('replaces_unused_key_on_approval')!=self.plan['replacement_map'][key]:
            raise BudgetError('resource mapping drift')
        if sum(r['event']=='RESERVED' for r in self.events)>=96:
            raise BudgetError('96-call cap')
        return self._append(dict(event='RESERVED',key=key,input_sha256=digest,
            code_sha256=m['code_bundle_sha256'],source_sha256=old.RECEIPT_SHA,semantics_sha256=old.SEMANTICS_SHA,
            correction_protocol_sha256=PROTOCOL_SHA,code_commit=self.activation['code_commit'],retry_of=None,
            replaces_unused_key_on_approval=self.plan['replacement_map'][key],
            activation_sha256=hashlib.sha256(encoded(self.activation)).hexdigest()))


@contextmanager
def locked(activation,plan,raw):
    if RUNTIME.is_symlink():raise BudgetError('symlink budget root')
    fd=os.open(RUNTIME/'writer.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'r+') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError as exc:raise BudgetError('another budget writer') from exc
        try:yield CorrectedBudget(RUNTIME,activation,plan,raw)
        finally:fcntl.flock(lock,fcntl.LOCK_UN)


def run(key):
    if not ACTIVATION.exists():raise BudgetError('corrected activation absent; no native authorization')
    ar=ACTIVATION.read_bytes();activation=json.loads(ar)
    pr=(PREPARED/'plan.json').read_bytes();plan=json.loads(pr)
    validate_activation(activation,plan,pr)
    if key not in plan['first_batch']:raise BudgetError('old or sealed key')
    path=Path(plan['first_batch'][key]['path']);raw=path.read_bytes();m=json.loads(raw)
    if hashlib.sha256(raw).hexdigest()!=plan['first_batch'][key]['sha256']:
        raise SourceError('corrected manifest SHA drift')
    verify_manifest(m);verify_anchor()
    from lab.portfolio_observed_integrity import controlled_hashes,freeze
    from scripts.run_portfolio_observed import execute_reserved
    with locked(activation,plan,pr) as budget:
        verify_anchor()
        if ACTIVATION.read_bytes()!=ar or (PREPARED/'plan.json').read_bytes()!=pr or path.read_bytes()!=raw:
            raise SourceError('CONTROL_INTEGRITY lock-time drift')
        verify_manifest(m)
        expected=controlled_hashes(path,m,raw,ar,pr,prepared=PREPARED,activation_path=ACTIVATION)
        expected.update(original_evidence())
        # Preserve original packages and result indices for paired comparison.
        legacy_plan,_=original()
        for p,h in [(old.PREPARED/'plan.json',protocol()['original_plan_sha256']),
                    (old.ACTIVATION,protocol()['original_activation_sha256'])]:expected[str(p)]=h
        for j in mapping():
            item=legacy_plan['first_batch'][j['original_key']];expected[item['path']]=item['sha256']
        before=freeze(expected,expected)
        if before['project']['commit']!=activation['code_commit']:
            raise SourceError('exact reviewed execution commit required')
        output=Path(m['output_root'])
        if output.exists():raise SourceError('corrected output exists; no overwrite')
        output.mkdir(parents=True);(output/'manifest.json').write_bytes(raw)
        before['files'][str(output/'manifest.json')]=sha(output/'manifest.json')
        budget.reserve_corrected(key,raw)
        return execute_reserved(output,key,m,budget,before)
