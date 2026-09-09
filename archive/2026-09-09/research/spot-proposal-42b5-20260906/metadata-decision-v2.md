# Metadata decision v2 — 2026-09-06

Only identity/date/source binding checked. No economic metrics or raw market values output in this check. Previous exposure incident remains recorded.

## Issue #32 resolved

Exact authorized root: `/Users/shenjianpeng/Documents/freqtrade-lab-local/issue-34-search-v2-console-20260901.vhBRO4/search-campaign`.

`search-terminal.json` campaign_id matches `campaign.json`: cc4b8e6a-2972-46ac-9fc9-707b26ec2f93. SHA-256 of campaign.json equals terminal.campaign_sha256. SHA-256 of acquisition/retained-data-provenance.json equals campaign.data_provenance_sha256. The same provenance hash is also bound by campaign-round-1.json. Its different campaign hash is expected for the earlier round; the final campaign has the terminal match.

Provenance identity: pair XRP/USDT:USDT; instrument XRP-USDT-SWAP; pair family XRP-USDT. Score [2026-06-01T00:00:00Z,2026-07-01T00:00:00Z), pre-roll starts 2026-05-31T22:00:00Z. Source kind: OKX perpetual futures OHLCV with mark and funding file-role metadata. portable_retained_fixture=false. No synthetic attribution. Source-acquisition references contain hashes only, no path leading to a distinct Issue #30 execution.

## Additional fixed asset order

TRX → XLM → ATOM, as directed before checking. Complete in-process parsing of the three authorized indexes, exact identity leaf projection including flat data.instrument_id: each asset NO_HIT in every index. Remote GitHub issues endpoint returned 86 total Issue/PR entries, below page size 100; all Issue bodies/titles were matched in process for exact pair/instrument identity, and none matched these three assets. No Issue body or result was output.

This establishes only no explicit pair/instrument hit in the checked scope; it does not establish global absence of older execution, comments, external tasks or unresolved #30 exposure. No asset has been substituted into a Search, and no fourth asset was checked.

## Remaining exact missing binding

Issue #30 imported Development terminal has no execution ID, research_run_id, pair, dated score window or source path in the previously inspected identity record. Its live Issue/comments also supply none. Required missing edge: that specific imported Development terminal → its actual execution receipt or retained-data-provenance source. Once that edge exists, pair/instrument, evaluation interval and source kind must be hash/ID-bound from it. #32's provenance cannot substitute for this edge. No same-asset or same-root relationship was proved.

Decision: #32 uncertainty resolved; #30 remains UNKNOWN. TRX/XLM/ATOM are not rejected economically and are not proven independent. Metadata-only stage cannot authorize a historical proposal until the missing #30 binding or a supervisory evidence adjudication resolves this uncertainty. Do not open a wider historical audit automatically. No market acquisition, backtest, DB/ledger write or repository change occurred.
