"""Frozen read-only native export attribution. Only Search consumer files; no simulation."""
from pathlib import Path
import json, hashlib, zipfile, math
from collections import Counter
import pandas as pd
R=Path(__file__).resolve().parent
D=R/'search/acquisition/data/okx/futures'
START=pd.Timestamp('2024-03-01',tz='UTC'); STOP=pd.Timestamp('2025-03-01',tz='UTC')
DAY=pd.Timedelta(days=1)
def read_series(suffix, expected, begin):
    df=pd.read_feather(D/('SOL_USDT_USDT-'+suffix+'.feather')).set_index('date')
    assert len(df)==expected and df.index.is_unique and df.index.is_monotonic_increasing
    assert df.index.min()==begin and df.index.max()<STOP
    return df
price=read_series('1d-futures',394,START-29*DAY)
mark=read_series('1h-mark',9456,START-29*DAY)
fund=read_series('1h-funding_rate',1095,START)
c=price['close'];v=price['volume'];upper=c.rolling(28).max().shift(1);lower=c.rolling(28).min().shift(1)
eu=c.rolling(14).max().shift(1);el=c.rolling(14).min().shift(1)
guard=(c.rolling(29).min()>0)&(v.rolling(29).min()>0)
sig=pd.DataFrame({'r1_long':guard&(c>upper),'r1_short':guard&(c<lower),'r2_long':guard&(c>upper)&(upper/lower<=1.10),'r2_short':guard&(c<lower)&(upper/lower<=1.10),'exit_long':guard&(c<el),'exit_short':guard&(c>eu)})
scored=price.loc[(price.index>=START)&(price.index<STOP)]
slots=[{'bar_label_utc':t.isoformat(),'available_next_open_utc':(t+DAY).isoformat(),'native_entry_within_S':bool(t+DAY<STOP),**{k:bool(x) for k,x in row.items()}} for t,row in sig.loc[scored.index].iterrows()]
def pf(xs):
    wins=sum(max(x,0) for x in xs); losses=-sum(min(x,0) for x in xs)
    return wins/losses if losses else None
def realized_dd(xs):
    equity=peak=2000.; dd=0.
    for x in xs:
        equity+=x;peak=max(peak,equity);dd=max(dd,(peak-equity)/peak*100)
    return dd
