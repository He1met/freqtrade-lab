#!/usr/bin/env python3
"""Explicit percentRate adapter for one pinned response; no acquisition capability."""
import argparse
import json
from decimal import Decimal as D, InvalidOperation
from pathlib import Path
import sys
import time
import issue151_diagnostic as v1
from issue147_diagnostic import DataError, deadline, sha, utc, write

RESPONSE_SHA='74422c92303df4cacc40823129306ebc8a90b6c53f289c238d6f4674c5f03d61'
ROOT=v1.ROOT

def macro_check(payload, expected):
    if not isinstance(payload,dict) or set(payload)!={'refRates'} or not isinstance(payload['refRates'],list) or not payload['refRates']:
        raise DataError('macro envelope')
    converted=[]
    for r in payload['refRates']:
        if not isinstance(r,dict) or r.get('type')!='EFFR' or 'percentRate' not in r or 'percent' in r:
            raise DataError('explicit percentRate-only EFFR schema required')
        if isinstance(r['percentRate'],bool): raise DataError('rate boolean')
        try: value=D(str(r['percentRate']))
        except (InvalidOperation,ValueError): raise DataError('rate not decimal')
        if not value.is_finite(): raise DataError('rate nonfinite')
        record=dict(r);del record['percentRate'];record['percent']=value
        converted.append(record)
    # Deliberate internal conversion into frozen calendar checker; never a source fallback.
    return v1.macro_check({'refRates':converted},expected)

def check(m):
    if m['response_sha256']!=RESPONSE_SHA or m['budget']!={'offline_validation':1,'analysis':1,'seconds':180,'units':21,'retries':0,'new_get':0}: raise ValueError('v2 identity')
    if sha(m['v1_manifest'])!=m['v1_manifest_sha256']: raise ValueError('v1 manifest drift')
    original=json.loads(Path(m['v1_manifest']).read_text());expected=v1.check(original)
    for p,h in m['bindings'].items():
        if sha(p)!=h: raise ValueError('v2 binding drift: '+p)
    if sha(ROOT/'acquisition/response.json')!=RESPONSE_SHA: raise ValueError('original response drift')
    return original,expected

def validate(m,manifest_sha):
    _,expected=check(m)
    root=ROOT/'validation-v2';root.mkdir()
    write(root/'attempt.json',dict(at_utc=utc(),manifest_sha256=manifest_sha,response_sha256=RESPONSE_SHA,offline_validation=1,new_get=0))
    try:
        result=macro_check(json.loads((ROOT/'acquisition/response.json').read_text(),parse_float=D),expected)
        write(root/'check.json',result)
        check(m)
        write(root/'terminal.json',dict(status='CHECKED_V2',check_sha256=sha(root/'check.json'),response_sha256=RESPONSE_SHA,at_utc=utc(),unknown_months=[k for k,x in result['months'].items() if x['mean'] is None]))
    except BaseException as exc:
        write(root/'failure.json',dict(status='FAILED_NO_RETRY',error=str(exc)));raise

def execute(m,manifest_sha,binding):
    original,expected=check(m)
    b=json.loads(Path(binding).read_text());validation=ROOT/'validation-v2'
    if b!={'manifest_sha256':manifest_sha,'response_sha256':RESPONSE_SHA,'validation_check_sha256':sha(validation/'check.json'),'validation_terminal_sha256':sha(validation/'terminal.json')}:
        raise ValueError('v2 validation binding')
    if json.loads((validation/'terminal.json').read_text())['status']!='CHECKED_V2': raise ValueError('not validated')
    root=ROOT/'analysis';root.mkdir()  # Same original analysis slot, never a new allowance.
    write(root/'attempt.json',dict(at_utc=utc(),manifest_sha256=manifest_sha,validation_binding_sha256=sha(binding),units=21,seconds=180,new_get=0))
    started=time.monotonic()
    try:
        with deadline(180):
            def deny(event,args):
                if event in ('socket.connect','socket.getaddrinfo','socket.bind'): raise ValueError('network forbidden')
            sys.addaudithook(deny)
            macro=json.loads((validation/'check.json').read_text(),parse_float=D)
            summary,rows=v1.analyze(v1.load_btc(original),macro)
            check(m)
            for src in original['sources']:
                if sha(src['path'])!=src['sha256']: raise DataError('post BTC drift')
            write(root/'events.json',rows);write(root/'summary.json',summary)
            write(root/'terminal.json',dict(status='SUCCEEDED',verdict=summary['verdict'],elapsed_seconds=time.monotonic()-started,events_sha256=sha(root/'events.json'),summary_sha256=sha(root/'summary.json')))
    except BaseException as exc:
        write(root/'failure.json',dict(status='FAILED_NO_RETRY',error=str(exc)));raise

def main():
    p=argparse.ArgumentParser();p.add_argument('command',choices=['check','validate','execute']);p.add_argument('--manifest',required=True);p.add_argument('--sha256',required=True);p.add_argument('--validation-binding');a=p.parse_args()
    if sha(a.manifest)!=a.sha256: raise ValueError('manifest SHA')
    m=json.loads(Path(a.manifest).read_text());check(m)
    if a.command=='validate':validate(m,a.sha256)
    elif a.command=='execute':execute(m,a.sha256,a.validation_binding)
    else:print('CONTROL_PASS_V2_NO_MARKET_STATISTICS')

if __name__=='__main__':main()
