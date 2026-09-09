Profile spot daily runs could not continue from a passed Development result to Holdout in the existing Console. This change binds an explicitly authorized Holdout-only source to the same run, uses the frozen Profile gate and daily window throughout, and atomically attaches HOLDOUT/HOLDOUT_STRESS evidence while keeping Release sealed. It also fixes the importer’s perpetual-only domain check and two fixed-5m calendar assumptions exposed by native testing.

The six-table schema and pinned native runtime are unchanged. The original Development snapshot keys/hashes remain intact; Holdout source provenance is appended independently. Base fees apply to D/H and only Stress accepts the frozen multiplier. Source/window/identity drift and duplicate authorization fail closed.

Validation: 380 related tests passed before native testing; after the importer fix its 91 tests passed, and after calendar fixes the affected Holdout/Profile tests (91) and bundle tests (38) passed. These overlap. `git diff --check` and Console CLI help passed. A separately authorized synthetic v2 batch completed actual HTTP authorization, native D/H/Stress once each, parsing/import, atomic attachment and HTTP readback: one COMPLETED run, three SUCCEEDED executions, original D snapshot preserved, Release count zero.

The prior synthetic v1 batch is retained as NATIVE_EXECUTION_PASS / ATTACH_FAILED; it exposed the calendar defects. Total native calls were 6 (v1 3 + authorized v2 3). Upstream Search was an explicit test stub and Holdout source was artificial, not network-acquired. Real Search and market requests were zero; this is engineering evidence, not strategy profitability. Persistent ZIPs are sanitized native evidence, not byte-identical temporary exports.

Operator commands and failure boundaries: `docs/profile-spot-holdout-continuation-v1.md`. Runtime receipts/DBs remain outside Git under `/Users/shenjianpeng/.codex/runs/freqtrade-lab/issue-88-profile-holdout-v1/`.

Refs #88. Awaiting supervising-task review; no merge or Issue closure authorized in this delivery.