results={};trades_by={}
for n in (1,2):
    name=f'ConsolidationChannelR{n}'
    archives=list((R/f'search/search-results-round-{n}').rglob('*.zip')); assert len(archives)==1
    archive=archives[0]
    with zipfile.ZipFile(archive) as z:
        report=json.loads(z.read(next(x for x in z.namelist() if x.endswith('.json') and 'config' not in x)))['strategy'][name]
        cfg=json.loads(z.read(next(x for x in z.namelist() if x.endswith('_config.json'))))
        assert z.read(next(x for x in z.namelist() if x.endswith('.py')))==(R/(name+'.py')).read_bytes()
    assert cfg['fee']==0.0005 and cfg['stake_amount']==400 and cfg['max_open_trades']==1
    assert report['minimal_roi']=={} and report['stoploss']==-0.08
    out=[]
    for t in report['trades']:
        opened=pd.Timestamp(t['open_date']);closed=pd.Timestamp(t['close_date']);direction=-1 if t['is_short'] else 1
        assert START<=opened<=closed<STOP and t['leverage']==1 and not t['is_open']
        assert t['trade_duration'] is not None and t['trade_duration']>=0
        assert t['fee_open']==t['fee_close']==0.0005 and len(t['orders'])==2
        decision=opened-DAY
        signal_key=f'r{n}_'+('short' if t['is_short'] else 'long')
        assert bool(sig.loc[decision,signal_key])
        assert math.isclose(t['open_rate'],float(price.loc[opened,'open']),rel_tol=1e-10)
        entry=sum(o['amount']*o['safe_price'] for o in t['orders'] if o['ft_is_entry'])
        exit_notional=sum(o['amount']*o['safe_price'] for o in t['orders'] if not o['ft_is_entry'])
        gross=direction*t['amount']*(t['close_rate']-t['open_rate'])
        fees=(entry+exit_notional)*0.0005;extra=(entry+exit_notional)*0.0002
        events=fund.loc[(fund.index>=opened)&(fund.index<=closed),'open']
        funding=-direction*sum(float(rate)*float(mark.loc[ts,'open'])*t['amount'] for ts,rate in events.items())
        assert math.isclose(funding,t['funding_fees'],abs_tol=1e-7)
        assert abs(gross-fees+funding-t['profit_abs'])<1e-6
        out.append({'open_utc':opened.isoformat(),'close_utc':closed.isoformat(),'direction':direction,'amount':t['amount'],'entry_notional':entry,'exit_notional':exit_notional,'duration_minutes':t['trade_duration'],'exit_reason':t['exit_reason'],'price_gross_usdt':gross,'fees_usdt':fees,'signed_funding_usdt':funding,'native_net_usdt':t['profit_abs'],'extra_cost_usdt':extra,'adjusted_net_usdt':t['profit_abs']-extra,'funding_events':len(events)})
    assert all(pd.Timestamp(a['close_utc'])<=pd.Timestamp(b['open_utc']) for a,b in zip(out,out[1:]))
    keys=['price_gross_usdt','fees_usdt','signed_funding_usdt','native_net_usdt','extra_cost_usdt','adjusted_net_usdt','entry_notional','exit_notional']
    totals={k:sum(t[k] for t in out) for k in keys}
    assert abs(totals['native_net_usdt']-report['profit_total_abs'])<1e-6
    native_pf=report.get('profit_factor');native_dd=report.get('max_drawdown_account')
    dd_pct=None if native_dd is None else native_dd*100
    durations=[t['duration_minutes'] for t in out]
    gates={'closed_trades_ge24':len(out)>=24,'native_net_ge25':totals['native_net_usdt']>=25,'extra_net_ge25':totals['adjusted_net_usdt']>=25,'native_pf_ge1_10':native_pf is not None and native_pf>=1.10,'native_dd_le15':dd_pct is not None and dd_pct<=15,'roi_exits_zero':all(t['exit_reason']!='roi' for t in out),'holding_nonnull_ge0':bool(out) and all(x is not None and x>=0 for x in durations)}
    monthly={month:{'closed_trades':sum(t['close_utc'].startswith(month) for t in out),**{k:sum(t[k] for t in out if t['close_utc'].startswith(month)) for k in keys}} for month in pd.period_range('2024-03','2025-02',freq='M').astype(str)}
    quarters=dict(Counter(str(pd.Timestamp(t['close_utc']).tz_localize(None).to_period('Q')) for t in out))
    positives=sum(max(t['native_net_usdt'],0) for t in out)
    maxwin=max(out,key=lambda x:x['native_net_usdt']) if out else None
    signed_average_quantity=sum(t['direction']*t['amount']*t['duration_minutes'] for t in out)/(365*1440)
    p0=float(scored.iloc[0]['open']);p1=float(scored.iloc[-1]['close'])
    def passive(q):
        gross=q*(p1-p0); fee=abs(q)*(p0+p1)*.0005; extra=abs(q)*(p0+p1)*.0002
        funding=-q*sum(float(rate)*float(mark.loc[ts,'open']) for ts,rate in fund['open'].items())
        return {'signed_quantity':q,'price_gross_usdt':gross,'fee_usdt':fee,'signed_funding_usdt':funding,'base_cost_net_usdt':gross-fee+funding,'extra_cost_net_usdt':gross-fee+funding-extra,'basis':'attribution only; first S open to last S close; no actual execution or gate'}
    results[name]={'archive':str(archive.relative_to(R)),'archive_sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'trades':len(out),**totals,'price_gross_per_entry_notional':totals['price_gross_usdt']/totals['entry_notional'] if totals['entry_notional'] else None,'native_profit_factor':native_pf,'native_max_drawdown_pct':dd_pct,'extra_profit_factor':pf([t['adjusted_net_usdt'] for t in out]),'extra_realized_dd_pct':realized_dd([t['adjusted_net_usdt'] for t in out]),'holding_average_minutes':sum(durations)/len(durations) if durations else None,'holding_min_minutes':min(durations) if durations else None,'holding_max_minutes':max(durations) if durations else None,'exit_reasons':dict(Counter(t['exit_reason'] for t in out)),'direction_counts':dict(Counter(t['direction'] for t in out)),'quarter_closed_trade_counts':quarters,'months_by_close':monthly,'maximum_trade':maxwin,'maximum_loss_trade':min(out,key=lambda x:x['native_net_usdt']) if out else None,'max_winner_share_of_positive_profits':maxwin['native_net_usdt']/positives if positives else None,'gates':gates,'self_pass':all(gates.values()),'attribution':{'cash':0,'passive_initial400_long':passive(400/p0),'passive_initial400_short':passive(-400/p0),'equal_average_signed_quantity':passive(signed_average_quantity)}}
    trades_by[name]=out
a=results['ConsolidationChannelR1'];b=results['ConsolidationChannelR2']
better={k:b[k] is not None and a[k] is not None and b[k]>a[k] for k in ['native_net_usdt','adjusted_net_usdt','price_gross_per_entry_notional']}
increment=b['self_pass'] and all(better.values())
terminal=json.loads((R/'search/search-terminal.json').read_text())
document={'scope':'Search only; D/H/Stress not evaluated','native_terminal':terminal,'rounds':results,'strict_increment_comparisons':better,'consolidation_increment_supported':increment,'baseline_self_qualified':a['self_pass'],'supplementary_qualified_names':(['ConsolidationChannelR1'] if a['self_pass'] else [])+(['ConsolidationChannelR2'] if increment else []),'signal_opportunities':slots,'trades':trades_by,'claims':{'real_slippage':'UNKNOWN','independent_effective_sample_size':'UNKNOWN','D':'SEALED_UNREAD_RESEARCHER','H_Stress':'SEALED_UNREAD','extra_pf_no_losses_semantics':'NULL denominator, not invented infinity','actual_trades_subset_assumed':False}}
target=R/'result-audit.json';assert not target.exists()
target.write_text(json.dumps(document,indent=2,allow_nan=False)+'\n')
print(json.dumps({k:{x:v[x] for x in ['trades','native_net_usdt','adjusted_net_usdt','native_profit_factor','native_max_drawdown_pct','holding_average_minutes','self_pass']} for k,v in results.items()},indent=2))
