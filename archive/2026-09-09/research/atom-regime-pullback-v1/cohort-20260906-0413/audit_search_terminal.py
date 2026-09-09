"""One S ZIP, Decimal trade accounting; no native run or later-phase inputs."""
import hashlib
import json
import zipfile
from decimal import Decimal
from pathlib import Path
from datetime import datetime,timezone

ROOT=Path(__file__).resolve().parent
D=lambda x:Decimal(str(x))
DAY=86400000
STOP=int(datetime(2023,9,1,tzinfo=timezone.utc).timestamp()*1000)
ARCHIVE=ROOT/'search/search-results-round-1/232031bf-5e0b-44ff-82be-8b7e30afaa38/raw/backtest-result-2026-09-06_04-25-30.zip'
ARCHIVE_SHA='ad3881b9896faeecd6ef946329d699fbabd8edf5970c4e91e6e8f0599939088d'

def exposure_groups(rows,stop):
    groups=[]
    for row in sorted(rows,key=lambda r:r['entry_timestamp']):
        start,end=row['entry_timestamp'],row['exit_timestamp']
        if not groups or start>groups[-1]['end']:
            groups.append({'start':start,'end':start+30*DAY,'trades':[],'all_natural':True,'natural_count':0,'base':D(0),'sensitivity':D(0)})
        g=groups[-1]
        g['end']=max(g['end'],end)
        g['trades'].append(row['number'])
        g['all_natural'] &= row['natural']
        g['natural_count']+=int(row['natural'])
        g['base']+=D(row['base_profit']);g['sensitivity']+=D(row['sensitivity_profit'])
    for g in groups:g['complete']=g['end']<=stop and g['all_natural']
    return groups

def daily_mtm(events,closes):
    """Daily close equity after actual timestamped cash/position events.

    Events already contain native fee + extra slip exactly once per leg.
    Close tuples use end-of-day timestamps. Exit before entry for equal times.
    """
    cash=D(1000);quantity=D(0);peak=D(1000);drawdown=D(0);points=[];index=0
    ordered=sorted(events,key=lambda e:(e['timestamp'],0 if e['side']=='sell' else 1))
    for timestamp,close in closes:
        while index<len(ordered) and ordered[index]['timestamp']<=timestamp:
            e=ordered[index];value=D(e['quantity'])*D(e['price']);cost=D(e['native_fee'])+D(e['extra_slip'])
            if e['side']=='buy':cash-=value+cost;quantity+=D(e['quantity'])
            else:cash+=value-cost;quantity-=D(e['quantity'])
            assert quantity>=0
            index+=1
        equity=cash+quantity*D(close);peak=max(peak,equity);drawdown=max(drawdown,(peak-equity)/peak)
        points.append(str(equity))
    assert index==len(ordered)
    return {'equities':points,'maximum_drawdown':str(drawdown),'final_cash':str(cash),'final_quantity':str(quantity)}

def synthetic_checks():
    def row(n,a,b,natural=True):return {'number':n,'entry_timestamp':a*DAY,'exit_timestamp':b*DAY,'natural':natural,'base_profit':'1','sensitivity_profit':'1'}
    # Holding past day30 extends to45; entry exactly45 belongs to that group;
    # it extends to70. Day71 starts next, whose day101 end is beyond stage100.
    g=exposure_groups([row(1,0,45),row(2,45,70),row(3,71,75)],100*DAY)
    assert [x['trades'] for x in g]==[[1,2],[3]] and [x['complete'] for x in g]==[True,False]
    assert g[0]['end']==70*DAY
    assert not exposure_groups([row(1,0,5,False)],100*DAY)[0]['complete']
    # Native fee .5 plus extra .5 at each leg, exactly once. Day1 unrealized
    # loss is visible although the position later exits at the entry price.
    events=[{'timestamp':0,'side':'buy','quantity':5,'price':100,'native_fee':'.5','extra_slip':'.5'},
            {'timestamp':DAY,'side':'sell','quantity':5,'price':100,'native_fee':'.5','extra_slip':'.5'}]
    m=daily_mtm(events,[(DAY-1,90),(2*DAY-1,100)])
    assert m['equities']==['949.0','998.0'] and D(m['maximum_drawdown'])==D('.051') and D(m['final_cash'])==998 and D(m['final_quantity'])==0
    return {'groups_recursive_extension_and_same_time_boundary':'PASS','incomplete_tail_and_forced_exit':'PASS','daily_unrealized_loss_and_per_leg_cost_timing':'PASS','network_calls':0,'native_runs':0}

