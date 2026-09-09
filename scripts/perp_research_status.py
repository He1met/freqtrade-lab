#!/usr/bin/env python3
"""Read-only lane status. Never claims work, collects data, or exports market values."""
import argparse
import copy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from lab import perp_dispatch as d, perp_schedule as s

UTC=timezone.utc


def queued_reason(root,state,task,budget,dispatch,now):
    if any(t['status'] in {'RUNNING','UNKNOWN_INTERRUPTED'} for t in state['tasks']):
        return dict(reason='WAIT_WRITER',explanation='已有计算占用或未知中断，先核清唯一 writer。')
    if task['status']=='WAITING_DATA':
        return dict(reason='WAIT_DEVELOPMENT_INPUTS',explanation='短期任务自身仍等待实际开发输入。')
    try:
        d.check_task(copy.deepcopy(task),state,budget,dispatch,root)
        for pending in d.lanes(state['tasks']):
            if pending['kind']=='confirmation':
                execution=s.validate_execution_class(pending,budget)
                if now+timedelta(seconds=task['max_seconds']+300)>=s.utc(execution['contract_ready_at']):
                    return dict(reason='WAIT_CONFIRMATION_PRIORITY',explanation='固定确认已到期或将在本轮预算时段内到期，优先处理确认。')
        if task.get('budget_not_before') and now<s.utc(task['budget_not_before']):
            return dict(reason='WAIT_BUDGET_TIME',not_before=task['budget_not_before'])
        started=[t for t in state['tasks'] if t.get('started_at') and t['kind']=='research']
        for period,fmt in [('daily','%Y-%m-%d'),('weekly','%G-W%V')]:
            used=sum(t['variants'] for t in started if s.utc(t['started_at']).strftime(fmt)==now.strftime(fmt))
            if used+task['variants']>budget[period+'_variants']:
                return dict(reason='WAIT_'+period.upper()+'_VARIANT_BUDGET',used=used,limit=budget[period+'_variants'])
        ended=[t for t in started if t['status'] in s.TERMINAL]
        if ended and len(ended)%budget['research_review_every_rounds']==0:
            previous=ended[-1];review=task.get('review_checkpoint',{})
            if (review.get('previous_task_id')!=previous['id'] or review.get('previous_summary_sha256')!=previous.get('summary_sha256') or
                    review.get('previous_wall_seconds')!=previous.get('claimed_to_report_seconds') or
                    not review.get('information_value') or not review.get('stop_condition')):
                return dict(reason='WAIT_SUCCESSOR_REVIEW',previous_task_id=previous['id'],explanation='需要前轮证据、资源和唯一后继信息价值检查点。')
    except (ValueError,KeyError,TypeError,OSError) as exc:
        return dict(reason='BLOCKED_INPUT_OR_CODE_INTEGRITY',error=str(exc))
    delay=timedelta(minutes=budget['market_available_delay_minutes'])
    closed=(now-delay).replace(minute=0,second=0,microsecond=0)
    next_maintenance=closed+timedelta(hours=1)+delay
    try:
        proof=d.maintenance(root,budget,task,now,state)
        return dict(reason='READY_FOR_CLAIM',explanation='只读条件检查通过；尚未 claim 或执行。',maintenance=proof)
    except (ValueError,KeyError,TypeError,OSError) as exc:
        reason='WAIT_MAINTENANCE' if 'maintenance deadline' in str(exc) else 'WAIT_REQUIRED_CAPTURE_OR_INTENT'
        return dict(reason=reason,error=str(exc),next_maintenance_at=s.stamp(next_maintenance),
                    earliest_recheck_at=s.stamp(next_maintenance if reason=='WAIT_MAINTENANCE' else now),
                    max_seconds=task['max_seconds'],buffer_seconds=300)


def observer_status(root,dispatch,now):
    path=Path(root).parent/'forward-signals/state.json'
    try:
        from lab.perp_forward_signal import control
        protocol_path=s.REPO/dispatch['confirmation_protocol_path']
        protocol=json.loads(protocol_path.read_bytes());registration_path=s.REPO/protocol['candidate_registration_path']
        _,_,_,identity=control(registration_path,protocol_path,path.parent/'observer-binding.json')
        raw=path.read_bytes();observer=json.loads(raw)
        if observer['identity']!=identity: raise ValueError('observer candidate identity drift')
        active=observer.get('active') is True
        if active and s.utc(observer['activated_at'])>=s.utc(protocol['window']['start_inclusive']):
            raise ValueError('activation was not before fixed window')
        phase=('PRE_CONFIRMATION' if now<s.utc(protocol['window']['start_inclusive']) else
               'FIXED_WINDOW_ENDED' if now>=s.utc(protocol['window']['end_exclusive']) else 'CONFIRMATION_WINDOW')
        health=dict(status='NO_HOUR_RECEIPT')
        if observer.get('records'):
            key=max(observer['records']);record=observer['records'][key]
            receipt=json.loads(s.bound_file(path.parent/'hours'/(key+'.receipt.json'),record['receipt_sha256']).read_bytes())
            intent=json.loads(s.bound_file(path.parent/'hours'/(key+'.intent.json'),record['intent_sha256']).read_bytes())
            if receipt['identity']!=identity or intent['identity']!=identity or receipt['intent_sha256']!=record['intent_sha256']:
                raise ValueError('latest observer hour binding drift')
            published=s.utc(receipt['published_observed_at']);entry=s.utc(intent['planned_entry'])
            if published>now: raise ValueError('observer receipt is ahead of actual clock')
            timely=sum(v.get('status') in {'TIMELY_SIGNAL','TIMELY_NO_TRADE'} for v in receipt.get('pairs',{}).values())
            health=dict(status='TIMELY_COMPLETE' if published<entry and timely==2 and set(receipt['pairs'])==d.PAIRS else 'LATE_OR_MISSING',
                latest_slot=key,published_observed_at=s.stamp(published),planned_entry=s.stamp(entry),
                timely_pair_count=timely,receipt_sha256=record['receipt_sha256'],intent_sha256=record['intent_sha256'])
        return dict(status='ACTIVATED' if active else 'NOT_ACTIVATED',phase=phase,
            activated_at=observer.get('activated_at'),window=dispatch['confirmation_window'],
            identity=identity,last_observed_at=observer.get('last_observed_at'),
            native_acceptance_receipt_sha256=observer.get('native_acceptance_receipt_sha256'),
            state_sha256=s.digest(raw),latest_hour_health=health,economic_values_exposed=False)
    except (ValueError,KeyError,TypeError,OSError) as exc:
        return dict(status='UNKNOWN_OR_INTEGRITY_BLOCKED',error=str(exc),economic_values_exposed=False)


