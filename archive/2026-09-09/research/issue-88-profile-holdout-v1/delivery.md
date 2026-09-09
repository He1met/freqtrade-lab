# Issue88 engineering delivery

Worktree: `/Users/shenjianpeng/.codex/worktrees/7183/freqtrade-lab`
Branch: `codex/profile-spot-holdout-continuation-v1`
Issue: https://github.com/He1met/freqtrade-lab/issues/88
PR: https://github.com/He1met/freqtrade-lab/pull/89
Verified remote head: `69777d83a570f4b9d2ca348cdc34fbf0ff354213`.
Worktree is clean; PR and Issue remain OPEN. No merge or close performed.

v2 completed through actual HTTP authorization, native D/H/Stress, parser,
importer and same-run atomic attach. Run `280d6da4-ea22-459b-8ed4-88e8e3f68940`.
The upstream Search handoff is an explicit test stub; H source is artificial
Feather written after authorization, composed by the actual provenance producer.
No acquisition HTTP ran. Real Search=0; real market values=0; Release=0.
The three executions are SUCCEEDED under COMPLETED, verdict remains NULL.

## Evidence

`native-batch-v2/recovery.json` freezes the source fixture and seven code SHAs.
`native-batch-v2/batch-result.json` records three executions and original D
snapshot preservation. `http-authorization.json`, `http-terminal.json` and
`native-calls.jsonl` record the actual HTTP and call sequence.

Persistent sanitized ZIP SHA-256:

- D: `8030682f3ffe6372143b4961759413910ae0450e5ead6e12ed7044f7ac646544`
- H: `90f4363a61ed060055baace6cd927f0f0c07e5a598d66471119ca0b1594fe699`
- Stress: `ad9b107cfa389205ec18cc825b30fda514c315809459dd920ce761d14b879108`

v1 remains FAILED: native execution succeeded, but two fixed-5m calendar
assumptions prevented attachment. Its DB/HTTP terminal remain unchanged. Its
initial D domain failure was recovered only by importing the retained ZIP and
calling the existing finalizer; no manual status or metric change. The first
recovery command incorrectly supplied an absolute archive path and was rejected
before mutation; using the required relative path completed import. Recovery
receipt retains before state and artifact/code SHA. No native D replay occurred.
The later proposed administrative state recovery was withdrawn and never run.

Native budget: v1 3 + separately authorized v2 3 = 6/6. No further native calls.
Persistent packages are sanitized native report/config/source/provenance ZIPs;
temporary raw exports were deleted by existing cleanup and are not recoverable
without rerunning. No such rerun was performed.

## Tests

Before native testing, ten related modules: 380 passed, zero skips. After the
spot importer fix: test_backtest_artifact.py 91 passed. After calendar fixes,
four Holdout/Profile modules passed 91 tests, and test_research_bundle.py passed
38 tests. Two initially incorrect new fixture dates were fixed in the test
before that final 38-pass run. These are overlapping suites, not an additive
unique-test total. No native environment or package installation was changed.
`git diff --check` and serve_research_console.py --help passed.

Pinned test command (select affected modules as needed; does not invoke native):

```sh
FTLAB_TEST_SITE=$(uv run --with pytest python -c 'import pathlib, pytest; print(pathlib.Path(pytest.__file__).parent.parent)')
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="/Users/shenjianpeng/.codex/runs/freqtrade-lab/issue-43-profile-driven-v1/freqtrade:$PWD:$FTLAB_TEST_SITE" /Users/shenjianpeng/.codex/runs/freqtrade-lab/issue-43-profile-driven-v1/venv/bin/python - <<'PY'
import sys, types
from pathlib import Path
local_tests = types.ModuleType('tests')
local_tests.__path__ = [str(Path.cwd() / 'tests')]
sys.modules['tests'] = local_tests
import pytest
raise SystemExit(pytest.main(['-q', '-p', 'no:cacheprovider', '--disable-warnings', 'tests/test_profile_holdout.py', 'tests/test_research_bundle.py', 'tests/test_holdout_run.py', 'tests/test_holdout_atomic.py', 'tests/test_holdout_console_http.py', 'tests/test_backtest_artifact.py']))
PY
```

Operator commands and failure/restart boundaries are in the single repository
document `docs/profile-spot-holdout-continuation-v1.md`. Completed runs can be read
with the same Console arguments; do not repeat acquisition or authorization.
Failed one-shot runs have no automatic retry/reset. Frozen implementation drift
is rejected. Future real H acquisition still needs separate authorization.