def main():
    tests=synthetic_checks()
    assert hashlib.sha256(ARCHIVE.read_bytes()).hexdigest()==ARCHIVE_SHA
    with zipfile.ZipFile(ARCHIVE) as z:
        report=json.loads(z.read(ARCHIVE.stem+'.json'))['strategy']['AtomRegimePullbackV1']
        config=json.loads(z.read(ARCHIVE.stem+'_config.json'))
    assert report['timerange']=='20210901-20230901' and report['stake_amount']==500 and report['starting_balance']==1000
    assert report['trading_mode']=='spot' and report['timeframe']=='1d' and config['fee']==.001
    assert config['exchange']['pair_whitelist']==['ATOM/USDT'] and config['max_open_trades']==1
    trades=sorted(report['trades'],key=lambda t:t['open_timestamp']); rows=[];previous_exit=0
    cash={s:D(1000) for s in ['native','base','sensitivity']};violations={s:[] for s in cash}
    gross=fees=legs=native=rounding=D(0)
    for n,t in enumerate(trades,1):
        assert t['open_timestamp']>=previous_exit;previous_exit=t['close_timestamp']
        assert not t['is_short'] and t['leverage']==1 and not t['is_open'] and t['fee_open']==t['fee_close']==.001
        orders=t['orders'];assert len(orders)==2 and orders[0]['ft_is_entry'] and not orders[1]['ft_is_entry']
        assert D(orders[0]['amount'])==D(orders[1]['amount'])==D(t['amount'])
        entry=D(orders[0]['amount'])*D(orders[0]['safe_price']);exit_value=D(orders[1]['amount'])*D(orders[1]['safe_price'])
        assert abs(entry-D(500))<D('.001')
        leg=entry+exit_value;profit=D(t['profit_abs']);fee=leg*D('.001')
        gross+=exit_value-entry;fees+=fee;legs+=leg;native+=profit;rounding+=(exit_value-entry-fee)-profit
        row={'number':n,'entry_timestamp':t['open_timestamp'],'exit_timestamp':t['close_timestamp'],'exit_reason':t['exit_reason'],'natural':t['exit_reason']!='force_exit' and t['close_timestamp']<STOP,'entry_notional':str(entry),'exit_notional':str(exit_value),'native_fees':str(fee),'gross_price_profit':str(exit_value-entry),'native_profit':str(profit),'base_profit':str(profit-leg*D('.001')),'sensitivity_profit':str(profit-leg*D('.003'))}
        for scenario,rate in [('native',D('.001')),('base',D('.002')),('sensitivity',D('.004'))]:
            if cash[scenario]*D('.99')<500 or cash[scenario]<entry*(1+rate):violations[scenario].append({'trade':n,'cash_before':str(cash[scenario])})
            cash[scenario]-=entry*(1+rate);cash[scenario]+=exit_value*(1-rate)
        rows.append(row)
    assert abs(rounding)<D('.000001') and abs(native-D(report['profit_total_abs']))<D('.000001')
    base=native-legs*D('.001');sensitivity=native-legs*D('.003')
    assert base<0  # actual sole run already decisively fails; do not read OHLCV for MTM
    groups=exposure_groups(rows,STOP);natural=sum(r['natural'] for r in rows);complete=sum(g['complete'] for g in groups)
    stripped=base-max((g['base'] for g in groups),default=D(0))
    status=json.loads((ROOT/'search-http-latest.json').read_text())['state']
    assert status['status']=='SEARCH_TERMINATED_NO_FINALIST' and status['budget']['consumed_total']==1 and status['budget']['remaining']==0
    result={'schema':'issue92-s-protocol-audit-v1','actual_campaign_id':status['campaign_id'],'native_terminal':status['status'],'protocol_terminal':'SEARCH_TERMINATED_NO_FINALIST','archive_path':str(ARCHIVE),'archive_sha256':ARCHIVE_SHA,'protocol_sha256':hashlib.sha256((ROOT/'protocol.md').read_bytes()).hexdigest(),'synthetic_checks':tests,'gross_price_pnl_usdt':str(gross),'actual_native_fees_usdt':str(fees),'native_net_usdt':str(native),'additional_base_slippage_usdt':str(legs*D('.001')),'base_net_usdt':str(base),'sensitivity_extra_fee_plus_slippage_usdt':str(legs*D('.003')),'sensitivity_fixed_path_net_usdt':str(sensitivity),'sensitivity_is_native_replay':False,'fee_not_double_counted':True,'rounding_reconciliation_error_usdt':str(rounding),'native_max_drawdown_pct':report['max_drawdown_account']*100,'native_profit_factor':report['profit_factor'],'native_roi_exit_count':sum(t['exit_reason']=='roi' for t in trades),'native_average_hold_minutes':status['attempts'][0]['search_metrics']['average_holding_period_minutes'],'native_rejected_signals':report['rejected_signals'],'natural_completed_trades':natural,'total_trades':len(trades),'complete_extended_30d_groups':complete,'required_trades':12,'required_groups':8,'base_net_remove_best_group':str(stripped),'cash_final_by_scenario':{k:str(v) for k,v in cash.items()},'entry_cash_violations':violations,'all_native_stakes_500':True,'daily_cost_mtm_drawdown':None,'daily_mtm_not_computed_reason':'DECISIVE_NEGATIVE_GROSS_NATIVE_BASE_SENSITIVITY_AND_NATIVE_DD_FAILURE; synthetic cash/mark helper verified without real data','gates':{'base_net':'FAIL','sensitivity_net':'FAIL','fixed_path_cash':{k:'FAIL' if v else 'PASS' for k,v in violations.items()},'native_drawdown':'PASS' if report['max_drawdown_account']<=.20 else 'FAIL','daily_cost_mtm_drawdown':'NOT_COMPUTED_EARLY_STOP','profit_factor':'PASS' if report['profit_factor']>=1 else 'FAIL','roi_exits':'PASS' if all(t['exit_reason']!='roi' for t in trades) else 'FAIL','natural_trades':'PASS' if natural>=12 else 'FAIL','complete_groups':'PASS' if complete>=8 else 'FAIL','remove_best_group_net':'PASS' if stripped>0 else 'FAIL'},'groups':[dict(start_utc=datetime.fromtimestamp(g['start']/1000,timezone.utc).isoformat(),end_utc=datetime.fromtimestamp(g['end']/1000,timezone.utc).isoformat(),trades=g['trades'],natural_count=g['natural_count'],complete=g['complete'],base_profit=str(g['base']),sensitivity_profit=str(g['sensitivity'])) for g in groups],'trade_audit':rows,'development':'PRODUCER_QC_ONLY_NOT_RUN','holdout':'SEALED_UNREAD_NOT_ACQUIRED','native_search_calls':1,'extra_native_calls':0,'finalist_imported':False}
    with (ROOT/'search-economic-audit.json').open('x') as f:json.dump(result,f,indent=2)
    print(json.dumps({k:v for k,v in result.items() if k not in ['groups','trade_audit']},indent=2))

if __name__=='__main__':main()
