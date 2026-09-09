#!/usr/bin/env python3
"""Run one frozen job only after its fixed-head review authorizes live providers."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lab.discovery_job import MANIFEST, run_job, check_manifest, canonical, sha
from lab.literature_discovery import read_batch
from lab.mechanism_precheck import PrecheckError


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest', type=Path, default=MANIFEST)
    p.add_argument('--execute-reviewed-manifest-sha', help='Explicit reviewed canonical manifest SHA; omission is offline plan only')
    a = p.parse_args()
    try:
        manifest, _ = read_batch(a.manifest); check_manifest(manifest)
        digest = sha(canonical(manifest))
        if a.execute_reviewed_manifest_sha is None:
            result = dict(status='PLAN_ONLY_NO_EXTERNAL_CALLS', manifest_sha256=digest, job_id=manifest['job_id'])
        else:
            if a.execute_reviewed_manifest_sha != digest: raise PrecheckError('MANIFEST_SHA_MISMATCH')
            result = run_job(manifest)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0 if result['status'] in ('COMPLETED_KNOWLEDGE_ONLY', 'PLAN_ONLY_NO_EXTERNAL_CALLS') else 2
    except (PrecheckError, OSError, ValueError, TypeError) as exc:
        print(json.dumps(dict(status='BLOCKED_INPUT', error_type=type(exc).__name__)))
        return 2


if __name__ == '__main__': raise SystemExit(main())
