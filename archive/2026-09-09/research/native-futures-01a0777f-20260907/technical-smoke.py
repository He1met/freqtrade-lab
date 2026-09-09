"""One registered native engineering run, never a research candidate selection."""
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO=Path('/Users/shenjianpeng/.codex/worktrees/3f31/freqtrade-lab')
sys.path.insert(0,str(REPO))
from lab import research_candidate as rc
from lab.futures_costs import audit_from_source

ROOT=Path(__file__).resolve().parent
SMOKE=ROOT/'technical-smoke-v1'
NATIVE=Path('/Users/shenjianpeng/.codex/runs/freqtrade-lab/issue-43-profile-driven-v1/freqtrade')
PYTHON=NATIVE.parent/'venv/bin/python'
STRATEGY='EngineeringFundingSmoke'
SOURCE='''from pandas import DataFrame
from freqtrade.strategy import IStrategy

class EngineeringFundingSmoke(IStrategy):
    INTERFACE_VERSION = 3
    timeframe = "1d"
    can_short = True
    startup_candle_count = 14
    process_only_new_candles = True
    minimal_roi = {}
    stoploss = -0.99

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[dataframe["date"].dt.dayofweek == 0, "enter_long"] = 1
        dataframe.loc[dataframe["date"].dt.dayofweek == 3, "enter_short"] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[dataframe["date"].dt.dayofweek == 2, "exit_long"] = 1
        dataframe.loc[dataframe["date"].dt.dayofweek == 5, "exit_short"] = 1
        return dataframe
'''

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def receipt(path):return {'bytes':path.stat().st_size,'sha256':sha(path)}
def write(path,value):path.write_bytes(rc._canonical_bytes(value))

if sys.argv[1]=='prepare':
    SMOKE.mkdir()
    source=ROOT/'engineering-search/acquisition'
    # Inputs already QC'd; no network or later-phase data is read.
    provenance=json.loads((source/'retained-data-provenance.json').read_bytes())
    for name in ('config.json','market_snapshot.json','isolated_tiers_snapshot.json'):
        shutil.copyfile(source/name,SMOKE/name)
    shutil.copytree(source/'data',SMOKE/'data')
    for name in ('strategies','raw','bundle','user-data','home'):(SMOKE/name).mkdir()
    (SMOKE/'home/tmp').mkdir()
    strategy_path=SMOKE/f'strategies/{STRATEGY}.py'
    strategy_path.write_text(SOURCE)
    config=rc._runtime_config(json.loads((SMOKE/'config.json').read_bytes()),
        config_source=SMOKE/'config.json',data_dir=SMOKE/'data/binance',user_data_dir=SMOKE/'user-data',
        strategy_path=SMOKE/'strategies',strategy=STRATEGY,timerange='20231106-20231113',fee=.0005,export_dir=SMOKE/'raw')
    write(SMOKE/'config.json',config)
    provenance['files']={'config.json':receipt(SMOKE/'config.json'),
                        f'strategies/{STRATEGY}.py':receipt(strategy_path)}
    provenance['contract']['strategy']=f'strategies/{STRATEGY}.py'
    write(SMOKE/'retained-data-provenance.json',provenance)
    runner=SMOKE/'run_freqtrade_backtest.py'
    shutil.copyfile(REPO/'scripts/run_freqtrade_backtest.py',runner)
    tree=rc._prepare_freqtrade_source_snapshot(NATIVE,SMOKE/'native-source',SMOKE/'git-home',Path('/usr/bin/sandbox-exec'))
    write(SMOKE/'preflight.json',{'source_tree_sha256':tree,'strategy_sha256':sha(strategy_path),
        'runner_sha256':sha(runner),'source_provenance_sha256':sha(SMOKE/'retained-data-provenance.json'),
        'timerange':'20231106-20231113','purpose':'TECHNICAL_ECONOMIC_EXPOSURE_ONLY',
        'maximum_native_runs':1,'maximum_seconds':600,'no_parameter_selection':True,
        'long_and_short':'fixed calendar signals, not an economic hypothesis'})
    print('PREPARED_NO_BACKTEST')
