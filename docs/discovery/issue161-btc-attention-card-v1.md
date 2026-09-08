# Issue 161 — BTC public attention protocol v1

Status: PROTOCOL_PROPOSED; no feature/price acquisition or scoring authorized.
Base: origin/main 89eaa8fb3beeb67fb089dc870031d585aa318a55, 2026-09-08.
[Issue](https://github.com/He1met/freqtrade-lab/issues/161).

## Bounded discovery decision

Exactly three mechanisms were compared against the current mechanism precheck,
Issue 135 registry, current Issues and global ledger mechanism metadata.
No market values were read. Lead/lag, volatility, ranking, burn, EFFR, supply,
calendar, funding, trend, reversal and existing B families remain unchanged.

| Candidate | Evidence and limitation | This slice |
|---|---|---|
| Public investor attention | Original research reports attention predictability. Wikipedia views are a different, unvalidated proxy. | Select one fixed hypothesis |
| Network adoption / active addresses | Network-factor exposure has research support, but addresses are not users; activity can be fabricated or structurally different. No unique low-frequency rule established here. | Defer, not universal rejection |
| Mining production stress | Authors report production factors do not explain returns. Production cost alone does not establish a predictive selling-pressure rule. | Reject for this slice |

Primary evidence: Liu and Tsyvinski, [publisher abstract](https://academic.oup.com/rfs/article-abstract/34/6/2689/5912024);
[author interview at Yale](https://news.yale.edu/2018/08/06/assessing-cryptocurrency-yale-economist-aleh-tsyvinski)
describes Google/Twitter attention and the negative production-cost result.
The NBER PDF returned 403; full-paper methods were not verified.
[Coin Metrics definitions](https://docs.coinmetrics.io/network-data/network-data-overview/addresses/active-addresses)
support the addresses/users distinction. This is not a paper replication.

## Unique rule and fixed exposed window

- BTC spot long/flat, no leverage.
- Feature: English Wikipedia article Bitcoin, all-access, agent user, daily views.
  No languages, redirects, topic basket, sentiment or substitute source variants.
- Feature dates: 2021-01-01 through 2022-10-31 inclusive: 669 days, 22 months.
- For month m, compute mean daily views in the two preceding complete calendar
  months. ATTENTION_UP iff mean(m-1)/mean(m-2)-1 > 0; otherwise OTHER.
  Zero denominator is UNKNOWN. Monthly means avoid unequal calendar lengths.
- Exactly 21 event months, March 2021 through November 2022. Decision on the
  eighth at 00:00 UTC; enter at 01:00 UTC; exit next month's eighth at 01:00 UTC.
  Seven-day buffer is a design assumption, not verified historical publication lag.
- Reuse only original Issue 139 BTC 1h price source bound by Issue 151, within
  2021-03-08 00:00 through 2022-12-08 01:00 UTC. Freeze exact existing path/SHA
  before scoring. No price GET. This is EXPOSED_DEVELOPMENT, not independent.
  No date was chosen from the B chart; no B parameter changes.

Conceptual strategy holds BTC in UP months, cash otherwise. Diagnostic computes
identical one-quote round trips for all valid events, then reports UP, OTHER and
all-event distributions. Primary comparison: mean(UP)-mean(OTHER), identical times
and costs. All-event mean is unconditional baseline. Report counts, medians,
year composition and all missing events. These are event associations, not a
compounded wallet. Cash nominal return is zero without interest; unknown evidence
is never zero. Separate round-trip costs differ from a wallet held across UP months.

Base per-side fee f=0.001, slippage s=0.0006; stress f=0.002, s=0.0012.
Net multiplier = (exit_open/entry_open) * (1-s)/(1+s) * (1-f)^2.
No changed thresholds, dates, assets or holding periods after reading values.

## Source admission and limitations

Official [API reference](https://doc.wikimedia.org/generated-data-platform/aqs/analytics-api/reference/page-views.html)
states availability from July 2015.
[Concepts](https://doc.wikimedia.org/generated-data-platform/aqs/analytics-api/concepts/page-views.html)
describe content requests, redirect handling and bot classification: views are
not unique people, investors, inflows or positive sentiment.
[Access policy](https://doc.wikimedia.org/generated-data-platform/aqs/analytics-api/documentation/access-policy.html)
provides CC0 access and requires identifying User-Agent, without a key or paid API.
[Official tutorial](https://doc.wikimedia.org/generated-data-platform/aqs/analytics-api/tutorials/compare-page-metrics.html)
documents daily item fields and UTC timestamps.
[Changelog](https://doc.wikimedia.org/generated-data-platform/aqs/analytics-api/changelog.html)
records changes including automated-agent detection in 2020.

Historical publication times, revisions, bot reclassification and title identity
are not established. Historical acquisition is RECONSTRUCTED_EX_POST, not PIT.
News, education, English-language selection and price-to-attention reverse causality
remain confounders; no causal or price-adjusted alpha claim is permitted.

Metadata attempt 1 was [preregistered](https://github.com/He1met/freqtrade-lab/issues/161#issuecomment-5587184815).
HTTP 200, 257 bytes, current pageid 28249265, title Bitcoin; adjacent JSON contains
sanitized response and receipt. This proves current identity only, not AQS
availability, historical coverage or PIT. Attempt 2 unused.
Feature GETs=0, price GETs=0, model/native runs=0.

## Proposed next authorization — NOT granted

1. Freeze code/config, source bindings and synthetic checks before the first
   feature request or price read.
2. One feature GET, 20 seconds, 1 MiB cap, zero retries/redirects/paging:
   https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/en.wikipedia.org/all-access/user/Bitcoin/daily/20210101/20221031
   User-Agent: freqtrade-lab-research/1.0 (https://github.com/He1met/freqtrade-lab).
   Acceptance of this full range is unverified; rejection stops without date
   splitting. Receipt UTC/status/bytes/raw SHA/request identity.
3. Require items array, exact identity fields, UTC YYYYMMDD00 timestamps, integer
   nonnegative views (boolean invalid), exactly 669 unique continuous days without
   extras. No zero filling. Source/schema/coverage failure => BLOCKED_DATA.
4. Bind existing BTC source, verify every held hour and positive boundary opens.
   Existing gaps leave affected events UNKNOWN; enumerate all 21, no repair or
   shifted events.
5. One offline diagnostic <=180 seconds, 21 events, zero retries/native runs,
   wallet writes or global-ledger mutations. Synthetic checks cover missing and
   duplicate dates, wrong identity, invalid counts, zero denominator, UTC boundary,
   price gaps and exact cost arithmetic.
6. Before values: either group with <5 valid events => UNDERPOWERED. Either group
   absent from either 2021 or 2022 => PERIOD_CONFOUNDED. In those cases report
   descriptive values only. Otherwise require positive UP-minus-OTHER mean under
   both costs; failure => STOP_RULE_NOT_SUPPORTED. Nonpositive UP mean under
   either cost => NO_LONG_COST_SUPPORT. Passing both yields only
   EXPOSED_DEVELOPMENT_ASSOCIATION; n>=5 is not a power calculation.
7. No qualification, 20% risk-gate relaxation, wallet drawdown claim, holdout or
   follow-up variant. Actual wallet drawdown remains UNKNOWN.

## Independent confirmation feasibility

A new historical feature does not restore independence to exposed BTC outcomes.
No unused historical confirmation window is established; sealed data stay closed.
Future as-observed inputs can be received and hashed before a future decision even
when the feature months precede acquisition. For example, an October 8 decision
could use August/September views captured October 7–8 before the decision, subject
to new approval and an unused outcome window. This is feasibility only, not a
reservation or third forward authorization. Historical revision uncertainty stays
explicit. This card does not impose an arbitrary multi-year waiting requirement.

B first daily slot remains September 10 00:10 UTC; Issue 155 first supply slot
remains October 7. Their grants/freezes are unchanged. Issue 161 stays OPEN pending
supervisor acceptance and a separately bounded execution grant.