def build(root,budget_policy,dispatch_policy,next_review_path=None,now=None):
    now=(now or datetime.now(UTC)).astimezone(UTC)
    result=d.status(root,budget_policy,dispatch_policy);state=result['state']
    dispatch,_=d.load(dispatch_policy,budget_policy);budget,_=s.load_policy(budget_policy)
    active=[t for t in state['tasks'] if t['status'] in {'RUNNING','UNKNOWN_INTERRUPTED'}]
    compute=dict(status='IDLE',task_id=None)
    if active:
        compute=dict(status=active[0]['status'] if len(active)==1 else 'INTEGRITY_BLOCKED_MULTIPLE_WRITERS',
            task_id=active[0]['id'],kind=active[0]['kind'],started_at=active[0].get('started_at'),
            max_seconds=active[0]['max_seconds'])
    confirmations=[t for t in state['tasks'] if t['kind']=='confirmation']
    confirmation=dict(status='NONE',window=dispatch['confirmation_window'])
    if confirmations:
        task=next((t for t in confirmations if t['status'] in s.OPEN),confirmations[-1])
        end=s.utc(task['fixed_input_window']['end_exclusive'])
        ready=end+timedelta(minutes=budget['market_available_delay_minutes'])
        reason=('WAIT_FORWARD' if now<ready else 'WAIT_INPUT_MATERIALIZATION') if task['status']=='WAITING_DATA' else task['status']
        confirmation=dict(task_id=task['id'],status=task['status'],reason=reason,
            window=task['fixed_input_window'],earliest_publication_ready_at=s.stamp(ready),
            candidate_sha256=task['candidate_sha256'],max_seconds=task['max_seconds'],
            blocks_entire_system=False,native_started=bool(task.get('started_at')))
    research=[t for t in state['tasks'] if t['kind']=='research' and t['status'] in s.OPEN]
    exploration=dict(status='NONE',reason='WAITING_FOR_REPORT_SUCCESSOR_REVIEW',
        explanation='当前没有已登记的短期后继；报告后的唯一下一方向尚待登记，不生成虚构任务。')
    if research:
        task=research[0];exploration=dict(task_id=task['id'],status=task['status'],mechanism=task['mechanism'],
            variants=task['variants'],max_seconds=task['max_seconds'])
        exploration.update(queued_reason(root,state,task,budget,dispatch,now) if task['status'] in {'QUEUED','WAITING_DATA'} else
                           dict(reason='ACTUAL_COMPUTE_'+task['status']))
    elif next_review_path:
        path=Path(next_review_path);raw=path.read_bytes();review=json.loads(raw)
        exploration['successor_review']=dict(path=str(path.resolve()),sha256=s.digest(raw),
            status=review.get('status','UNKNOWN'),reason=review.get('reason','UNKNOWN'))
        if all(isinstance(review.get(k),str) and review[k].strip() for k in ('status','reason')):
            exploration.update(reason=review['status'],explanation=review['reason'])
    return dict(status='READ_ONLY_LANE_SNAPSHOT',observed_at=s.stamp(now),
        dispatch_binding_sha256=result['dispatch_binding_sha256'],actual_compute=compute,
        confirmation=confirmation,observer=observer_status(root,dispatch,now),exploration=exploration,
        execution_performed=False,market_values_exposed=False)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',required=True);p.add_argument('--policy',required=True)
    p.add_argument('--dispatch-policy',required=True);p.add_argument('--next-review-json')
    a=p.parse_args()
    try:result=build(a.root,a.policy,a.dispatch_policy,a.next_review_json)
    except (ValueError,KeyError,TypeError,OSError) as exc:
        result=dict(status='STATUS_INTEGRITY_BLOCKED',error=str(exc),execution_performed=False,market_values_exposed=False)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True,allow_nan=False))


if __name__=='__main__':main()
