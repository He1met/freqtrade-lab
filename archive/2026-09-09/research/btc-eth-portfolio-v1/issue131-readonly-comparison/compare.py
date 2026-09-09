"""Only summarize retained actual outputs; no price loading, matcher or native."""
from pathlib import Path
import sys,json,hashlib
from fractions import Fraction
from collections import Counter
ROOT=Path('/Users/shenjianpeng/.codex/worktrees/1b63/freqtrade-lab')
sys.path.insert(0,str(ROOT))
from scripts.diagnose_portfolio_evidence import sample_support,num,serial,sha,read,at
from lab.portfolio_corrected import RUNTIME,PREPARED,ACTIVATION,OUTPUT,mapping,original_evidence
from lab.portfolio_budget import ANCHOR_LEDGER
HERE=Path(__file__).parent
HELPER=ROOT/'scripts/diagnose_portfolio_evidence.py'
assert sha(HELPER)=='671aa085894cf58a0e3fe47d2d83a612e9f8926b545516ffd902ea65d2d1cc4c'
assert sha(ROOT/'docs/protocols/issue127-readonly-diagnosis-v1.json')=='e60fcfb8423e2e2484bf02c0d78a6b06191e8393373afcadc24553ab74dc3274'
assert not (HERE/'input-manifest.json').exists() and not (HERE/'summary.json').exists()

def write(path,value):
    with path.open('x') as f:json.dump(serial(value),f,indent=2,ensure_ascii=False,allow_nan=False);f.write('\n')

bound={str(HELPER):sha(HELPER),str(Path(__file__)):sha(__file__)}
for p in [ROOT/'docs/protocols/issue127-readonly-diagnosis-v1.json',ROOT/'docs/protocols/issue131-corrected-exploration-v1.json',
          PREPARED/'plan.json',ACTIVATION,RUNTIME/'calls.jsonl',ANCHOR_LEDGER]:bound[str(p)]=sha(p)
bound.update(original_evidence())
for i in range(1,11):
    root=OUTPUT/f'{i:02d}';index=root/'evidence-index.json';idx=read(index)
    assert idx['status']=='SUCCEEDED'
    bound[str(index)]=sha(index)
    for name,h in idx['files'].items():bound[str(root/name)]=h
    log=RUNTIME/f'issue131-corrected-{i:02d}.log';bound[str(log)]=sha(log)
for p,h in bound.items():assert sha(p)==h,p
write(HERE/'input-manifest.json',dict(schema='issue131-actual-comparison-input-v1',files=bound,
    natural_definition='UNCHANGED_ISSUE127_FROZEN',new_gets=0,new_native=0))


def actual_money(orders,result,cost):
    gross=sum(num(o['amount'])*num(o['price'])*(1 if o['side']=='sell' else -1) for o in orders)
    fees=sum(num(o['modeled_execution_fee']) for o in orders)
    slip=sum(num(o['amount'])*num(o['price'])*Fraction('.0006' if cost=='base' else '.0012') for o in orders)
    funding=num(result['model_funding']);net=gross-fees-slip+funding
    assert net==num(result['modeled_net'])
    return dict(actual_price_cashflow=gross,modeled_fees_on_actual_fills=fees,modeled_slippage_on_actual_fills=slip,
        modeled_funding_on_actual_inventory=funding,modeled_net=net,exact_identity_verified=True)


def order_signature(o):
    return json.dumps({k:o[k] for k in ['pair','filled_at','side','amount','price','tag']},sort_keys=True)

