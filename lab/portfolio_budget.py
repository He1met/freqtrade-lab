"""Single-writer append-only reservation for the fixed portfolio native pilot.

The CLI uses one fixed Git-external anchor for every output directory. Tests may
construct a temporary ledger. There is no reset, delete, timeout-reclaim or
market-call operation in this slice. Even constructor failures consume a slot.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path

from lab.portfolio_preflight import PROTOCOL_SHA256, AdmissionError, _sha

RUNTIME_ROOT = Path.home()/".codex/runs/freqtrade-lab/btc-eth-portfolio-v1"
ANCHOR_LEDGER = Path.home()/"Documents/freqtrade-lab-local/search-research-supervision-20260902/global-research-ledger.jsonl"
ANCHOR_RECORD_SHA256 = "7aaba6a65e372275d3a65a2fbaaf79abdd3a9597ae98eba62e5344edf3af79e9"


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


class BudgetError(ValueError):
    pass


def verify_anchor():
    """Bind the CLI to the published, exact control row, even after appends."""
    matched, checkpoints = [], []
    for line in ANCHOR_LEDGER.read_bytes().splitlines():
        if not line.strip(): continue
        if hashlib.sha256(line).hexdigest() == ANCHOR_RECORD_SHA256:
            matched.append(json.loads(line))
        row=json.loads(line)
        if row.get("record_type")=="PORTFOLIO_NATIVE_BUDGET_CHECKPOINT" and row.get("protocol_sha256")==PROTOCOL_SHA256:
            checkpoints.append(row)
    if len(matched) != 1 or matched[0]["budget_root"] != str(RUNTIME_ROOT) or matched[0]["protocol_sha256"] != PROTOCOL_SHA256:
        raise BudgetError("trusted global budget anchor missing or moved")
    if checkpoints:
        try: raw=(RUNTIME_ROOT/"calls.jsonl").read_bytes()
        except OSError as exc: raise BudgetError("checkpointed budget ledger missing; cannot reset") from exc
        verify_checkpoint(raw, checkpoints[-1])


def verify_checkpoint(raw, checkpoint):
    length=checkpoint["bytes"]
    if type(length) is not int or length<=0 or len(raw)<length or hashlib.sha256(raw[:length]).hexdigest()!=checkpoint["sha256"]:
        raise BudgetError("budget differs from globally checkpointed prefix")


def checkpoint_budget():
    """Caller holds the native writer lock; preserve the old global byte prefix."""
    raw=(RUNTIME_ROOT/"calls.jsonl").read_bytes()
    row={"record_type":"PORTFOLIO_NATIVE_BUDGET_CHECKPOINT","protocol_sha256":PROTOCOL_SHA256,
         "bytes":len(raw),"sha256":hashlib.sha256(raw).hexdigest(),
         "at_utc":datetime.now(timezone.utc).isoformat()}
    with Path(str(ANCHOR_LEDGER)+".lock").open("a") as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        previous=ANCHOR_LEDGER.read_bytes()
        row["previous_prefix_sha256"]=hashlib.sha256(previous).hexdigest()
        with ANCHOR_LEDGER.open("ab") as output:
            output.write(canonical(row)+b"\n");output.flush();os.fsync(output.fileno())


class NativeBudget:
    def __init__(self, root):
        self.root = Path(root)

    @contextmanager
    def locked(self):
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.root.is_symlink():
            raise BudgetError("budget root may not be a symlink")
        fd = os.open(self.root/"writer.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "r+") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise BudgetError("another portfolio worker owns the budget") from exc
            try:
                yield LockedBudget(self.root)
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)


class LockedBudget:
    def __init__(self, root):
        self.path = root/"calls.jsonl"
        self.events = []
        self.previous = "0"*64
        if self.path.exists():
            if self.path.is_symlink():
                raise BudgetError("ledger may not be a symlink")
            raw = self.path.read_bytes()
            if len(raw) > 2*1024*1024 or (raw and not raw.endswith(b"\n")):
                raise BudgetError("ledger truncated or oversized; no calls allowed")
            for line in raw.splitlines():
                try:
                    row = json.loads(line)
                except (ValueError, UnicodeError) as exc:
                    raise BudgetError("ledger invalid") from exc
                if not isinstance(row, dict) or row.get("previous_sha256") != self.previous or row.get("protocol_sha256") != PROTOCOL_SHA256:
                    raise BudgetError("ledger chain or protocol changed")
                self.events.append(row)
                self.previous = hashlib.sha256(line).hexdigest()
        self._validate_history()

    def _validate_history(self):
        opened, ended, statuses, recovered = {}, set(), {}, set()
        for row in self.events:
            key = row.get("key")
            if row.get("event") == "RESERVED":
                if key in opened or any(k not in ended for k in opened):
                    raise BudgetError("duplicate or overlapping reservation")
                if key not in {f"synthetic/{n}" for n in range(1, 9)} | {f"retry/{n}" for n in range(1, 5)}:
                    raise BudgetError("non-synthetic or overbudget history")
                opened[key] = row
            elif row.get("event") in {"SUCCEEDED", "FAILED", "INTERRUPTED"}:
                if key not in opened or key in ended:
                    raise BudgetError("invalid terminal history")
                ended.add(key)
                statuses[key] = row["event"]
            elif row.get("event") == "AUDIT_RECOVERED":
                if statuses.get(key) != "FAILED" or key in recovered:
                    raise BudgetError("invalid audit recovery history")
                recovered.add(key)
            else:
                raise BudgetError("invalid ledger event")

    def _append(self, event):
        row = {**event, "schema": "portfolio-native-budget-v1", "protocol_sha256": PROTOCOL_SHA256,
               "at_utc": datetime.now(timezone.utc).isoformat(), "previous_sha256": self.previous}
        raw = canonical(row)
        fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "ab") as output:
            output.write(raw+b"\n"); output.flush(); os.fsync(output.fileno())
        # Persist directory entry as well as reservation bytes before native.
        directory = os.open(self.path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        self.events.append(row); self.previous = hashlib.sha256(raw).hexdigest()
        return row

    def pending(self):
        ends = {r["key"] for r in self.events if r["event"] != "RESERVED"}
        return [r for r in self.events if r["event"] == "RESERVED" and r["key"] not in ends]

    def reserve(self, key, *, input_sha256, code_sha256, source_sha256, retry_of=None, semantics_sha256=None):
        for value in (input_sha256, code_sha256, source_sha256):
            try:
                _sha(value)
            except AdmissionError as exc:
                raise BudgetError("invalid binding hash") from exc
        from lab.portfolio_causal import SEMANTICS_SHA, verify_binding
        from lab.portfolio_risk_v2 import V2_SHA, verify_v2
        allowed_slots={"synthetic/6":SEMANTICS_SHA,"synthetic/7":V2_SHA}
        if key in {"synthetic/6","synthetic/7","synthetic/8"}:
            if semantics_sha256 is None or semantics_sha256!=allowed_slots.get(key):
                raise BudgetError("causal slot requires its explicitly allowed semantics version")
        if semantics_sha256 is not None:
            if semantics_sha256==SEMANTICS_SHA: verify_binding(PROTOCOL_SHA256,SEMANTICS_SHA)
            elif semantics_sha256==V2_SHA: verify_v2(PROTOCOL_SHA256,V2_SHA)
            else: raise BudgetError("unknown semantics version")
        if self.pending():
            raise BudgetError("interrupted reservation must be recorded, never replayed")
        if any(r["key"] == key for r in self.events):
            raise BudgetError("native key already consumed")
        if key in {f"synthetic/{n}" for n in range(1, 9)}:
            if retry_of is not None:
                raise BudgetError("a repair consumes a retry slot, not a fresh synthetic slot")
        elif key in {f"retry/{n}" for n in range(1, 5)}:
            parent = next((r for r in self.events if r["key"] == retry_of and r["event"] == "RESERVED"), None)
            terminal = next((r for r in self.events if r["key"] == retry_of and r["event"] in {"FAILED", "INTERRUPTED"}), None)
            if parent is None or terminal is None or any(r["key"]==retry_of and r["event"]=="AUDIT_RECOVERED" for r in self.events) or parent["input_sha256"] != input_sha256 or parent["source_sha256"] != source_sha256:
                raise BudgetError("retry requires failed same-input/source parent")
            if parent.get("semantics_sha256") != semantics_sha256:
                raise BudgetError("retry semantics must equal failed parent")
            if any(r.get("retry_of") == retry_of for r in self.events):
                raise BudgetError("retry chain must reference its latest failed attempt")
        else:
            raise BudgetError("only eight synthetic and four repair slots allowed")
        return self._append({"event": "RESERVED", "key": key, "input_sha256": input_sha256,
                             "code_sha256": code_sha256, "source_sha256": source_sha256,
                             "retry_of": retry_of, **({"semantics_sha256":semantics_sha256} if semantics_sha256 is not None else {})})

    def finish(self, key, status, result_sha256):
        if status not in {"SUCCEEDED", "FAILED", "INTERRUPTED"} or [r["key"] for r in self.pending()] != [key]:
            raise BudgetError("terminal must close the sole pending reservation")
        try:
            _sha(result_sha256)
        except AdmissionError as exc:
            raise BudgetError("invalid result hash") from exc
        return self._append({"event": status, "key": key, "result_sha256": result_sha256})

    def recover_audit(self, key, result_sha256):
        if self.pending() or not any(r["key"] == key and r["event"] == "FAILED" for r in self.events) or any(r["key"] == key and r["event"] == "AUDIT_RECOVERED" for r in self.events):
            raise BudgetError("only a failed completed call can attach one recovered audit")
        _sha(result_sha256)
        return self._append({"event":"AUDIT_RECOVERED", "key":key,"result_sha256":result_sha256,"additional_native_calls":0})
