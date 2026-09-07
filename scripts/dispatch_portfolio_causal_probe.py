#!/usr/bin/env python3
"""One synthetic/6 attempt, only after supervisor approval of the fixed binding."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import signal
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from lab.portfolio_budget import NativeBudget, BudgetError, RUNTIME_ROOT, canonical, verify_anchor, checkpoint_budget
from scripts.prepare_portfolio_causal_probe import REPO, prepare, verify_manifest, run_reserved


def write_new(path,value):
    raw=canonical(value)
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,"wb") as output:
        output.write(raw);output.flush();os.fsync(output.fileno())
    directory=os.open(path.parent,os.O_RDONLY)
    try: os.fsync(directory)
    finally: os.close(directory)
    return hashlib.sha256(raw).hexdigest()


def dispatch(source,binding):
    """Hold the same nonblocking writer lock from preflight through terminal."""
    with NativeBudget(RUNTIME_ROOT).locked() as budget:
        verify_anchor()  # Recheck after acquiring the sole writer lock.
        current=prepare(source)
        if canonical(current)!=canonical(binding):
            raise BudgetError("fixed preparation manifest changed before reservation")
        verify_manifest(binding,source)
        root=RUNTIME_ROOT/"runs/synthetic-6"
        if root.exists() or root.is_symlink():
            raise BudgetError("output exists; never overwrite an attempt")
        budget.reserve("synthetic/6",input_sha256=binding["input_sha256"],
                       code_sha256=binding["code_sha256"],source_sha256=binding["source_sha256"],
                       semantics_sha256=binding["semantics_sha256"])
        old_handler=signal.getsignal(signal.SIGALRM)
        def timeout(*_): raise TimeoutError("fixed 180 second synthetic worker budget expired")
        signal.signal(signal.SIGALRM,timeout)
        signal.alarm(180)
        status="FAILED"
        evidence={"market_execution_allowed":False,"economic_result":None}
        root_created=False
        try:
            # Persist the global checkpoint before any engine or output setup.
            checkpoint_budget()
            root.mkdir(parents=True,exist_ok=False,mode=0o700)
            root_created=True
            write_new(root/"bindings.json",binding)
            evidence=run_reserved(root,source,binding)
            status="SUCCEEDED"
        except BaseException as exc:
            status="INTERRUPTED" if isinstance(exc,(KeyboardInterrupt,SystemExit)) else "FAILED"
            evidence=dict(status=status,error_type=type(exc).__name__,reason=str(exc),
                          halt_liquidation=getattr(exc,"receipt",None),
                          market_execution_allowed=False,economic_result=None)
        finally:
            # Verify even a failed attempt. Failures never roll back the slot.
            try:
                verify_manifest(binding,source)
            except BaseException as exc:
                status="FAILED"
                evidence=dict(status=status,reason="post-execution code/input/source validation failed",
                              error_type=type(exc).__name__,attempt_evidence=evidence,
                              market_execution_allowed=False,economic_result=None)
            signal.alarm(0)
            signal.signal(signal.SIGALRM,old_handler)
        evidence={**evidence,"budget_status":status,"key":"synthetic/6"}
        result_hash=hashlib.sha256(canonical(evidence)).hexdigest()
        persistence_error=None
        try:
            if not root_created: raise OSError("attempt output directory was not created")
            write_new(root/"evidence.json",evidence)
        except OSError as exc:
            # Do not replace an existing artifact. Publish failure hash/terminal
            # in the durable ledger even if the artifact storage failed.
            persistence_error=exc
            status="FAILED"
            evidence={"status":status,"reason":"evidence persistence failed","attempt_evidence":evidence}
            result_hash=hashlib.sha256(canonical(evidence)).hexdigest()
        budget.finish("synthetic/6",status,result_hash)
        checkpoint_budget()
        if persistence_error is not None: raise persistence_error
        return dict(status=status,key="synthetic/6",evidence=str(root/"evidence.json"),market_execution_allowed=False)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native-source",type=Path,required=True)
    parser.add_argument("--execute-approved",action="store_true",required=True,
                        help="Use only after supervisor has approved this exact prepared revision")
    args=parser.parse_args()
    binding=json.loads((REPO/"docs/issue115-prepared-binding.json").read_bytes())
    result=dispatch(args.native_source.resolve(strict=True),binding)
    print(json.dumps(result))
    return 0 if result["status"]=="SUCCEEDED" else 2


if __name__=="__main__": raise SystemExit(main())
