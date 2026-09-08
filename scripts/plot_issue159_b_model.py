#!/usr/bin/env python3
"""Render existing, hash-bound B V3 model logs; no strategy or native execution."""
import argparse
from datetime import datetime, timezone
from decimal import Decimal as D
import hashlib
import json
from pathlib import Path
import sys

REPO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO))
from scripts.analyze_spot139_attribution import summarize
MANIFEST=REPO/'docs/issue139-attribution-v1-manifest.json'
MANIFEST_SHA='c4b155afcb34b9eaf471b28838afede94e88405e8c943c3fec01a0f465a948e3'
OUT=Path('/Users/shenjianpeng/.codex/runs/freqtrade-lab/issue159-model-charts-v1')
COLORS={'base':'#176B87','stress':'#D97732'}
LABELS={'base':'基础成本','stress':'压力成本'}


def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def utc(h):return datetime.fromtimestamp(h*3600,timezone.utc)


def load():
    if sha(MANIFEST)!=MANIFEST_SHA:raise ValueError('frozen attribution manifest drift')
    m=json.loads(MANIFEST.read_text());data={};receipt={}
    for c in COLORS:
        src=m['logs'][c];result=m['results'][c]
        for s in (src,result):
            if sha(s['path'])!=s['sha256']:raise ValueError('SHA drift: '+s['path'])
        rows=[json.loads(x) for x in Path(src['path']).read_text().splitlines()]
        if len(rows)!=17520 or any(r['hour']!=447072+i for i,r in enumerate(rows)):
            raise ValueError('not the complete fixed 2021-2022 log')
        old=json.loads(Path(result['path']).read_text());summary=summarize(rows)
        if summary['terminal_nav']!=D(old['modeled_terminal']['equity']):raise ValueError('terminal mismatch')
        if sum((p['change'] for p in summary['months'].values()),D(0))!=summary['net']:raise ValueError('monthly MTM does not telescope')
        equity=[D(r['equity']) for r in rows];peak=D(1000);dd=[]
        for r,e in zip(rows,equity):
            marked=D(r['cash'])+sum((D(p['inventory'])*D(p['mark']) for p in r['positions'].values()),D(0))
            if abs(marked-e)>D('1e-20'):raise ValueError('cash and inventory NAV mismatch')
            peak=max(peak,e);loss=(peak-e)/peak;dd.append(loss)
            if abs(loss-D(r['observed_drawdown']))>D('1e-20'):raise ValueError('drawdown log mismatch')
        high=max(range(len(rows)),key=lambda i:equity[i]);low=max(range(len(rows)),key=lambda i:dd[i])
        stale=[i for i,r in enumerate(rows) if any(p['mark_age_hours']>0 for p in r['positions'].values())]
        exposure=[sum(float(p['inventory'])*float(p['mark']) for p in r['positions'].values())/float(r['equity'])*100 for r in rows]
        data[c]=dict(time=[utc(r['hour']) for r in rows],nav=list(map(float,equity)),dd=[-float(d)*100 for d in dd],exposure=exposure,
                     stale=stale,high=high,low=low,summary=summary)
        receipt[c]=dict(log=src,result=result,observations=len(rows),terminal_nav=summary['terminal_nav'],net=summary['net'],
            peak_nav=equity[high],peak_utc=utc(rows[high]['hour']).isoformat(),observed_max_dd=dd[low],dd_utc=utc(rows[low]['hour']).isoformat(),
            stale_hours=len(stale),real_drawdown='UNKNOWN',monthly_mtm=summary['months'],average_exposure=summary['average_notional_to_nav'],
            terminal_boundary_carry_hours=summary['terminal_boundary_carried_hours'])
        for s in (src,result):
            if sha(s['path'])!=s['sha256']:raise ValueError('post-read SHA drift')
    return data,receipt


