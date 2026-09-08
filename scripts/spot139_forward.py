#!/usr/bin/env python3
"""Check a fixed source package; init/daily require external registered grants."""
import argparse
import json
import sys
from pathlib import Path
from datetime import date
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from lab import spot139_forward as f
from lab import spot139_daily as d


def read_bound(path,sha):
    raw=Path(path).read_bytes()
    if d.digest(raw)!=sha: raise ValueError('file SHA changed')
    return json.loads(raw)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',choices=['check','init','daily'])
    p.add_argument('--manifest',required=True);p.add_argument('--manifest-sha256',required=True)
    p.add_argument('--grant');p.add_argument('--grant-sha256');p.add_argument('--data-day')
    a=p.parse_args();m=read_bound(a.manifest,a.manifest_sha256);f.check_manifest(m)
    if a.command=='check' and not a.grant:
        print('PACKAGE_CHECK_PASS_EXTERNAL_GRANT_AND_REGISTRATION_REQUIRED_NO_IO');return
    if not a.grant or not a.grant_sha256: raise ValueError('external grant required')
    g=read_bound(a.grant,a.grant_sha256);f.check_grant(m,g)
    if a.command=='check':print('GRANTED_PACKAGE_CHECK_PASS_NO_ROOT_OR_SOURCE_READ');return
    if a.command=='init':print(json.dumps(f.initialize(m,g)));return
    if not a.data_day:raise ValueError('explicit UTC data-day required')
    day=(date.fromisoformat(a.data_day)-date(1970,1,1)).days
    print(json.dumps(f.run_daily(m,g,day)))


if __name__=='__main__':main()