rows=[]
for i,job in enumerate(mapping(),1):
    newroot=OUTPUT/f'{i:02d}';oldroot=RUNTIME/'observed-jobs'/f'{i:02d}'
    r=read(newroot/'result.json');old=read(oldroot/'result.json')
    orders=read(newroot/'actual-orders.json');oldorders=read(oldroot/'actual-orders.json')
    trace=read(newroot/'trace.json');oldtrace=read(oldroot/'trace.json')
    assert [r['time'] for r in trace]==[r['time'] for r in oldtrace]
    natural,episodes,increases=sample_support(read(newroot/'episode-events.json'),trace,orders,
        read(newroot/'position-cycles.json'),job['mode'])
    changed={p:sum(num(x['targets'][p])!=num(y['targets'][p]) for x,y in zip(trace,oldtrace)) for p in trace[0]['targets']}
    pair_changed={p:[] for p in changed}
    for x,y in zip(trace,oldtrace):
        for p in changed:
            if num(x['targets'][p])!=num(y['targets'][p]):
                pair_changed[p].append(dict(time=x['time'],old=y['targets'][p],new=x['targets'][p],actual=x['actual_inventory'][p]))
    before=Counter(map(order_signature,oldorders));after=Counter(map(order_signature,orders))
    added=list((after-before).elements());removed=list((before-after).elements())
    money=actual_money(orders,r,job['cost']);oldmoney=actual_money(oldorders,old,job['cost'])
    row=dict(index=i,key=job['key'],mode=job['mode'],cost=job['cost'],status='SUCCEEDED',integrity='PASS',
        new_result_sha256=sha(newroot/'result.json'),old_result_sha256=sha(oldroot/'result.json'),
        new_evidence_index_sha256=sha(newroot/'evidence-index.json'),new_root=str(newroot),old_root=str(oldroot),
        new_model=money,old_implementation_affected_model=oldmoney,
        actual_model_differences={k:money[k]-oldmoney[k] for k in money if k!='exact_identity_verified'},
        new_max_drawdown=num(r['modeled_max_drawdown']),old_max_drawdown=num(old['modeled_max_drawdown']),
        new_net_gate=r['modeled_net_gate'],new_risk_gate=r['modeled_risk_gate'],
        new_actual_position_cycles=r['actual_closed_position_cycles'],old_actual_position_cycles=old['actual_closed_position_cycles'],
        old_order_count=len(oldorders),new_order_count=len(orders),actual_order_signature_multisets_equal=before==after,
        different_actual_orders_new=[json.loads(o) for o in added],different_actual_orders_old=[json.loads(o) for o in removed],
        target_changed_hours_by_asset=changed,target_change_examples={p:rs[:3] for p,rs in pair_changed.items()},
        natural_support=natural,model_label=r['label'],economic_qualification=r['economic_qualification'],
        native_funding=num(r['native_funding']),native_funding_delta=num(r['native_funding_delta']),
        native_rejection_reasons='UNKNOWN_NO_NATIVE_REJECTION_RECEIPT',new_independence=False)
    assert read(newroot/'terminal-integrity.json')['status']=='PASS'
    write(HERE/f'natural-support-{i:02d}.json',dict(key=job['key'],natural=natural,episodes=episodes,actual_increases=increases))
    rows.append(row)
for p,h in bound.items():assert sha(p)==h,p
write(HERE/'summary.json',dict(schema='issue131-actual-paired-summary-v1',script_sha256=sha(__file__),
    helper_sha256=sha(HELPER),input_manifest_sha256=sha(HERE/'input-manifest.json'),jobs=rows,
    all_input_hashes_unchanged=True,additional_native=0,new_gets=0,new_synthetic_returns=0,
    comparison='ACTUAL_OUTPUT_ONLY; SAME_EXPOSED_WINDOW; NO_INDEPENDENCE',natural_counts_not_pooled=True))
for r in rows:
    print(r['index'],r['mode'],r['cost'],'orders',r['old_order_count'],r['new_order_count'],
          'target_hours',r['target_changed_hours_by_asset'],'counts',
          {f:(v['natural_clusters'],v['proven_cluster_upper_bound']) for f,v in r['natural_support'].items()})
print('SUMMARY_SHA',sha(HERE/'summary.json'))
