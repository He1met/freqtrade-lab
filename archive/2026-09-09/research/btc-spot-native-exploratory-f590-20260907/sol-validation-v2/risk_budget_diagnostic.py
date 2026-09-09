"""Three preset retrospective sensitivities; no signals or new native execution."""
import io
import json
import zipfile
import pandas as pd
from runtime_control import ROOT, put, append, sha
from benchmark_audit import drawdown

STAKES = (100, 150, 250)
archive = ROOT/'search-data-01/search-results-round-1/99eb3df4-ebad-4d97-8dfd-0fdd2af826ce/raw/backtest-result-2026-09-07_10-08-30.zip'
assert sha(archive.read_bytes()) == '2319facb0bebe7c1cee61d48b7084e8de0e2988db618a3192ed7ec70881e7ee3'
economic = json.loads((ROOT/'S-economic-audit.json').read_text())
with zipfile.ZipFile(archive) as z:
    wallet = pd.read_feather(io.BytesIO(z.read(next(n for n in z.namelist() if n.endswith('_wallet.feather')))))
series = (wallet['rate'] * wallet['balance']).groupby(wallet['date']).sum().sort_index()
rows = []
for stake in STAKES:
    factor = stake / 250.0
    values = (1000.0 + factor * (series - 1000.0)).tolist()
    rows.append({'nominal_stake_usdt':stake,'initial_wallet_pct':stake/10,
                 'approx_net_usdt':factor*economic['net_usdt'],
                 'approx_final_wallet_usdt':1000+factor*economic['net_usdt'],
                 'approx_daily_open_DD_pct':drawdown(values)})
assert abs(rows[-1]['approx_daily_open_DD_pct'] - economic['independently_recomputed_daily_open_wallet_DD_pct']) < 1e-8
result = {'status':'RETROSPECTIVE_COUNTERFACTUAL_APPROXIMATION_ONLY',
    'preset_stakes':list(STAKES), 'scenarios':rows,
    'formula':'E_stake(t) = 1000 + (stake/250)*(E_original(t)-1000); final PnL scaled by same factor',
    'assumptions':'Exactly unchanged entry/exit dates, rates, stop decisions, fills and proportional costs. Same main pre-trade daily-open snapshot dates; no added endpoints.',
    'limits':'Amount rounding, minimum orders, available cash, slippage/fills and stop execution may change an actual run. This is not a backtest, new signal computation or validated candidate.',
    'selection':'No optimum solved, no exact stake inverted from the10% cap, no parameters selected, no candidate status changed.',
    'interpretation':'The observed rejection is account floating drawdown/position risk, not negative price economics. Scale sensitivity can prioritize a separately preregistered risk-budget question; these three approximations do not establish a stake that qualifies.',
    'trailing_or_profit_exit':'No alternate exit tested. This diagnostic cannot identify a superior take-profit or trailing rule, and does not authorize changing exits.',
    'original_candidate':'REJECTED_UNCHANGED', 'new_native_calls':0, 'new_signals':0,
    'new_market_HTTP':0, 'D_H_Stress_opened':False,
    'source_archive_sha256':sha(archive.read_bytes()), 'diagnostic_source_sha256':sha((ROOT/'risk_budget_diagnostic.py').read_bytes())}
put('risk-budget-diagnostic.json',result)
context = json.loads((ROOT/'after-rejection-research_context.json').read_text())
candidate = next(c for c in context['candidates'] if c['candidate_id']=='99eb3df4-ebad-4d97-8dfd-0fdd2af826ce')
assert candidate['status'] != 'READY'
search = json.loads((ROOT/'after-rejection-search_context.json').read_text())
assert search['state']['search_protocol_rejection']['outcome']=='REJECTED'
delivery = {'status':'PROTOCOL_REJECTION_ATTACHED_RISK_DIAGNOSTIC_COMPLETE',
    'attachment_receipt_sha256':sha((ROOT/'protocol-rejection-attachment-receipt.json').read_bytes()),
    'review_sha256':sha((ROOT/'search-protocol-rejection-review.json').read_bytes()),
    'diagnostic_sha256':sha((ROOT/'risk-budget-diagnostic.json').read_bytes()),
    'research_context_candidate':candidate,
    'context_limit':'Existing S-only Console uses unused-pilot: research/context reports BLOCKED_DATA/Pilot spec unavailable before the rejection-specific check. It is not READY. Independently invoked read-only existing require_no_protocol_rejection guard returns search_protocol_rejected. No D binding or run was opened to change displayed reason.',
    'search_context_rejection':'REJECTED; full failed gate and bound review shown to Console',
    'historical_core':'SEARCH_FINALIST_FROZEN unchanged',
    'native_generation_and_manual_projection_preserved':True,
    'market_calls_added':0,'native_calls_added':0,'D_H_Stress': 'UNOPENED',
    'diagnostic':result}
put('rejection-closeout-receipt.json',delivery)
previous=json.loads((ROOT/'protocol-rejection-authorization-ledger.json').read_text())['after_sha256']
ledger=append({'record_type':'SEARCH_REJECTION_ATTACHED_AND_RISK_DIAGNOSTIC',
    'status':delivery['status'],'receipt_path':str(ROOT/'rejection-closeout-receipt.json'),
    'receipt_sha256':sha((ROOT/'rejection-closeout-receipt.json').read_bytes()),
    'candidate_id':'99eb3df4-ebad-4d97-8dfd-0fdd2af826ce',
    'protocol_outcome':'REJECTED','failure_kind':'ACCOUNT_FLOATING_DRAWDOWN_POSITION_RISK',
    'new_native_calls':0,'new_market_calls':0,'D_H_Stress_opened':False,
    'diagnostic_kind':result['status'],'diagnostic_sha256':delivery['diagnostic_sha256']},previous)
put('rejection-closeout-ledger.json',ledger)
print(json.dumps({'scenarios':rows,'closeout_sha256':sha((ROOT/'rejection-closeout-receipt.json').read_bytes()),'diagnostic_sha256':delivery['diagnostic_sha256'],'ledger':ledger},indent=2))