elif sys.argv[1]=='complete-preflight':
    assert not (ROOT/'smoke-registration-receipt.json').exists()
    config=rc._runtime_config(json.loads((SMOKE/'config.json').read_bytes()),
        config_source=SMOKE/'config.json',data_dir=SMOKE/'data/binance',user_data_dir=SMOKE/'user-data',
        strategy_path=SMOKE/'strategies',strategy=STRATEGY,timerange='20231106-20231113',fee=.0005,export_dir=SMOKE/'raw')
    write(SMOKE/'config.json',config)
    provenance=json.loads((SMOKE/'retained-data-provenance.json').read_bytes())
    provenance['files']['config.json']=receipt(SMOKE/'config.json')
    write(SMOKE/'retained-data-provenance.json',provenance)
    frozen=json.loads((SMOKE/'preflight.json').read_bytes())
    frozen['source_provenance_sha256']=sha(SMOKE/'retained-data-provenance.json')
    write(SMOKE/'preflight.json',frozen)
elif sys.argv[1]=='run':
    assert (ROOT/'smoke-registration-receipt.json').is_file()
    marker=SMOKE/'native-process-launch-consumed'
    with marker.open('x') as handle:handle.write('One native invocation; do not retry or tune.\n')
    frozen=json.loads((SMOKE/'preflight.json').read_bytes())
    assert frozen['runner_sha256']==sha(SMOKE/'run_freqtrade_backtest.py')
    assert frozen['strategy_sha256']==sha(SMOKE/f'strategies/{STRATEGY}.py')
    assert frozen['source_provenance_sha256']==sha(SMOKE/'retained-data-provenance.json')
    def bounded(command,**kwargs):
        kwargs['timeout']=600
        result=subprocess.run(command,**kwargs)
        (SMOKE/'stdout.txt').write_text(result.stdout)
        (SMOKE/'stderr.txt').write_text(result.stderr)
        return result
    completed,summary,shape=rc._run_scenario(scenario='SEARCH',timerange=frozen['timerange'],fee=.0005,
        python=PYTHON,source=SMOKE/'native-source',source_tree_sha256=frozen['source_tree_sha256'],
        runner_script=SMOKE/'run_freqtrade_backtest.py',runner_sha256=frozen['runner_sha256'],
        sandbox_exec=Path('/usr/bin/sandbox-exec'),config_path=SMOKE/'config.json',data_dir=SMOKE/'data/binance',
        user_data_dir=SMOKE/'user-data',strategy_path=SMOKE/'strategies',strategy_file=SMOKE/f'strategies/{STRATEGY}.py',
        strategy_sha256=frozen['strategy_sha256'],strategy=STRATEGY,export_dir=SMOKE/'raw',
        market_snapshot=SMOKE/'market_snapshot.json',leverage_tiers=SMOKE/'isolated_tiers_snapshot.json',
        data_provenance=SMOKE/'retained-data-provenance.json',home=SMOKE/'home',command_runner=bounded,allow_zero_trades=True)
    write(SMOKE/'runner-summary.json',summary)
    artifact=rc._sanitize_raw_artifact(scenario='SEARCH',slug='engineering-only',raw_dir=SMOKE/'raw',
        runner_summary=summary,completed=completed,command_shape=shape,bundle_dir=SMOKE/'bundle',strategy=STRATEGY,
        strategy_source=(SMOKE/f'strategies/{STRATEGY}.py').read_bytes(),
        data_provenance=json.loads((SMOKE/'retained-data-provenance.json').read_bytes()),
        data_provenance_sha256=frozen['source_provenance_sha256'],expected_input_receipts=summary['input_receipts'],
        source_tree_sha256=frozen['source_tree_sha256'],implementation_receipts={
            'runner':receipt(SMOKE/'run_freqtrade_backtest.py'),'producer':receipt(REPO/'lab/research_candidate.py')},
        timerange=frozen['timerange'],network_policy='deny-by-default',allow_zero_trades=True,
        funding_data_dir=SMOKE/'data/binance')
    write(SMOKE/'acceptance.json',{'purpose':'TECHNICAL_ONLY_NOT_SEARCH','artifact':str(artifact),
        'native_runs':1,'network':'denied by native sandbox','native_report_unchanged':True})
    print('NATIVE_TECHNICAL_ARTIFACT_ACCEPTED_NO_RESEARCH_VERDICT')