def png(data,path):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib.dates as dates
    from matplotlib.font_manager import FontProperties
    font=FontProperties(fname='/System/Library/Fonts/STHeiti Medium.ttc')
    plt.rcParams.update({'font.family':font.get_name(),'axes.unicode_minus':False,'font.size':11,'axes.spines.top':False,'axes.spines.right':False})
    # Explicit font registration makes Chinese labels portable within this macOS run.
    from matplotlib import font_manager
    font_manager.fontManager.addfont('/System/Library/Fonts/STHeiti Medium.ttc')
    fig,axs=plt.subplots(4,1,figsize=(15,12),gridspec_kw={'height_ratios':[2.3,1.2,1.5,1.1]})
    fig.patch.set_facecolor('#F5F7FA')
    fig.subplots_adjust(top=.83,bottom=.16,left=.08,right=.94,hspace=.55)
    fig.text(.08,.955,'B V3｜资金如何变化',fontsize=25,fontweight='bold',color='#14283D')
    fig.text(.08,.917,'已有模型小时日志 · 初始 1,000 USDT · 2021—2022 已暴露开发样本',fontsize=13,color='#526275')
    fig.text(.08,.880,'期末 1,049.60 / 1,047.59 USDT    |    收益 +4.96% / +4.76%    |    最大观察回撤 3.86% / 3.86%',fontsize=13,color='#14283D')
    for ax in axs:
        ax.set_facecolor('white');ax.grid(axis='y',alpha=.18);ax.set_axisbelow(True)
    for c,d in data.items():
        line='-' if c=='base' else '--';col=COLORS[c]
        axs[0].plot(d['time'],d['nav'],line,color=col,lw=1.25,label=LABELS[c],alpha=.95)
        axs[1].plot(d['time'],d['dd'],line,color=col,lw=1.0)
        axs[3].plot(d['time'],d['exposure'],line,color=col,lw=.9,alpha=.8)
    b=data['base'];s=data['stress'];h=b['high'];l=b['low']
    axs[0].axhline(1000,color='#64748B',ls=':',lw=1)
    axs[0].scatter([b['time'][i] for i in b['stale']],[b['nav'][i] for i in b['stale']],s=23,marker='x',color='#A77900',label='STALE 估值标记',zorder=5)
    axs[0].annotate('基础峰值 1,080.78\n2021-10-21 10:00 UTC',xy=(b['time'][h],b['nav'][h]),xytext=(35,-50),textcoords='offset points',arrowprops=dict(arrowstyle='-',color='#64748B'),fontsize=10,bbox=dict(facecolor='white',edgecolor='none',alpha=.85))
    axs[0].annotate('期末 基础 1,049.60\n        压力 1,047.59',xy=(b['time'][-1],b['nav'][-1]),xytext=(-170,-30),textcoords='offset points',arrowprops=dict(arrowstyle='-',color='#64748B'),fontsize=10,bbox=dict(facecolor='white',edgecolor='none',alpha=.85))
    axs[1].annotate('最大观察回撤 3.8603%\n2021-02-28 16:00 UTC',xy=(b['time'][l],b['dd'][l]),xytext=(35,12),textcoords='offset points',arrowprops=dict(arrowstyle='-',color='#64748B'),fontsize=10,bbox=dict(facecolor='white',edgecolor='none',alpha=.85))
    axs[0].set_title('模型净值｜含残余库存，未假设终点强制清仓',loc='left',fontsize=13,pad=10);axs[0].set_ylabel('USDT');axs[0].legend(loc='upper right',ncol=3,fontsize=10)
    axs[1].set_title('小时观察回撤｜相对截至当时的模型净值峰值',loc='left',fontsize=13,pad=10);axs[1].set_ylabel('%');axs[1].set_ylim(-4.8,.3)
    months=list(b['summary']['months']);x=list(range(len(months)))
    for c,d in data.items():
        shift=-.19 if c=='base' else .19
        axs[2].bar([i+shift for i in x],[float(d['summary']['months'][m]['change']) for m in months],width=.37,color=COLORS[c],label=LABELS[c])
    axs[2].axhline(0,color='#64748B',lw=.8);axs[2].set_xticks(x);axs[2].set_xticklabels([m[2:] for m in months],rotation=45,ha='right',fontsize=9)
    axs[2].set_title('月度盯市净变化｜不是按卖出月份归属的利润',loc='left',fontsize=13,pad=10);axs[2].set_ylabel('USDT')
    axs[3].set_title('总名义敞口 / 净值｜平均仅约 2.19%，不是满仓策略',loc='left',fontsize=13,pad=10);axs[3].set_ylabel('%')
    for ax in [axs[0],axs[1],axs[3]]:
        ax.xaxis.set_major_locator(dates.MonthLocator(bymonth=[1,4,7,10]));ax.xaxis.set_major_formatter(dates.DateFormatter('%Y-%m',tz=timezone.utc));ax.tick_params(axis='x',labelsize=9);ax.set_xlim(b['time'][0],b['time'][-1])
    fig.text(.08,.025,'注意：每成本有 13 个 STALE 小时；沿用原日志的滞后估值，真实最大回撤仍 UNKNOWN。\n月末采用下月 00:00 动作前估值；最终边界沿用 2022-12-31 23:00，滞后 1 小时。\n图为原模型 MTM，非 FreqUI 两笔聚合 Trade 的累计曲线；不是独立验证，也没有新增风险/交易资格。',fontsize=10,color='#526275',linespacing=1.5)
    fig.savefig(path,dpi=160,facecolor=fig.get_facecolor());plt.close(fig)


