"""Descriptive event and accounting diagnostics after a frozen native batch."""
from pathlib import Path
import json


def event_diagnostics(frames, events, score_start, train_end, score_end):
    import pandas as pd
    from lab.perp_baseline import features
    rows=[]
    for pair,frame in frames.items():
        f=features(frame).set_index('date');ev=events[pair]
        for at,row in f.iterrows():
            side=1 if row.baseline_long else -1 if row.baseline_short else 0
            entered=at+pd.Timedelta(hours=2);closed=at+pd.Timedelta(hours=26)
            if (not side or pd.isna(row.risk_multiplier) or entered<score_start or
                    closed>=score_end or entered not in f.index or closed not in f.index):
                continue
            op=float(f.loc[entered,'open']);cp=float(f.loc[closed,'open'])
            funding=ev.loc[(ev.date>entered)&(ev.date<=closed)]
            flow=-side*float((funding.open_fund*funding.open_mark).sum())/op
            cost=.0008*(1+cp/op);gross=side*(cp/op-1)
            rows.append(dict(pair=pair,entry=entered,closed=closed,side=side,
                persistence_pass=side*row.persistence>=.25,risk_multiplier=float(row.risk_multiplier),
                gross=gross,cost=cost,funding=flow,net=gross-cost+flow,
                stage='training' if closed<train_end else 'later_development' if entered>=train_end else 'boundary_purged'))
    frame=pd.DataFrame(rows)
    def describe(part):
        return dict(signal_events=len(part),common_72h_entry_clusters=int(part.entry.dt.floor('72h').nunique()),
            mean_net_return=float(part.net.mean()) if len(part) else None,
            mean_gross_return=float(part.gross.mean()) if len(part) else None,
            fifth_percentile_net=float(part.net.quantile(.05)) if len(part) else None,
            mean_cost=float(part.cost.mean()) if len(part) else None)
    return dict(label='OVERLAPPING_24H_EVENTS_NOT_WALLET_RETURNS_NOT_INDEPENDENT_SAMPLES',
        fixed_horizon_hours=24,all=describe(frame),
        persistence_pass=describe(frame.loc[frame.persistence_pass]),
        persistence_fail=describe(frame.loc[~frame.persistence_pass]),
        dynamic_reduced=describe(frame.loc[frame.risk_multiplier<1]),
        no_volatility_reduction=describe(frame.loc[frame.risk_multiplier==1]),
        training=describe(frame.loc[frame.stage=='training']),
        later_development=describe(frame.loc[frame.stage=='later_development']),
        train_boundary_purged=int((frame.stage=='boundary_purged').sum()),
        confidence_interval=None,reason='Overlapping fixed labels and two synchronized assets; descriptive diagnostics only.')


def period_diagnostics(points, train_end):
    import pandas as pd
    df=pd.DataFrame(points);df['at']=pd.to_datetime(df['at'],utc=True);df=df.set_index('at')
    def describe(frame,initial):
        peak=initial;dd=0.
        for value in frame.equity:
            peak=max(peak,value);dd=max(dd,1-value/peak)
        return dict(initial_equity=initial,final_equity=float(frame.equity.iloc[-1]),
            return_fraction=float(frame.equity.iloc[-1])/initial-1,version_period_drawdown=dd)
    training=df.loc[df.index<train_end];later=df.loc[df.index>=train_end]
    return dict(training=describe(training,1000.),later_development=describe(later,float(training.equity.iloc[-1])),
        independently_validated=False,phase_boundary_positions_carried=True,
        note='Same continuous native account; period returns are descriptive, later period was not a fresh unseen holdout. Lifecycle DD is retained separately.')


def simple_benchmark(frames,events,start,end):
    """Fixed 40/40/20 notional reference, arithmetic only, not native strategy."""
    import pandas as pd
    net=0.;gross=0.;cost=0.;funding=0.;by_pair={}
    # Match native first hourly execution and final available open.
    entered=start+pd.Timedelta(hours=1);closed=end-pd.Timedelta(hours=1)
    for pair,frame in frames.items():
        f=frame.set_index('date');op=float(f.loc[entered,'open']);cp=float(f.loc[closed,'open'])
        q=400/op
        ev=events[pair];selected=ev.loc[(ev.date>entered)&(ev.date<=closed)]
        g=q*(cp-op);c=q*(op+cp)*.0008;flow=-q*float((selected.open_fund*selected.open_mark).sum())
        net+=g-c+flow;gross+=g;cost+=c;funding+=flow
        by_pair[pair]=dict(price_return=cp/op-1,net_usdt=g-c+flow)
    return dict(label='ARITHMETIC_LONG_BTC40_ETH40_CASH20_REFERENCE_NOT_NATIVE_OR_PIT_EXECUTABLE',
        net_usdt=net,gross_usdt=gross,transaction_cost_usdt=cost,funding_usdt=funding,
        by_pair=by_pair,minimum_precision_and_historical_margin_checks=False)


def complete_diagnostics(root,source):
    import pandas as pd
    from lab.perp_baseline_runner import load_source,PROTOCOL,write
    root=Path(root);p=json.loads(PROTOCOL.read_text())
    frames,marks,events,metadata,binding=load_source(source)
    start=pd.Timestamp(p['score_start']);end=pd.Timestamp(p['score_end_exclusive']);cut=pd.Timestamp(p['training_end_exclusive'])
    summary=json.loads((root/'summary.json').read_text())
    out=dict(event_layer=event_diagnostics(frames,events,start,cut,end),
        periods={v:period_diagnostics(json.loads((root/v/'equity.json').read_text()),cut) for v in summary['variants']},
        benchmark=simple_benchmark(frames,events,start,end))
    write(root/'diagnostics.json',out)
    return out


def figure(root,output):
    """Static accounting chart; optional plotting runtime never enters backtest."""
    from datetime import datetime
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    root=Path(root)
    colors={'baseline':'#787c8c','persistence':'#2875cd','volatility':'#d27d20','fixed':'#439777'}
    fig,axes=plt.subplots(3,1,figsize=(12,9),sharex=True,gridspec_kw={'height_ratios':[2,1,1]})
    for variant,color in colors.items():
        rows=json.loads((root/variant/'equity.json').read_text())
        # Daily display samples, full hourly MTM is retained in equity.json.
        sampled=rows[::24]+rows[-1:]
        dates=[datetime.fromisoformat(r['at']) for r in sampled]
        axes[0].plot(dates,[r['equity'] for r in sampled],label=variant,color=color,lw=1.5)
        axes[1].plot(dates,[-100*r['drawdown'] for r in sampled],color=color,lw=1.)
        axes[2].plot(dates,[100*r['gross_exposure']/r['equity'] for r in sampled],color=color,lw=.65,alpha=.65)
    axes[0].axhline(1000,color='#202530',lw=.8,ls='--');axes[0].legend(loc='lower left',ncol=4)
    axes[1].axhline(-20,color='#be4050',lw=.8,ls='--')
    axes[0].set_ylabel('Equity (USDT)');axes[1].set_ylabel('Lifecycle DD (%)');axes[2].set_ylabel('Gross exposure (%)')
    for axis in axes:
        axis.grid(alpha=.2);axis.spines[['top','right']].set_visible(False)
    axes[0].set_title('BTC / ETH perpetual: first frozen native comparison\nDevelopment only | 1x | taker + slippage allowance + exact funding')
    fig.text(.08,.025,'Daily chart samples from hourly MTM. Intrahour risk unknown. 20% is a research target, not an automatic rejection.',fontsize=9)
    fig.tight_layout(rect=[0,.05,1,1]);fig.savefig(output,dpi=150);plt.close(fig)
