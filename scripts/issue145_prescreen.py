#!/usr/bin/env python3
"""One externally authorized, offline exposed-data eight-wallet allocation analysis."""
import argparse
from collections import Counter
from contextlib import contextmanager, ExitStack
from datetime import datetime, timezone
from decimal import Decimal as D, getcontext
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import sys
import time

getcontext().prec = 50
REPO = Path(__file__).resolve().parents[1]
ROOT = Path('/Users/shenjianpeng/.codex/runs/freqtrade-lab/issue145-relative-prescreen-v1')
COSTS = {'base': (D('.001'), D('.0006')), 'stress': (D('.002'), D('.0012'))}
CELLS = [f'{family}/{cost}' for family in ['R','E','B','H'] for cost in COSTS]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def utc():
    return datetime.now(timezone.utc).isoformat()


def write(path, data):
    with Path(path).open('x') as stream:
        json.dump(data, stream, indent=2, default=str, allow_nan=False)
        stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
    sync(Path(path).parent)


def sync(path):
    fd = os.open(path, os.O_RDONLY)
    try: os.fsync(fd)
    finally: os.close(fd)


@contextmanager
def deadline(seconds):
    if seconds <= 0: raise TimeoutError('deadline expired')
    def expired(*_): raise TimeoutError('180-second task deadline')
    old = signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try: yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0); signal.signal(signal.SIGALRM, old)


SYMS = ['BTCUSDT', 'ETHUSDT']
START = 447288  # 2021-01-10T00Z
SCORE = 447985  # 2021-02-08T01Z
END = 464592

class DataError(ValueError):
    """Bound source contents cannot support the authorized analysis."""


def load_sources(m):
    bars = {'BTCUSDT':{}, 'ETHUSDT':{}}
    for src in m['sources']:
        if sha(src['path'])!=src['sha256']: raise DataError('source SHA drift')
    for src in m['sources']:
        q=src['request']
        if q.get('interval')!='1h': continue  # metadata and 2020 daily warmup: hash only
        s=q['symbol']; last=None
        for x in json.loads(Path(src['path']).read_bytes()):
            if not isinstance(x,list) or len(x)!=12 or type(x[0]) is not int or type(x[6]) is not int: raise DataError('kline shape')
            t=x[0]//3600000
            if not m['start']<=t<m['end']: continue  # no OHLC decoding outside authorized domain
            if x[0]%3600000 or not m['start']<=t<m['end'] or t in bars[s] or (last is not None and t<=last): raise DataError('time/duplicate/order')
            if not q['startTime']<=x[0]<=q['endTime'] or not x[0]<=x[6]<x[0]+3600000: raise DataError('request/close boundary')
            o,h,l,c=map(D,x[1:5]); volume=D(x[5])
            if not all(v.is_finite() and v>0 for v in [o,h,l,c]) or not volume.is_finite() or volume<0 or not l<=min(o,c)<=max(o,c)<=h: raise DataError('OHLC invalid')
            bars[s][t]=dict(open=o,close=c,full=x[6]==x[0]+3599999);last=t
    for s in bars:
        observed=[dict(kind='MISSING',open_ms=t*3600000) for t in range(m['start'],m['end']) if t not in bars[s]]
        observed += [dict(kind='SHORT',open_ms=t*3600000) for t,r in bars[s].items() if not r['full']]
        expected=[{k:a[k] for k in ['kind','open_ms']} for a in m['anomalies'][s] if m['start']*3600000<=a['open_ms']<m['end']*3600000]
        if sorted(observed,key=lambda a:a['open_ms'])!=sorted(expected,key=lambda a:a['open_ms']): raise DataError('anomaly inventory drift')
    return bars


