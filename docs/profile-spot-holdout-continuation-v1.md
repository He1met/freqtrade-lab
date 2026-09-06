# Profile spot 1d Holdout continuation

Issue #88 adds an explicitly authorized Holdout source and continues the same
eligible Development ResearchRun through HOLDOUT and HOLDOUT_STRESS. The scope
is OKX spot, one pair, daily candles and the existing six-table database.
Completion attaches evidence; it does not establish profitability or release.

## Operator entrypoint

Use the existing frozen Profile Search root, Development pilot, runtime root,
database and pinned Freqtrade 2026.7 environment. First inspect the Development
run and obtain authorization to acquire its Holdout plus required warmup. The
following command is the acquisition action, not a read-only preview:

Set the environment explicitly first. This local example uses the native source
and Python verified by the Issue88 synthetic batch; use the reviewed project
checkout containing this change. Native source must precede site-packages and
the project on the import path so Freqtrade retains its pinned Git identity.

```sh
export FTLAB_PROJECT_ROOT=/Users/shenjianpeng/.codex/worktrees/7183/freqtrade-lab
export FTLAB_NATIVE_SOURCE=/Users/shenjianpeng/.codex/runs/freqtrade-lab/issue-43-profile-driven-v1/freqtrade
export FTLAB_PYTHON=/Users/shenjianpeng/.codex/runs/freqtrade-lab/issue-43-profile-driven-v1/venv/bin/python
cd "$FTLAB_PROJECT_ROOT"
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$FTLAB_NATIVE_SOURCE:$FTLAB_PROJECT_ROOT"
```

Set `FTLAB_DATABASE` to the existing approved run database,
`FTLAB_RESEARCH_RUN_ID` to its eligible Development UUID, `FTLAB_RUNTIME_ROOT`
to the original Console runtime root, `FTLAB_PILOT_ROOT` to its frozen
Development pilot and `FTLAB_SEARCH_ROOT` to its verified Search root. These
must be the original run's paths; do not substitute the artificial test DB for
a real research run. The executable alone does not establish this environment.

```sh
"$FTLAB_PYTHON" scripts/fetch_okx_profile_data.py \
  --profile-database "$FTLAB_DATABASE" \
  --authorize-holdout-source "$FTLAB_RESEARCH_RUN_ID"
```

This verifies the frozen Development gate, Candidate and Profile, then writes
`holdout-source-authorization.json` exclusively before any Holdout values are
read. The window starts at Development's exclusive stop and spans the frozen
Profile's `holdout_days`; the Candidate's bounded lookback sets the warmup.
Output is `<run_dir>/holdout-source`. Profile, output, window, fee and warmup
overrides are forbidden. Failed acquisition retains the authorization receipt
and removes the incomplete new source; it does not authorize an automatic retry.

Start the existing Console with the same frozen paths and one selected run:

```sh
"$FTLAB_PYTHON" scripts/serve_research_console.py \
  --database "$FTLAB_DATABASE" --runtime-root "$FTLAB_RUNTIME_ROOT" \
  --pilot-root "$FTLAB_PILOT_ROOT" --search-root "$FTLAB_SEARCH_ROOT" \
  --holdout-research-run-id "$FTLAB_RESEARCH_RUN_ID" \
  --freqtrade-python "$FTLAB_PYTHON" --freqtrade-source "$FTLAB_NATIVE_SOURCE"
```

Use the existing ResearchRun Holdout authorization action. Its HTTP equivalent
is `POST /api/research-runs/<id>/actions` with
`{"action":"AUTHORIZE_HOLDOUT"}` under the Console's existing request checks.
Read back `GET /api/research-runs/<id>`. Startup checks source control metadata;
execution authorization verifies and materializes source values, consumes the
one-shot action and starts the existing worker. Repeated authorization fails.
Other run IDs remain sealed in this Profile Console. Judge/Release remain sealed.

## Binding and failure behavior

- The original Development snapshot keys and hashes remain unchanged. The
  appended Holdout authorization binds original snapshot, D artifact, Candidate,
  Profile, window, independent source provenance and pinned implementation.
- D and H use the base Profile fee. Only HOLDOUT_STRESS uses the frozen Profile
  stress multiplier; it uses exactly the H data view. Daily sources must contain
  the complete UTC window plus warmup, with no gaps, duplicates or extra rows.
- Importer domain follows the parsed artifact's spot/futures mode. Exchange,
  margin, pair, timeframe and costs retain their independent checks.
- Authorized execution ends and cross-scenario calendar spans use the validated
  5m/1d bar duration. Unknown periods fail closed. Both H artifacts attach in
  one transaction after all three scenarios pass identity and provenance checks.
- Invalid inputs, worker failure or attach failure preserve unknown metrics and
  consume the authorization. There is no automatic state reset or rerun.

## Verification boundary

The opt-in `tests/native_profile_holdout.py NEW_OUTPUT_ROOT` uses artificial
prices and an explicitly stubbed upstream Search handoff. Native execution,
artifact parsing/import, Profile source composition, actual Console HTTP action,
worker and atomic attachment are real. It calls no market endpoint. Run it only
with an explicitly assigned native-call budget and the pinned dependency set;
ordinary pytest does not invoke it. Existing roots are refused.

On 2026-09-06, batch v1 consumed D/H/Stress once each. Native produced all three
artifacts, but two remaining fixed-5m assumptions prevented H attachment. Its
original FAILED database and HTTP terminal were retained. D's earlier spot
domain importer failure was recovered through the existing importer/finalizer
using its retained artifact, without a second D call or manual status update.

After fixing those calendar assumptions, separately authorized batch v2 used a
new directory and new implementation receipts. D/H/Stress each ran once, all
three executions attached as SUCCEEDED under one COMPLETED run, the original D
snapshot keys stayed identical, and Release count stayed zero. Total native
calls were 6, real Search calls and market-data requests were zero. This validates
the engineering path; it is not a real strategy finalist or economic verdict.

Persistent evidence ZIPs contain the native report, strategy, configuration and
verified provenance. They are sanitized packages, not byte-identical temporary
native export ZIPs; the existing executor removes its temporary export directory.
Runtime evidence and databases stay outside Git.