def html(data,path):
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    fig=make_subplots(rows=4,cols=1,subplot_titles=['模型小时净值（初始 1000 USDT）','小时观察回撤（真实最大回撤 UNKNOWN）','月度 MTM 净变化（USDT）','总名义敞口 / 净值（%）'],vertical_spacing=.075,row_heights=[.38,.2,.23,.19])
    for c,d in data.items():
        name=LABELS[c];line=dict(color=COLORS[c],width=1.5,dash='solid' if c=='base' else 'dash')
        for row,key,unit in [(1,'nav',' USDT'),(2,'dd','%'),(4,'exposure','%')]:
            fig.add_trace(go.Scatter(x=d['time'],y=d[key],name=name,legendgroup=c,showlegend=row==1,line=line,mode='lines',hovertemplate='%{x|%Y-%m-%d %H:%M} UTC<br>'+name+' %{y:.5f}'+unit+'<extra></extra>'),row=row,col=1)
        months=list(d['summary']['months'])
        fig.add_trace(go.Bar(x=months,y=[float(d['summary']['months'][m]['change']) for m in months],name=name,legendgroup=c,showlegend=False,marker_color=COLORS[c],hovertemplate='%{x}<br>'+name+' %{y:.6f} USDT<extra></extra>'),row=3,col=1)
        fig.add_trace(go.Scatter(x=[d['time'][i] for i in d['stale']],y=[d['nav'][i] for i in d['stale']],name=name+' STALE',showlegend=False,mode='markers',marker=dict(color='#A77900',symbol='x',size=7),hovertemplate='%{x|%Y-%m-%d %H:%M} UTC<br>STALE：沿用旧估值，非新报价<extra></extra>'),row=1,col=1)
        i=d['high'];fig.add_annotation(x=d['time'][i],y=d['nav'][i],text=name+'峰值 '+str(round(d['nav'][i],3)),showarrow=True,ay=-45 if c=='base' else 45,row=1,col=1)
    fig.update_layout(height=1250,title='B V3｜原模型小时净值 · 2021—2022 开发诊断',template='plotly_white',font=dict(family='PingFang SC, Heiti SC, sans-serif'),hovermode='x unified',barmode='group',margin=dict(t=110,b=60),legend=dict(orientation='h',y=1.06),dragmode='zoom')
    fig.update_yaxes(title_text='USDT',row=1,col=1);fig.update_yaxes(title_text='%',row=2,col=1);fig.update_yaxes(title_text='USDT',row=3,col=1);fig.update_yaxes(title_text='%',row=4,col=1)
    chart=fig.to_html(full_html=False,include_plotlyjs=True,config=dict(displaylogo=False,responsive=True,scrollZoom=True))
    note='每成本17520小时、13个STALE小时；图保留滞后估值，不补原市场缺口。净值峰值/观察回撤按原日志核对。月MTM用下一月00UTC动作前净值，最后边界沿用末23UTC（1小时）。这些是已暴露开发数据；没有独立确认，真实最大回撤UNKNOWN。不是FreqUI聚合Trade-close曲线。'
    path.write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>B V3 模型图表</title><style>body{margin:24px;font-family:system-ui;background:#f5f7fa;color:#14283d}p{max-width:1100px;line-height:1.65}</style><h1>B V3：看资金路径，而非两笔聚合交易</h1><p>期末：基础 1049.597961 / 压力 1047.586038 USDT。滚轮或框选缩放，双击复位；点击图例显示/隐藏成本场景。所有交互数据与绘图库已内嵌，无网络或服务依赖。</p><p>'+note+'</p>'+chart+'</html>')


def main():
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,default=OUT);a=p.parse_args()
    a.out.mkdir(parents=True,exist_ok=True);data,receipt=load()
    png(data,a.out/'b-v3-model-overview.png');html(data,a.out/'b-v3-model-interactive.html')
    receipt=dict(classification='EXISTING_MODEL_LOG_VISUALIZATION_ONLY',costs=receipt,script_sha256=sha(__file__),source_manifest_sha256=sha(MANIFEST),model_runs=0,native_runs=0,market_gets=0,
                 outputs={n:sha(a.out/n) for n in ['b-v3-model-overview.png','b-v3-model-interactive.html']})
    (a.out/'receipt.json').write_text(json.dumps(receipt,indent=2,default=str)+'\n')
    print(a.out)

if __name__=='__main__':main()
