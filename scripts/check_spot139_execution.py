#!/usr/bin/env python3
"""Actual read-only entrypoint: validate fixed inputs and refuse unbound scoring."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from lab.spot139_binding import BindingError,deny_network,preflight

def main():
    p=argparse.ArgumentParser();p.add_argument('manifest',type=Path);p.add_argument('--manifest-sha256',required=True);a=p.parse_args()
    sys.addaudithook(deny_network)
    from lab.spot139_binding import sha
    try:
        if sha(a.manifest)!=a.manifest_sha256:raise BindingError('manifest changed')
        result=preflight(json.loads(a.manifest.read_bytes()));print(json.dumps(result));return 2
    except BindingError as exc:print(json.dumps(dict(status='BLOCKED_CONTROL',reason=str(exc),native_calls=0,economic_result=None)));return 2
if __name__=='__main__':sys.exit(main())
