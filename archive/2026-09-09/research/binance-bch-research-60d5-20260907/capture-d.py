"""One authorized call to the existing project capture, no strategy execution."""
from pathlib import Path
import sys,json
repo=Path('/Users/shenjianpeng/.codex/worktrees/60d5/freqtrade-lab');sys.path.insert(0,str(repo))
from lab.binance_source import capture_native
from lab.bounded_research import canonical
from scripts.fetch_okx_profile_data import configure_profile_acquisition
r=Path(__file__).parent
full=configure_profile_acquisition(r/'lab.sqlite','issue96-bch-trend28-v1',r/'window.json',29,json.loads((r/'economic-gate.json').read_bytes()),json.loads((r/'single-baseline.json').read_bytes()))
(r/'frozen-source-contract.json').write_bytes(canonical(full))
capture=dict(full,search_timerange='20240715-20250714',development_timerange=None)
(r/'capture-network-boundary.json').write_bytes(canonical({'purpose':'NETWORK_BOUNDARY_ONLY_NOT_RESEARCH_PROFILE','capture_contract':capture,'original_research_contract_file':'frozen-source-contract.json','original_protocol_file':'frozen-protocol.md'}))
receipts,raw=capture_native(r/'d-capture',capture)
(r/'d-capture-complete.json').write_bytes(canonical({'http_receipts':str(receipts),'raw_dir':str(raw),'strategy_runs':0,'classification':'MECHANICAL_SOURCE_ACQUISITION_ONLY'}))
print('D_CAPTURE_COMPLETE_MECHANICAL_ONLY')
