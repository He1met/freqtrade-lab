#!/usr/bin/env python3
"""Render retained native-fill equity audits; optional reporting dependency only."""
import argparse
from datetime import datetime
import json
from pathlib import Path


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--experiment-root',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib.dates as dates
    colors={'baseline':'#64748b','persistence':'#2563eb','volatility':'#a855f7','fixed':'#d97706'}
    labels={'baseline':'Baseline','persistence':'+ Direction persistence','volatility':'+ Volatility reduction','fixed':'Fixed reduction'}
    fig,axes=plt.subplots(2,1,figsize=(11,7),sharex=True,gridspec_kw={'height_ratios':[2,1]})
    for variant,color in colors.items():
        rows=json.loads((args.experiment_root/variant/'equity.json').read_text())
        times=[datetime.fromisoformat(r['at']) for r in rows]
        axes[0].plot(times,[r['equity'] for r in rows],label=labels[variant],color=color,lw=1.3)
        axes[1].plot(times,[-100*r['drawdown'] for r in rows],color=color,lw=1.1)
    axes[0].axhline(1000,color='#334155',ls=':',lw=1)
    axes[0].set_ylabel('Shared wallet equity (USDT)')
    axes[1].set_ylabel('Drawdown (%)')
    axes[0].legend(loc='lower left',fontsize=9,ncol=2)
    for ax in axes:
        ax.grid(alpha=.18); ax.spines[['top','right']].set_visible(False)
    axes[1].xaxis.set_major_locator(dates.MonthLocator(interval=3))
    axes[1].xaxis.set_major_formatter(dates.DateFormatter('%Y-%m'))
    fig.suptitle('BTC / ETH USDT perpetual | 1x | Development only',fontsize=15,x=.10,ha='left')
    fig.text(.10,.91,'Native fills + hourly mark-to-market; taker, slippage allowance and actual funding included.',fontsize=9,color='#475569')
    fig.text(.10,.02,'2025-01-08 to 2026-07-01 UTC. Historical exposure; no independent confirmation. Intrahour risk unknown.',fontsize=8,color='#475569')
    fig.subplots_adjust(left=.10,right=.98,top=.86,bottom=.09,hspace=.10)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    fig.savefig(args.output,dpi=160,facecolor='white');plt.close(fig)
    print(args.output)


if __name__=='__main__':main()
