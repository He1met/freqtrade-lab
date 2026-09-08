#!/usr/bin/env python3
"""Exactly two fixed historical buy-hold diagnostics; never runs B or native."""
import sys,json,os,argparse
from pathlib import Path
from decimal import Decimal as D
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from lab.spot139_model import floor_grid,ceil_grid
from lab.spot139_binding import sha,validate_sources,deny_network
from lab.spot139_feed import decode
RUNTIME=Path('/Users/shenjianpeng/.codex/runs/freqtrade-lab/issue139-attribution-v1')
START=447072;ENTRY=447073;END=464592
COSTS={'base':(D('.001'),D('.0006')),'stress':(D('.002'),D('.0012'))}


def stamp(hour):return datetime.fromtimestamp(hour*3600,timezone.utc)
def value(row):return D(row['equity'])
def pre_boundary(previous,current):
    if previous is None:return D(1000)
    return D(previous['cash'])+sum((D(p['inventory'])*D(current['positions'][s]['mark']) for s,p in previous['positions'].items()),D(0))


def summarize(rows,end=END):
    """Calendar periods use next00 pre-action NAV; final missing00 carries last23."""
    rows=list(rows)
    if not rows or rows[0]['hour']%24 or end%24 or len(rows)!=end-rows[0]['hour'] or any(r['hour']!=rows[0]['hour']+i for i,r in enumerate(rows)):
        raise ValueError('complete contiguous hourly NAV log and UTC day boundaries required')
    previous=None;boundary=D(1000);days={};day_stale=False
    peak=D(1000);maxdd=D(0);exposure=D(0);notional_time=D(0);cash_time=D(0);maximum=D(0);active=0;stale_hours=0
    for row in rows:
        hour=row['hour'];equity=value(row)
        if previous is not None and hour%24==0:
            end_value=pre_boundary(previous,row);day=stamp(hour-24).strftime('%Y-%m-%d')
            boundary_stale=any(D(p['inventory'])>0 and row['positions'][s]['mark_age_hours']>0 for s,p in previous['positions'].items())
            days[day]=dict(start_nav=boundary,end_nav=end_value,change=end_value-boundary,return_fraction=end_value/boundary-1,stale_valuation=day_stale or boundary_stale,end_utc=stamp(hour).isoformat(),terminal_carry_hours=0)
            boundary=end_value;day_stale=False
        marked=sum((D(p['inventory'])*D(p['mark']) for p in row['positions'].values()),D(0));ratio=marked/equity
        exposure+=ratio;maximum=max(maximum,ratio);notional_time+=marked;cash_time+=D(row['cash'])
        active+=int(any(p.get('active',D(p['inventory'])>0) for p in row['positions'].values()))
        stale=any(D(p['inventory'])>0 and p['mark_age_hours']>0 for p in row['positions'].values());day_stale|=stale;stale_hours+=int(stale)
        peak=max(peak,equity);maxdd=max(maxdd,(peak-equity)/peak)
        previous=row
    final=value(rows[-1]);carry=end-rows[-1]['hour'];day=stamp(end-24).strftime('%Y-%m-%d')
    days[day]=dict(start_nav=boundary,end_nav=final,change=final-boundary,return_fraction=final/boundary-1,stale_valuation=day_stale or carry>0,end_utc=stamp(end).isoformat(),terminal_carry_hours=carry)
    months={};years={}
    for key,period in days.items():
        for table,label in [(months,key[:7]),(years,key[:4])]:
            if label not in table:table[label]=dict(start_nav=period['start_nav'],end_nav=period['end_nav'],change=D(0),stale_days=0)
            table[label]['end_nav']=period['end_nav'];table[label]['change']+=period['change'];table[label]['stale_days']+=int(period['stale_valuation'])
    for table in [months,years]:
        for p in table.values():p['return_fraction']=p['end_nav']/p['start_nav']-1
    assert sum((p['change'] for p in days.values()),D(0))==final-1000
    n=len(rows)
    return dict(net=final-1000,terminal_nav=final,daily=days,months=months,years=years,average_notional_to_nav=exposure/n,maximum_notional_to_nav=maximum,notional_usdt_hours=notional_time,average_notional_usdt=notional_time/n,average_cash_usdt=cash_time/n,active_hours=active,in_market_fraction=D(active)/n,observed_open_max_drawdown=maxdd,real_drawdown='UNKNOWN',stale_hours=stale_hours,terminal_boundary_carried_hours=carry,observations=n)


