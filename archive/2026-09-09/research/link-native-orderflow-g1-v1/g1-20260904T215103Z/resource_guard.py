"""Ephemeral G1 owned-child watchdog. RSS measurement, not a backtest runner."""
import datetime, json, os, pathlib, signal, subprocess, sys, time
import psutil

ROOT = pathlib.Path(__file__).resolve().parent
DEADLINE = datetime.datetime(2026, 9, 5, 1, 51, 3, tzinfo=datetime.timezone.utc).timestamp()

def run(label, seconds, limit, argv):
    if time.time() >= DEADLINE:
        raise RuntimeError("G1 four-hour deadline reached")
    seconds = min(seconds, DEADLINE - time.time())
    stdout = (ROOT / (label + ".stdout")).open("xb")
    stderr = (ROOT / (label + ".stderr")).open("xb")
    began = time.monotonic()
    child = subprocess.Popen(argv, stdout=stdout, stderr=stderr, start_new_session=True,
                             env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    proc = psutil.Process(child.pid)
    identity = proc.create_time()
    peak = 0
    samples = 0
    reason = None
    terminated_at = None
    usage = None
    def own_group_signal(sig):
        try:
            p = psutil.Process(child.pid)
            if p.create_time() == identity and os.getpgid(child.pid) == child.pid:
                os.killpg(child.pid, sig)
        except ProcessLookupError:
            pass
        except psutil.NoSuchProcess:
            pass
    while True:
        pid, status, ru = os.wait4(child.pid, os.WNOHANG)
        if pid:
            child.returncode = os.waitstatus_to_exitcode(status)
            usage = ru
            break
        try:
            members = [proc] + proc.children(recursive=True)
            rss = 0
            for p in members:
                try:
                    rss += p.memory_info().rss
                except psutil.NoSuchProcess:
                    pass
            peak = max(peak, rss)
            samples += 1
        except psutil.NoSuchProcess:
            pass
        except psutil.Error:
            reason = reason or "RESOURCE_MEASUREMENT_FAILED"
        elapsed = time.monotonic() - began
        if reason is None and peak > limit:
            reason = "RSS_LIMIT"
        if reason is None and elapsed > seconds:
            reason = "TIMEOUT"
        if reason is not None:
            if terminated_at is None:
                own_group_signal(signal.SIGTERM)
                terminated_at = time.monotonic()
            elif time.monotonic() - terminated_at > 0.5:
                own_group_signal(signal.SIGKILL)
        time.sleep(0.02)
    stdout.close()
    stderr.close()
    os_peak_bytes = int(usage.ru_maxrss)  # macOS reports bytes
    if sys.platform != "darwin":
        os_peak_bytes *= 1024
    if os_peak_bytes > limit:
        reason = reason or "OS_PEAK_RSS_LIMIT"
    record = {
        "label": label, "argv": argv, "owned_pid": child.pid,
        "owned_process_created": identity, "new_process_group": child.pid,
        "exit_code": child.returncode, "stop_reason": reason,
        "elapsed_seconds": time.monotonic() - began,
        "sampled_tree_peak_rss_bytes": peak, "os_child_peak_rss_bytes": os_peak_bytes,
        "rss_limit_bytes": limit, "timeout_seconds": seconds, "samples": samples,
        "measurement": "RSS not VMS; 20ms tree polling plus wait4 OS high-water. Not kernel hard RSS allocation control.",
        "started_at_utc": datetime.datetime.fromtimestamp(time.time()-(time.monotonic()-began),datetime.timezone.utc).isoformat(),
        "finished_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat()
    }
    (ROOT / (label + ".resources.json")).write_text(json.dumps(record, indent=2)+"\n")
    print(json.dumps(record))
    return record

if __name__ == "__main__":
    label, seconds, limit, *argv = sys.argv[1:]
    assert label.replace("-", "").replace("_", "").isalnum()
    r = run(label, float(seconds), int(limit), argv)
    sys.exit(0 if r["exit_code"] == 0 and r["stop_reason"] is None else 2)
