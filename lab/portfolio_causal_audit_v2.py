"""New semantics audit, never reclassifies synthetic/6 or edits its assertions."""
from datetime import datetime,timedelta
from decimal import Decimal
from lab.portfolio_causal import PAIRS
from lab.portfolio_causal_audit import audit_halt_liquidation
from lab.portfolio_execution import dec,fill_equity


def audit_v2(result,trace,start):
    def require(test,message):
        if not test: raise ValueError(message)
    require(trace and trace[0]['time']==start.isoformat(),'first daily boundary missing')
    require(not any('fatal_error' in p for p in trace),'callback failed')
    trades=result['trades'];fills=[]
    require(trades and {t['pair'] for t in trades}==set(PAIRS),'both pairs must trade')
    for t in trades:
        require(t['leverage']==1 and t['fee_open']==t['fee_close']==.0006,'fee/leverage mismatch')
        for o in t['orders']:
            fills.append(dict(pair=t['pair'],side=o['ft_order_side'],amount=o['amount'],price=o['safe_price'],
                              time=o['order_filled_timestamp'],is_entry=o['ft_is_entry']))
    requests=[];confirmations=[];resumes=[]
    for point in trace:
        for event in point['hard_cap_fallback']:
            if event['event']=='FULL_REDUCE_ONLY_INTENT':requests.append((point,event))
            elif event['event']=='ACTUAL_FLAT_CONFIRMED':confirmations.append((point,event))
            elif event['event']=='RESUME_AT_FRESH_DAILY_BOUNDARY':resumes.append((point,event))
    require(requests and confirmations and resumes,'fallback/confirmation/resume coverage absent')
    liquidation=[]
    for point,event in requests:
        pair=event['pair'];stamp=int(datetime.fromisoformat(point['time']).timestamp()*1000)
        actual=dec(point['inventory'][pair])
        before=sum((dec(f['amount'])*(1 if f['side']=='buy' else -1) for f in fills if f['pair']==pair and f['time']<stamp),Decimal(0))
        require(abs(before-actual)<Decimal('1e-8'),'fallback inventory differs from real fills')
        delta=sum((dec(f['amount'])*(1 if f['side']=='buy' else -1) for f in fills if f['pair']==pair and f['time']==stamp),Decimal(0))
        require(actual!=0 and abs(actual+delta)<Decimal('1e-8'),'full fallback not filled at earliest open')
        require(not any(f['is_entry'] and f['pair']==pair and f['time']==stamp for f in fills),'fallback adds risk')
        confirmation=next((e for p,e in confirmations if e['pair']==pair and int(datetime.fromisoformat(e['receipt']).timestamp()*1000)==stamp),None)
        require(confirmation is not None,'latest cycle actual flat confirmation missing')
        boundary=datetime.fromisoformat(confirmation['pause_until'])
        expected=datetime.fromisoformat(confirmation['receipt']).replace(hour=0,minute=0,second=0,microsecond=0)+timedelta(days=1)
        require(boundary==expected,'pause does not reach strict next UTC daily boundary')
        require(not any(f['pair']==pair and f['is_entry'] and stamp<=f['time']<int(boundary.timestamp()*1000) for f in fills),'entry during risk pause')
        liquidation.append(dict(pair=pair,at=point['time'],actual_before=str(actual),actual_delta=str(delta),residual=str(actual+delta),pause_until=boundary.isoformat()))
    require(any(p['daily_decision'] and p['episodes'] for p in trace),'real daily indicators absent')
    require(any(p['paused_assets'] and p['episodes'] for p in trace),'paused episodes not retained')
    for pair in PAIRS:
        require(any(f['pair']==pair and f['is_entry'] and f['time']==int((start+timedelta(days=1)).timestamp()*1000) for f in fills),'actual first daily resume missing')
        require(sum(e['pair']==pair for _,e in confirmations)>=2,'second cycle flat proof not exercised')
    require(not any(p['unexecutable_reductions'] or p['blocked_assets'] for p in trace),'unresolved reduction blocked')
    halt=audit_halt_liquidation(fills,trace)
    require(all(t['funding_fees'] is not None for t in trades),'missing native funding')
    net=fill_equity(fills,{p:1 for p in PAIRS},funding=sum(t['funding_fees'] for t in trades),slippage='.0006')
    require(all(abs(q)<Decimal('1e-8') for q in net['inventory'].values()),'final actual inventory remains')
    slip=sum(dec(f['amount'])*dec(f['price'])*Decimal('.0006') for f in fills)
    require(abs(net['equity']-(1000+sum(dec(t['profit_abs']) for t in trades)-slip))<Decimal('.00001'),'net fee/slip reconciliation failed')
    dd=max(dec(p['max_drawdown']) for p in trace)
    return dict(status='V2_SYNTHETIC_CONTROL_PASS',full_exit_receipts=liquidation,halt_liquidation=halt,
                final_net_equity_synthetic_only=str(net['equity']),fees_and_slippage=str(net['costs']),
                max_mark_drawdown=str(dd),risk_limit_satisfied=dd<=Decimal('.20'),
                cash_insufficiency='NOT_COVERED_NATIVE',funding_real_settlement='UNVERIFIED',market_execution_allowed=False,economic_result=None)