def buyhold(hourly,rules,cost,start=START,entry=ENTRY,end=END):
    fee,slip=COSTS[cost];cash=D(1000);inventory={s:D(0) for s in rules};basis={s:D(0) for s in rules};marks={};marked_at={};buys=[];rows=[]
    for hour in range(start,end):
        for s in rules:
            if hour in hourly[s]:marks[s]=hourly[s][hour][0][0];marked_at[s]=hour
        if hour==entry:
            for s in sorted(rules):
                if hour not in hourly[s]:raise ValueError('fixed benchmark entry has no original open')
                r=rules[s];p=ceil_grid(marks[s]*(1+slip),r.price_tick);q=floor_grid(min(D(400)/p,r.max_qty),r.step)
                if q<r.min_qty or q*p<r.min_notional:raise ValueError('fixed benchmark order invalid; no top-up')
                basefee=ceil_grid(q*fee,r.base_fee_step);inventory[s]=q-basefee;cash-=q*p;basis[s]=q*p
                buys.append(dict(symbol=s,hour=hour,gross_quantity=q,price=p,base_fee=basefee,net_quantity=inventory[s],cost_basis=basis[s]))
        equity=cash+sum((q*marks[s] for s,q in inventory.items()),D(0))
        rows.append(dict(hour=hour,cash=cash,equity=equity,positions={s:dict(inventory=q,mark=marks[s],mark_age_hours=hour-marked_at[s],active=q>0) for s,q in inventory.items()}))
    marked=sum((q*marks[s] for s,q in inventory.items()),D(0))
    return rows,dict(cash=cash,inventory=inventory,basis=basis,marked_inventory=marked,equity=cash+marked,realized=D(0),unrealized=marked-sum(basis.values(),D(0)),estimated_exit_cost=marked*(fee+slip),buys=buys,forced_exit=False,rebalanced=False,risk_equivalent_to_B=False)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('manifest');parser.add_argument('--sha256',required=True);parser.add_argument('--run',action='store_true');args=parser.parse_args()
    if sha(args.manifest)!=args.sha256:raise ValueError('analysis binding changed')
    m=json.loads(Path(args.manifest).read_text());validate_sources(m)
    for c in COSTS:
        if sha(m['results'][c]['path'])!=m['results'][c]['sha256'] or sha(m['logs'][c]['path'])!=m['logs'][c]['sha256']:raise ValueError('result/log changed')
    if not args.run:print('ANALYSIS_CHECK_PASS_NO_COMPUTATION');return
    if RUNTIME.exists():raise ValueError('fixed analysis already started; no repeat/reset')
    RUNTIME.mkdir();sys.addaudithook(deny_network)
    hourly,_,_,rules=decode(m);summary={}
    for cost in COSTS:
        def event(kind,**more):
            with (RUNTIME/'analysis-calls.jsonl').open('a') as stream:
                stream.write(json.dumps(dict(event=kind,cost=cost,at_utc=datetime.now(timezone.utc).isoformat(),script_sha256=sha(__file__),manifest_sha256=args.sha256,**more))+'\n');stream.flush();os.fsync(stream.fileno())
        event('RESERVED_MECHANICAL_BENCHMARK')
        try:
            original=json.load(open(m['results'][cost]['path']))
            b=summarize(json.loads(x) for x in open(m['logs'][cost]['path']))
            if b['terminal_nav']!=D(original['modeled_terminal']['equity']) or b['observations']!=END-START:
                raise ValueError('B log does not reconcile to frozen terminal/window')
            bhrows,terminal=buyhold(hourly,rules,cost);bh=summarize(bhrows)
            result=dict(cost=cost,B_log_attribution=b,B_exit_month_realized=original['realized_by_month'],B_terminal=original['modeled_terminal'],buyhold=bh,buyhold_terminal=terminal,evidence_grade='POST_RESULT_DIAGNOSTIC_NOT_PREREGISTERED_OR_RISK_MATCHED',source_manifest_sha256=args.sha256)
            p=RUNTIME/(cost+'-analysis.json');p.write_text(json.dumps(result,indent=2,default=str)+'\n');summary[cost]=result
            event('SUCCEEDED',result_sha256=sha(p))
        except BaseException as error:event('FAILED',error=str(error));raise
    out=dict(cases=summary,counts=dict(historical_mechanical_benchmark_calculations=2,existing_B_log_aggregations=2,native_market_calls=0,new_gets=0,weight_scans=0,posthoc_exclusion_sensitivities=0),cash_reference=dict(initial=1000,terminal=1000,net=0,interest=0,drawdown=0,kind='ANALYTICAL_IDENTITY_NOT_ANOTHER_BACKTEST'))
    (RUNTIME/'summary.json').write_text(json.dumps(out,indent=2,default=str)+'\n');print(RUNTIME/'summary.json')
if __name__=='__main__':main()