def once(root, action, seconds=180, identity=None):
    root=Path(root)
    root.mkdir()  # Existing root, including a failed attempt, rejects without retry.
    sync(root.parent)
    write(root/'attempt.json',dict(event='ATTEMPT',at_utc=utc(),identity=identity,invocations=1,cells_limit=8,retries=0))
    started=time.monotonic()
    try:
        with deadline(seconds): result=action(root)
        write(root/'terminal.json',dict(status='SUCCEEDED',elapsed_seconds=time.monotonic()-started,at_utc=utc(),**result))
    except BaseException as exc:
        write(root/'terminal.json',dict(status='FAILED',verdict='BLOCKED_DATA' if isinstance(exc,DataError) else 'ATTEMPT_FAILED_NO_RETRY',error=type(exc).__name__+': '+str(exc),elapsed_seconds=time.monotonic()-started,at_utc=utc()))
        raise



def stamp(hour):
    return datetime.fromtimestamp(hour*3600, timezone.utc).isoformat()


def daily_closes(bars):
    out = {}
    days = sorted({h//24 for h in bars[SYMS[0]]})
    for d in days:
        if all(h in bars[s] and bars[s][h]['full'] for s in SYMS for h in range(d*24,(d+1)*24)):
            out[d] = [bars[s][d*24+23]['close'] for s in SYMS]
    return out


def relative_at(daily, boundary_day):
    # 29 consecutive full UTC closes, last one known at this boundary; no future close.
    ds = list(range(boundary_day-29, boundary_day))
    if any(d not in daily for d in ds): return None
    first,last = daily[ds[0]],daily[ds[-1]]
    return (last[1]*first[0])/(first[1]*last[0])


def allocation(family, relative):
    if family=='E' or (family=='R' and relative==1): return [D('.2'),D('.2')]
    if family=='B' or (family=='R' and relative<1): return [D('.3'),D('.1')]
    return [D('.1'),D('.3')]


class Wallet:
    def __init__(self, name):
        self.name=name; self.family,self.cost=name.split('/'); self.fee,self.slip=COSTS[self.cost]
        self.cash=D(1000); self.q={s:D(0) for s in SYMS}; self.peak=D(1000); self.dd=D(0); self.maxdd=D(0)
        self.half=False; self.halt=False; self.breach=False; self.unknown=[]; self.recover=3
        self.pending={}; self.weekly=None; self.weights=[D('.2'),D('.2')]; self.trades=[]; self.risks=[]; self.weeks=[]; self.marks=[]
        self.cost_loss=D(0); self.fees=D(0); self.slippage=D(0); self.turnover=D(0); self.last_prices=None

    def nav(self, prices): return self.cash+sum((self.q[s]*prices[s] for s in SYMS),D(0))

    def reduce(self, target):
        for s in SYMS: self.pending[s]=min(self.pending.get(s,self.q[s]),self.q[s],target[s])

    def trade(self, hour, side, s, qty, ref, reason):
        if qty<=0: return
        before=self.cash; before_q=self.q[s]
        if side=='SELL':
            qty=min(qty,self.q[s]); price=ref*(1-self.slip); fee=qty*price*self.fee
            self.cash+=qty*price-fee; self.q[s]-=qty; fee_base=D(0); fee_quote=fee
            fee_mark=fee; slip_loss=qty*(ref-price)
        else:
            price=ref*(1+self.slip); spent=qty*price
            if spent>self.cash+D('1e-40'): raise ValueError('cash overspend')
            self.cash-=spent; fee_base=qty*self.fee; fee_quote=D(0); self.q[s]+=qty-fee_base
            fee_mark=fee_base*ref; slip_loss=qty*(price-ref)
        if abs(self.cash)<D('1e-40'): self.cash=D(0)
        if self.cash<0 or self.q[s]<0: raise ValueError('negative wallet')
        self.fees+=fee_mark; self.slippage+=slip_loss; self.cost_loss+=fee_mark+slip_loss; self.turnover+=qty*ref
        self.trades.append(dict(hour=hour,utc=stamp(hour),side=side,symbol=s,quantity=qty,reference=ref,price=price,
            fee_base=fee_base,fee_quote=fee_quote,fee_value_at_reference=fee_mark,slippage_loss=slip_loss,
            cash_before=before,cash_after=self.cash,quantity_before=before_q,quantity_after=self.q[s],reason=reason))

    def execute(self,h,opens,allow_weekly=True):
        had_reduction=bool(self.pending)
        for s in list(self.pending):
            if s in opens:
                self.trade(h,'SELL',s,max(D(0),self.q[s]-self.pending[s]),opens[s],'RISK_REDUCTION')
                del self.pending[s]
        if self.weekly is None: return
        due,target,record=self.weekly
        if h<due: return
        self.weekly=None
        if h!=due or not allow_weekly or len(opens)!=2 or had_reduction or self.recover<3:
            record['execution']='CANCELLED_NO_MAKEUP'; return
        # Targets are frozen at decision close; only the cash affordability scale uses execution prices.
        for s in SYMS: self.trade(h,'SELL',s,max(D(0),self.q[s]-target[s]),opens[s],'WEEKLY')
        desired={s:max(D(0),target[s]-self.q[s]) if not self.halt else D(0) for s in SYMS}
        required=sum((desired[s]*opens[s]*(1+self.slip) for s in SYMS),D(0))
        scale=min(D(1),self.cash/required) if required else D(1)
        for s in SYMS: self.trade(h,'BUY',s,desired[s]*scale,opens[s],'WEEKLY')
        record.update(execution='EXECUTED',cash_scale=scale,actual_quantities=dict(self.q),cash_after=self.cash,
            actual_total_weight=sum((self.q[s]*opens[s] for s in SYMS),D(0))/self.nav(opens))

    def decision(self,h,relative,prices):
        r=dict(decision_hour=h,decision_utc=stamp(h),last_signal_close_known_utc=stamp(h),relative_ratio=relative,execution=None)
        self.weeks.append(r)
        if relative is None or relative<=0 or prices is None or self.recover<3:
            r['execution']='CANCELLED_INVALID_INPUT'; return
        self.weights=allocation(self.family,relative)
        factor=D('.5') if self.half else D(1)
        nav=self.nav(prices); target={s:nav*self.weights[i]*factor/prices[s] for i,s in enumerate(SYMS)}
        if self.halt: target={s:min(self.q[s],target[s]) for s in SYMS}
        r.update(target_weights=self.weights[:],risk_multiplier=factor,decision_nav=nav,decision_prices=dict(prices),target_quantities=dict(target),due_hour=h+1,execution_due_utc=stamp(h+1))
        self.weekly=(h+1,target,r)

    def observe(self,h,prices):
        if prices is None:
            self.recover=0
            self.unknown.append(dict(hour=h,bar_open_utc=stamp(h),close_due_utc=stamp(h+1),held=any(self.q.values()),quantities=dict(self.q)))
            return False
        self.recover=min(3,self.recover+1); self.last_prices=dict(prices)
        nav=self.nav(prices); self.peak=max(self.peak,nav); self.dd=1-nav/self.peak; self.maxdd=max(self.maxdd,self.dd)
        events=[]
        if self.dd>=D('.1') and not self.half:
            self.half=True; events.append('DD10_LATCH')
            self.reduce({s:nav*self.weights[i]*D('.5')/prices[s] for i,s in enumerate(SYMS)})
        if self.dd>=D('.15') and not self.halt: self.halt=True; events.append('DD15_NO_BUY_LATCH')
        if self.dd>=D('.2') and not self.breach: self.breach=True; events.append('OWN_DD20')
        values={s:self.q[s]*prices[s] for s in SYMS}; total=sum(values.values(),D(0))
        if any(v>nav*D('.4') for v in values.values()) or total>nav*D('.8'):
            events.append('NOTIONAL_DRIFT')
            capped={s:min(values[s],nav*D('.4')) for s in SYMS}; summed=sum(capped.values(),D(0))
            scale=min(D(1),nav*D('.8')/summed) if summed else D(1)
            self.reduce({s:capped[s]*scale/prices[s] for s in SYMS})
        if events: self.risks.append(dict(hour=h,bar_open_utc=stamp(h),close_known_utc=stamp(h+1),events=events,nav=nav,dd=self.dd,values=values))
        self.marks.append(dict(hour=h,bar_open_utc=stamp(h),close_known_utc=stamp(h+1),nav=nav,cash=self.cash,quantities=dict(self.q),prices=dict(prices),dd=self.dd,
            exposure=total/nav,asset_weights={s:values[s]/nav for s in SYMS},cost_loss=self.cost_loss))
        return self.breach

    def summary(self):
        last=self.marks[-1] if self.marks else None
        prices=self.last_prices
        nav=self.nav(prices) if prices is not None else None
        exit_cost=sum((self.q[s]*prices[s]*(1-(1-self.slip)*(1-self.fee)) for s in SYMS),D(0)) if prices else None
        periods={}
        # MTM changes on the actual common interval, using last observed valuations across gaps.
        for fmt,label in [('%Y-%m','months'),('%Y','years')]:
            buckets={}; previous=D(1000)
            for m in self.marks:
                key=datetime.fromtimestamp(m['hour']*3600,timezone.utc).strftime(fmt)
                if key not in buckets: buckets[key]=dict(start_nav=previous,end_nav=m['nav'],last_observed_utc=m['close_known_utc'],observations=0)
                buckets[key].update(end_nav=m['nav'],last_observed_utc=m['close_known_utc']); buckets[key]['observations']+=1
                previous=m['nav']
            for b in buckets.values(): b.update(mtm_change=b['end_nav']-b['start_nav'],net_return=b['end_nav']/b['start_nav']-1)
            periods[label]=buckets
        exposures=[m['exposure'] for m in self.marks]
        return dict(mean_observed_asset_weights={s:sum((m['asset_weights'][s] for m in self.marks),D(0))/len(self.marks) if self.marks else None for s in SYMS},max_observed_asset_weights={s:max((m['asset_weights'][s] for m in self.marks),default=None) for s in SYMS},name=self.name,cash=self.cash,quantities=self.q,mark_nav_net=nav,mark_net_usdt=nav-1000 if nav is not None else None,
            last_joint_observed_utc=last['close_known_utc'] if last else None,estimated_exit_cost=exit_cost,
            mark_less_estimated_exit_cost=nav-exit_cost if nav is not None else None,terminal_exit_is_trade=False,
            execution_cost_addback_diagnostic=nav+self.cost_loss-1000 if nav is not None else None,
            cost_addback_is_not_zero_cost_strategy=True,fee_value_at_execution_reference=self.fees,slippage_loss=self.slippage,
            traded_reference_notional=self.turnover,turnover_over_initial=self.turnover/1000,trade_count=len(self.trades),
            max_observed_hourly_close_dd=self.maxdd,continuous_dd='UNKNOWN',held_unknown_hours=sum(u['held'] for u in self.unknown),
            unknown_hours=len(self.unknown),risk_qualification='UNKNOWN' if any(u['held'] for u in self.unknown) else 'CONTINUOUS_DD_UNKNOWN',
            mean_observed_exposure=sum(exposures,D(0))/len(exposures) if exposures else None,max_observed_exposure=max(exposures,default=None),
            mean_observed_cash_fraction=1-sum(exposures,D(0))/len(exposures) if exposures else None,
            half_latched=self.half,no_buy_latched=self.halt,own_dd20=self.breach,
            weekly_decisions=len(self.weeks),weekly_status_counts=dict(Counter(w['execution'] for w in self.weeks)),
            first_decision=self.weeks[0] if self.weeks else None,risks=self.risks,**periods)


def analyze(bars,start=SCORE,end=END):
    daily=daily_closes(bars); initial=relative_at(daily,(start-1)//24)
    if initial is None or initial<=0: raise DataError('initial 29-day window')
    wallets=[Wallet(n) for n in CELLS]; stop=None; settled=None
    for h in range(start-1,end):
        # 00 decision -> 01 open; all close information is timestamped by actual availability.
        prev={s:bars[s][h-1]['close'] for s in SYMS if h-1 in bars[s] and bars[s][h-1]['full']}
        if stop is None and h%24==0 and datetime.fromtimestamp(h*3600,timezone.utc).weekday()==0:
            relative=relative_at(daily,h//24)
            for w in wallets: w.decision(h,relative,prev if len(prev)==2 else None)
        opens={s:bars[s][h]['open'] for s in SYMS if h in bars[s]}
        for w in wallets: w.execute(h,opens,allow_weekly=stop is None)
        prices={s:bars[s][h]['close'] for s in SYMS if h in bars[s] and bars[s][h]['full']}
        if h>=start:
            triggered=[w.observe(h,prices if len(prices)==2 else None) for w in wallets]
            if stop is None and any(triggered):
                stop=h
                for w in wallets:
                    if w.weekly: w.weekly[2]['execution']='CANCELLED_COHORT_STOP'; w.weekly=None
                    w.reduce({s:D(0) for s in SYMS})
            if stop is not None and all(not any(w.q.values()) for w in wallets): settled=h; break
    cells={w.name:w.summary() for w in wallets}; comparisons={}
    for cost in COSTS:
        r=cells['R/'+cost]
        for family in ['E','B','H']:
            c=cells[family+'/'+cost]
            nr=r['mark_net_usdt']; nc=c['mark_net_usdt']; dr=r['max_observed_hourly_close_dd']; dc=c['max_observed_hourly_close_dd']
            comparisons[cost+'/'+family]=dict(net_R_minus_control=nr-nc,observed_dd_R_minus_control=dr-dc,
                joint_support=nr>=0 and nr>=nc and dr<=dc and (nr>nc or dr<dc))
    support=all(c['joint_support'] for c in comparisons.values())
    for w in wallets:
        directions=[1 if z['relative_ratio']>1 else -1 if z['relative_ratio']<1 else 0 for z in w.weeks if z['execution']=='EXECUTED']
        nonzero=[x for x in directions if x]
        cells[w.name].update(executed_week_direction_counts=dict(Counter(directions)),consecutive_nontie_direction_flips=sum(a!=b for a,b in zip(nonzero,nonzero[1:])))
        if w.family=='R' and (not w.trades or not {-1,1}.issubset(set(directions))): support=False
        for e in w.trades:
            if stop is not None and e['hour']>stop: e['reason']='COHORT_ADMIN_EXIT'
    variation=all(cells['R/'+c]['trade_count']>0 and all(k in cells['R/'+c]['executed_week_direction_counts'] for k in [-1,1]) for c in COSTS)
    descriptive='INSUFFICIENT_RANKING_VARIATION' if not variation else 'DESCRIPTIVE_JOINT_SUPPORT_ONLY' if support else 'STOP_NO_JOINT_SUPPORT'
    summary=dict(cells=cells,comparisons=comparisons,initial_relative_ratio=initial,initial_close_dates=['2021-01-10','2021-02-07'],
        score_start=stamp(start),requested_end_exclusive=stamp(end),cohort_trigger_bar_open_utc=stamp(stop) if stop is not None else None,
        cohort_trigger_close_known_utc=stamp(stop+1) if stop is not None else None,
        admin_exit_last_open_utc=max((e['utc'] for w in wallets for e in w.trades if e['reason']=='COHORT_ADMIN_EXIT'),default=None),
        last_processed_bar_open_utc=stamp(h),last_processed_close_due_utc=stamp(h+1),settlement_completed=settled is not None,
        completed_requested_window=stop is None,descriptive_comparison=descriptive,
        verdict='STOP_COHORT_RISK_LIMIT' if stop is not None else 'RISK_UNKNOWN_NO_QUALIFICATION',independent_qualification=False,
        qualification_reason='Continuous DD remains UNKNOWN; observed risk and comparative descriptive support are separate',
        source_grade='EXPOSED_DEVELOPMENT',cells_completed=8,
        notional_rule='40% per asset / 80% total observed breach -> next available open reduce only')
    events={w.name:dict(trades=w.trades,marks=w.marks,unknown=w.unknown,weeks=w.weeks) for w in wallets}
    return summary,events


def check(m):
    if m['root']!=str(ROOT) or m['cells']!=CELLS or m['budget']!={'invocations':1,'cells':8,'seconds':180,'retries':0}: raise ValueError('identity/budget')
    if (m['start'],m['score'],m['end'])!=(START,SCORE,END) or m['costs']!={k:[str(x) for x in v] for k,v in COSTS.items()}: raise ValueError('window/cost')
    for p,h in m['bindings'].items():
        if sha(p)!=h: raise ValueError('control/code binding drift: '+p)
    old=json.loads((REPO/'docs/issue139-v3-first-diagnostics-manifest.json').read_bytes())
    inv=json.loads((REPO/'docs/issue139-source-inventory-v3-terminal.json').read_bytes())
    if m['sources']!=old['sources'] or len(m['sources'])!=39: raise ValueError('source manifest')
    if m['anomalies']!={s:v['anomalies'] for s,v in inv['symbols'].items()}: raise ValueError('anomaly identity')
    if m['incomplete_days_utc']!={s:v['incomplete_days_utc'] for s,v in inv['symbols'].items()}: raise ValueError('incomplete day identity')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('command',choices=['check','execute']);parser.add_argument('--manifest',required=True);parser.add_argument('--sha256',required=True)
    parser.add_argument('--grant');parser.add_argument('--grant-sha256');a=parser.parse_args()
    if sha(a.manifest)!=a.sha256: raise ValueError('manifest SHA')
    m=json.loads(Path(a.manifest).read_bytes());check(m)
    if a.command=='check': print('CONTROL_CHECK_PASS_NO_RAW_READ');return
    if not a.grant or sha(a.grant)!=a.grant_sha256: raise ValueError('grant SHA')
    g=json.loads(Path(a.grant).read_bytes())
    if g!={'authorized':True,'manifest_sha256':a.sha256,'authorization_reference':m['authorization_reference'],'root':m['root'],'budget':m['budget']}: raise ValueError('exact grant')
    with ExitStack() as stack:
        for path in m['lock_paths']:
            stream=stack.enter_context(Path(path).open('r'));fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
        check(m)
        def deny(event,args):
            if event in ('socket.connect','socket.getaddrinfo','socket.bind'): raise ValueError('network forbidden')
        sys.addaudithook(deny)
        def work(root):
            write(root/'analysis-ledger.json',dict(invocations_consumed=1,paths=CELLS,native_calls=0,market_http=0,retries=0))
            try: bars=load_sources(m)
            except TimeoutError: raise
            except (OSError,ValueError,TypeError,KeyError,IndexError) as exc: raise DataError(str(exc)) from exc
            for s in SYMS:
                missing=[datetime.fromtimestamp(d*86400,timezone.utc).strftime('%Y-%m-%d') for d in range(START//24,END//24)
                    if any(t not in bars[s] or not bars[s][t]['full'] for t in range(d*24,(d+1)*24))]
                if missing!=m['incomplete_days_utc'][s]: raise DataError('incomplete calendar drift')
            summary,events=analyze(bars)
            summary.update(source_anomalies=m['anomalies'])
            write(root/'events.json',events);write(root/'summary.json',summary)
            check(m)
            for src in m['sources']:
                if sha(src['path'])!=src['sha256']:raise ValueError('post source drift')
            return dict(manifest_sha256=a.sha256,grant_sha256=a.grant_sha256,summary_sha256=sha(root/'summary.json'),events_sha256=sha(root/'events.json'),source_code_postcheck='PASS',cells_completed=8,verdict=summary['verdict'])
        once(ROOT,work,180,dict(manifest_sha256=a.sha256,grant_sha256=a.grant_sha256))
    print((ROOT/'terminal.json').read_text())


if __name__=='__main__': main()
