"""Issue93 single realized path audit; no native invocation or D/H reads."""
import hashlib
import json
import zipfile
from collections import Counter,defaultdict
from decimal import Decimal
from pathlib import Path
import pandas as pd
import pyarrow.feather as feather
from accounting_semantics import ordered_legs,gap_supplement

ROOT=Path(__file__).resolve().parent
D=lambda x:Decimal(str(x))
ZERO=D(0)
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def clean(x):
    if isinstance(x,Decimal):return str(x)
    if isinstance(x,dict):return {str(k):clean(v) for k,v in x.items()}
    if isinstance(x,list):return [clean(v) for v in x]
    return x

def main():
    frozen=json.loads((ROOT/'freeze-receipt.json').read_text())
    terminal=json.loads((ROOT/'search/search-terminal.json').read_text())
    context=json.loads((ROOT/'search-http-latest.json').read_text())
    attempt=context['state']['attempts'][0]
    assert len(context['state']['attempts'])==1 and attempt['technical_status']=='VALID'
    archive=ROOT/'search'/attempt['evidence']['archive']['path']
    assert sha(archive)==attempt['evidence']['archive']['sha256']
    with zipfile.ZipFile(archive) as z:
        rep=json.loads(z.read(archive.stem+'.json'))['strategy']['LtcVolumeLiquidityReboundV1']
        strategy_name=archive.stem+'_LtcVolumeLiquidityReboundV1.py'
        assert z.read(strategy_name)==(ROOT/'LtcVolumeLiquidityReboundV1.py').read_bytes()
        config=json.loads(z.read(archive.stem+'_config.json'))
    assert rep['timerange']=='20210501-20240101' and rep['starting_balance']==1000 and rep['stake_amount']==500
    assert config['trading_mode']=='spot' and config['fee']==.001 and config['max_open_trades']==1
    source=ROOT/'search/acquisition/data/okx/LTC_USDT-1d.feather'
    known=json.loads((ROOT/'source-consumer-qc.json').read_text())['search_slices']['acquisition/data/okx/LTC_USDT-1d.feather']['sha256']
    assert sha(source)==known
    df=feather.read_feather(source).set_index('date')
    assert len(df)==1015 and df.index.max()==pd.Timestamp('2023-12-31',tz='UTC')
    start=pd.Timestamp('2021-05-01',tz='UTC');end=pd.Timestamp('2024-01-01',tz='UTC')
    rr=df.close/df.close.shift(1)-1
    m2=(rr*rr).shift(1).rolling(30).mean()
    vm=df.volume.shift(1).rolling(30).mean()
    liquidity=(df.volume*df.low).shift(1).rolling(30).min()
    def Q(day):
        return bool(rr.loc[day]<=-.02 and rr.loc[day]**2>=2.25*m2.loc[day]
            and df.loc[day,'volume']>=2*vm.loc[day] and m2.loc[day]>0 and vm.loc[day]>0)
    rows=[];legs=[];gross=ZERO;fees=ZERO;native_profit_sum=ZERO;gaps=ZERO
    block_net=defaultdict(lambda:ZERO);block_counts=Counter();natural=0;force=0
    max_volume_fraction=ZERO;cash_minimum_margin={k:None for k in ['native','base','sensitivity']}
    for i,t in enumerate(rep['trades']):
        ot=pd.Timestamp(t['open_date']);ct=pd.Timestamp(t['close_date'])
        assert start<=ot<=ct<end and not t['is_short'] and t['leverage']==1 and not t['is_open']
        assert len(t['orders'])==2
        entry,exit_=t['orders']
        assert entry['ft_is_entry'] is True and entry['ft_order_side']=='buy'
        assert exit_['ft_is_entry'] is False and exit_['ft_order_side']=='sell'
        assert entry['order_filled_timestamp']==t['open_timestamp'] and exit_['order_filled_timestamp']==t['close_timestamp']
        q=D(t['amount']);o=D(entry['safe_price']);p=D(exit_['safe_price'])
        assert q==D(entry['amount'])==D(exit_['amount']) and o==D(t['open_rate']) and p==D(t['close_rate'])
        assert D(t['fee_open'])==D(t['fee_close'])==D('.001')
        assert abs(q*o-D(t['stake_amount']))<D('0.00000001')
        assert 0<=D(500)-q*o<o*D('.000001')+D('0.00000001')
        assert o==D(df.loc[ot,'open'])
        signal_day=ot-pd.Timedelta(days=1)
        assert Q(signal_day) and not any(Q(signal_day-pd.Timedelta(days=k)) for k in (1,2,3))
        assert liquidity.loc[signal_day]>=500000
        if t['exit_reason']=='exit_signal':
            assert ct-ot==pd.Timedelta(days=2) and t['trade_duration']==2880
            assert p==D(df.loc[ct,'open'])
        elif t['exit_reason']=='stop_loss':
            assert 0<=t['trade_duration']<=2880 and D(df.loc[ct,'low'])<=D(t['stop_loss_abs'])
        elif t['exit_reason']=='force_exit':force+=1
        else:raise AssertionError('unexpected exit reason')
        if t['exit_reason']!='force_exit':natural+=1
        native_gap=D(gap_supplement(quantity=float(q),native_exit=float(p),candle_open=float(df.loc[ct,'open']),held_before_candle=ct>ot,stop_exit=t['exit_reason']=='stop_loss'))
        # Fee/slippage are charged on the native leg notional, conservatively
        # retaining that fee basis if a separate worse-open supplement is needed.
        trade_gross=q*(p-o);trade_fees=q*(o+p)*D('.001')
        trade_native=trade_gross-trade_fees
        assert abs(trade_native-D(t['profit_abs']))<D('0.00000002')
        trade_base=trade_native-trade_fees-native_gap
        trade_sensitive=trade_gross-q*(o+p)*D('.004')-native_gap
        block=(ot-start).days//30
        complete=start+pd.Timedelta(days=30*(block+1))<=end
        block_net[block]+=trade_base;block_counts[block]+=1
        native_profit_sum+=D(t['profit_abs']);gross+=trade_gross;fees+=trade_fees;gaps+=native_gap
        identity=f'{sha(archive)}:/strategy/LtcVolumeLiquidityReboundV1/trades/{i}'
        # Native export omits trade_id/order_id. Use immutable artifact addresses,
        # never fabricate exchange IDs; preserve original list index and flags.
        for j,order in enumerate(t['orders']):
            day=pd.Timestamp(order['order_filled_timestamp'],unit='ms',tz='UTC')
            fraction=q/D(df.loc[day,'volume']);max_volume_fraction=max(max_volume_fraction,fraction)
            legs.append({'time':order['order_filled_timestamp'],'trade_open_time':t['open_timestamp'],
                'trade_id':identity,'order_id':identity+f'/orders/{j}',
                'side':order['ft_order_side'],'q':q,'rate':D(order['safe_price']),
                'gap_debit':native_gap if j==1 else ZERO,'volume_fraction':fraction})
        rows.append({'artifact_trade_index':i,'native_trade_id':t.get('trade_id'),'artifact_identity':identity,
            'open_utc':ot.isoformat(),'close_utc':ct.isoformat(),'duration_minutes':t['trade_duration'],
            'exit_reason':t['exit_reason'],'quantity':q,'open_rate':o,'exit_rate':p,
            'gross':trade_gross,'native_fees':trade_fees,'native_net_exact':trade_native,
            'native_report_profit_abs':D(t['profit_abs']),'extra_base_slippage':trade_fees,
            'unreflected_gap_supplement':native_gap,'base_net':trade_base,'sensitivity_net':trade_sensitive,
            'entry_block':block,'complete_block':complete,'same_bar_entry_exit':ot==ct})
    cash={k:D(1000) for k in cash_minimum_margin};quantity=ZERO;cash_feasible={k:True for k in cash}
    order_events=[]
    for e in ordered_legs(legs):
        quote=e['q']*e['rate']
        if e['side']=='buy':
            assert quantity==0
            for k,friction in [('native',D('.001')),('base',D('.002')),('sensitivity',D('.004'))]:
                margin=cash[k]-D(500)*(1+friction)
                cash_minimum_margin[k]=margin if cash_minimum_margin[k] is None else min(cash_minimum_margin[k],margin)
                if margin<0:cash_feasible[k]=False
                cash[k]-=quote*(1+friction)
            quantity+=e['q']
        else:
            assert quantity==e['q']
            for k,friction in [('native',D('.001')),('base',D('.002')),('sensitivity',D('.004'))]:
                cash[k]+=quote*(1-friction)-(ZERO if k=='native' else e['gap_debit'])
            quantity-=e['q']
        order_events.append({'time':e['time'],'artifact_order_identity':e['order_id'],'side':e['side'],
            'cash':dict(cash),'quantity_after':quantity,'volume_fraction':e['volume_fraction']})
    assert quantity==0 and abs(cash['native']-D(rep['final_balance']))<D('0.0000002')
    native_net=gross-fees;base_net=gross-2*fees-gaps;sensitivity_net=gross-4*fees-gaps
    assert cash['base']-1000==base_net and cash['sensitivity']-1000==sensitivity_net
    assert abs(native_net-D(rep['profit_total_abs']))<D('0.0000002')
    complete_blocks={b:p for b,p in block_net.items() if start+pd.Timedelta(days=30*(b+1))<=end}
    best=max(complete_blocks.values());positive=sum(p>0 for p in complete_blocks.values())
    force_net=sum((x['base_net'] for x in rows if x['exit_reason']=='force_exit'),ZERO)
    gate={'native_positive':native_net>0,'native_PF_at_least_1_10':rep['profit_factor']>=1.1,
        'native_DD_at_most_20pct':rep['max_drawdown_account']<=.20,
        'base_net_positive':base_net>0,'sensitivity_net_positive':sensitivity_net>0,
        'all_cash_paths_executable':all(cash_feasible.values()),'each_leg_at_most_0_1pct_daily_volume':max_volume_fraction<=D('.001'),
        'natural_trades_at_least_12':natural>=12,'complete_active_30day_blocks_at_least_8':len(complete_blocks)>=8,
        'positive_complete_blocks_strict_majority':positive*2>len(complete_blocks),
        'net_after_removing_best_complete_block_positive':base_net-best>0,
        'net_after_removing_force_exit_positive':base_net-force_net>0,
        'daily_cost_MTM_DD_at_most_20pct':None}
    assert not gate['native_PF_at_least_1_10'] and not gate['base_net_positive']
    result={'status':'SEARCH_TERMINATED_NO_FINALIST','technical_status':'VALID','issue':93,
        'actual_campaign_id':context['state']['campaign_id'],'planned_campaign_id':frozen['planned_campaign_id'],
        'archive_path':str(archive),'archive_sha256':sha(archive),'strategy_sha256':sha(ROOT/'LtcVolumeLiquidityReboundV1.py'),
        'protocol_sha256':sha(ROOT/'protocol.md'),'S_feather_sha256':sha(source),
        'source_provenance_sha256':sha(ROOT/'source/retained-data-provenance.json'),
        'native_runs':1,'attempts_used':1,'remaining_attempts':0,'total_trades':len(rows),
        'gross_usdt':gross,'native_fees_usdt':fees,'native_net_usdt':native_net,
        'native_report_profit_abs_sum':native_profit_sum,'native_rounding_delta_usdt':native_net-D(rep['profit_total_abs']),
        'extra_base_slippage_usdt':fees,'unreflected_gap_supplement_usdt':gaps,
        'base_net_usdt':base_net,'sensitivity_fixed_path_net_usdt':sensitivity_net,
        'native_PF':rep['profit_factor'],'native_DD_pct':rep['max_drawdown_account']*100,
        'native_vs_base_vs_sensitivity_cash':cash,'cash_feasible':cash_feasible,'minimum_full_500_stake_cash_margin':cash_minimum_margin,
        'max_leg_fraction_of_day_volume':max_volume_fraction,'natural_trades':natural,'force_exits':force,
        'same_bar_stops':sum(x['same_bar_entry_exit'] and x['exit_reason']=='stop_loss' for x in rows),
        'exit_reasons':dict(Counter(t['exit_reason'] for t in rep['trades'])),
        'complete_active_blocks':len(complete_blocks),'positive_complete_blocks':positive,
        'block_base_net':dict(block_net),'block_trade_counts':dict(block_counts),
        'net_without_best_complete_block':base_net-best,'net_without_force_exit':base_net-force_net,
        'gates':gate,'daily_cost_MTM_drawdown_pct':None,
        'daily_cost_MTM_not_computed_reason':'Preauthorized decisive native PF and base/sensitivity economic failures; no further expensive audit.',
        'CI':None,'CI_reason':'D/H-only; both unopened',
        'volume_increment_identified':False,'execution_depth_at_open':'UNKNOWN; daily volume check is only coarse feasibility',
        'native_trade_and_order_ids':'NOT_EXPORTED; immutable archive JSON positional identities used',
        'trades':rows,'ordered_cash_events':order_events,
        'D':'PRODUCER_QC_ONLY_NOT_RUN','H':'SEALED_UNREAD_NOT_ACQUIRED','Stress':'SEALED_UNREAD_NOT_RUN',
        'research_run_created':False,'global_terminal_consumption_appended':False,'issue_closed':False}
    with (ROOT/'search-economic-audit.json').open('x') as f:json.dump(clean(result),f,indent=2)
    print(json.dumps(clean({k:result[k] for k in ['status','actual_campaign_id','gross_usdt','native_fees_usdt','native_net_usdt','base_net_usdt','sensitivity_fixed_path_net_usdt','unreflected_gap_supplement_usdt','native_PF','native_DD_pct','natural_trades','force_exits','same_bar_stops','exit_reasons','complete_active_blocks','positive_complete_blocks','net_without_best_complete_block','max_leg_fraction_of_day_volume','cash_feasible','gates']})))

if __name__=='__main__':main()
