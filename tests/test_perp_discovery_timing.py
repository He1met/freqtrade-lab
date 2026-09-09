import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from scripts import perp_discovery_timing as timing


class TimingTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(prefix="perp-timing-", dir="/tmp")
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.reference = self.root / "synthetic.json"
        self.reference.write_text('{"fixture":"synthetic; no market data"}\n')
        self.log = self.root / "timing.jsonl"
        self.seconds = 0
        self.boot = "synthetic-boot"
        self.monotonic_offset = 0

    def clock(self):
        return dict(utc=(datetime(2026, 1, 1, tzinfo=timezone.utc) +
                         timedelta(seconds=self.seconds)).isoformat(),
                    monotonic_ns=int((self.seconds + self.monotonic_offset) * 1e9),
                    boot_id=self.boot)

    def run_event(self, command, **kwargs):
        return timing.run(command, self.log, _clock_fn=self.clock, **kwargs)

    def begin(self):
        return self.run_event("begin", reference=self.reference, purpose="synthetic test",
                              phase="SEARCH_READ")

    def test_continuous_intervals_include_report_and_wait_without_refund(self):
        self.begin()
        self.seconds = 10
        self.run_event("phase", phase="REPORT")
        self.seconds = 17
        self.run_event("phase", phase="MAINTENANCE_WAIT", evidence=self.reference)
        self.seconds = 20
        self.run_event("phase", phase="USER_IDLE")
        self.seconds = 25
        result = self.run_event("finish")
        self.assertEqual(result["phase_wall_seconds"], dict(SEARCH_READ=10, REPORT=7,
                         MAINTENANCE_WAIT=3, USER_IDLE=5))
        self.assertEqual(result["search_read_plus_report_seconds"], 17)
        self.assertEqual(result["conservative_charged_seconds"], 25)
        self.assertEqual(result["automatically_excluded_seconds"], 0)
        self.assertFalse(result["pending_reservation"])
        self.assertIsNone(result["cpu_seconds"])
        self.assertIsNone(result["exact_model_cost"])
        self.assertTrue(result["intervals"][2]["potentially_excludable"])
        self.assertEqual(self.run_event("status"), result)

    def test_open_interval_keeps_unknown_and_reservation(self):
        self.begin()
        self.seconds = 12
        result = self.run_event("phase", phase="REPORT")
        self.assertEqual(result["status"], "OPEN")
        self.assertTrue(result["pending_reservation"])
        self.assertEqual(result["reliable_closed_seconds"], 12)
        self.assertIsNone(result["phase_wall_seconds"]["REPORT"])
        self.assertIsNone(result["search_read_plus_report_seconds"])
        self.assertIsNone(result["conservative_charged_seconds"])

    def test_clock_tolerance_uses_max_and_anomalies_are_unknown(self):
        self.begin()
        self.seconds, self.monotonic_offset = 9, 1
        result = self.run_event("finish")
        interval = result["intervals"][0]
        self.assertEqual(result["status"], "FINISHED")
        self.assertEqual(interval["utc_elapsed_seconds"], 9)
        self.assertEqual(interval["monotonic_elapsed_seconds"], 10)
        self.assertEqual(interval["conservative_seconds"], 10)
        self.assertEqual(result["phase_wall_seconds"]["SEARCH_READ"], 9)
        self.assertEqual(result["phase_conservative_seconds"]["SEARCH_READ"], 10)
        self.assertEqual(result["search_read_plus_report_seconds"], 10)
        self.assertEqual(result["reliable_closed_seconds"], 10)
        self.assertEqual(result["conservative_charged_seconds"], 10)
        for kind in ("backwards", "boot", "disagreement", "missing_boot"):
            with self.subTest(kind=kind):
                self.log = self.root / (kind + ".jsonl")
                self.seconds, self.boot, self.monotonic_offset = 10, "synthetic-boot", 0
                self.begin()
                self.seconds = 20
                if kind == "backwards":
                    self.seconds = 9
                elif kind == "boot":
                    self.boot = "different-boot"
                elif kind == "missing_boot":
                    self.boot = None
                else:
                    self.monotonic_offset = 3
                result = self.run_event("finish")
                self.assertEqual(result["status"], "UNKNOWN_RECONCILE")
                self.assertTrue(result["pending_reservation"])
                self.assertIsNone(result["conservative_charged_seconds"])
                self.assertIsNone(result["phase_wall_seconds"]["SEARCH_READ"])

    def test_duplicate_begin_and_finished_append_preserve_bytes(self):
        self.begin()
        original = self.log.read_bytes()
        with self.assertRaises(FileExistsError):
            self.begin()
        self.assertEqual(self.log.read_bytes(), original)
        with self.log.open() as held:
            fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
            for command in ("status", "finish"):
                with self.assertRaises(BlockingIOError):
                    self.run_event(command)
            self.assertEqual(self.log.read_bytes(), original)
        self.seconds = 1
        self.run_event("finish")
        original = self.log.read_bytes()
        for command, kwargs in (("finish", {}), ("phase", {"phase": "REPORT"})):
            with self.assertRaises(ValueError):
                self.run_event(command, **kwargs)
            self.assertEqual(self.log.read_bytes(), original)

    def test_reference_drift_corruption_and_invalid_phase_refuse_append(self):
        self.begin()
        original = self.log.read_bytes()
        self.reference.write_text('{"changed":true}\n')
        with self.assertRaises(ValueError):
            self.run_event("phase", phase="REPORT")
        self.assertEqual(self.log.read_bytes(), original)
        self.reference.write_text('{"fixture":"synthetic; no market data"}\n')
        with self.assertRaises(ValueError):
            self.run_event("phase", phase="NOT_A_PHASE")
        self.assertEqual(self.log.read_bytes(), original)
        for bad in (b"{broken}\n", original[:-1]):
            self.log.write_bytes(bad)
            with self.assertRaises(ValueError):
                self.run_event("finish")
            self.assertEqual(self.log.read_bytes(), bad)

    def test_real_cli_entrypoints_and_no_backdating_argument(self):
        script = Path(timing.__file__).resolve()
        def cli(*args):
            return subprocess.run([sys.executable, str(script), *args],
                                  env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                                  capture_output=True, text=True, timeout=10)
        common = ("--log", str(self.log))
        begin = cli("begin", *common, "--reference", str(self.reference),
                    "--purpose", "synthetic CLI", "--phase", "SEARCH_READ")
        self.assertEqual(begin.returncode, 0, begin.stderr)
        self.assertEqual(json.loads(begin.stdout)["status"], "OPEN")
        phase = cli("phase", *common, "--phase", "REPORT")
        self.assertEqual(phase.returncode, 0, phase.stderr)
        before = self.log.read_bytes()
        self.assertEqual(cli("finish", *common, "--utc", "2025-01-01").returncode, 2)
        self.assertEqual(self.log.read_bytes(), before)
        finish = cli("finish", *common)
        self.assertEqual(finish.returncode, 0, finish.stderr)
        status = cli("status", *common)
        self.assertEqual(status.returncode, 0, status.stderr)
        result = json.loads(status.stdout)
        self.assertEqual(json.loads(finish.stdout), result)
        if result["status"] == "FINISHED":
            self.assertGreater(result["reliable_closed_seconds"], 0)
        else:  # A sandbox may deny the real boot identity; never invent one.
            self.assertEqual(result["status"], "UNKNOWN_RECONCILE")
            self.assertTrue(result["pending_reservation"])
            self.assertIsNone(result["conservative_charged_seconds"])


if __name__ == "__main__":
    unittest.main()
