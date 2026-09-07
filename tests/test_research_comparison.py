"""Invented 2030 reports/marks only. No Freqtrade execution or acquisition."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import sys
import threading
from types import SimpleNamespace
import zipfile

import pandas as pd
import pytest

from lab import research_comparison as rc, codex_generation as cg
from lab.backtest_artifact import SUPPORTED_FREQTRADE_COMMIT
from lab.database import get_connection
from lab.futures_costs import audit_native_trades, binance_identity, source_identity
from tests.test_codex_generation import _database_with_profile
from tests.test_search_console_http import _add_candidate
from tests.test_prefilter_evidence import state
from tests.test_search_protocol_rejection import evidence

DAY = 86_400_000
BENCHMARK_SOURCE = '''from pandas import DataFrame, Timestamp
from freqtrade.strategy import IStrategy

class SyntheticBuyHold(IStrategy):
    INTERFACE_VERSION = 3
    timeframe = "1d"
    can_short = False
    startup_candle_count = 14
    process_only_new_candles = True
    minimal_roi = {}
    stoploss = -1.0

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        first_signal = Timestamp(self.config["timerange"].split("-")[0], tz="UTC")
        dataframe.loc[dataframe["date"] == first_signal, "enter_long"] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["exit_long"] = 0
        return dataframe
'''


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode())
    return {'path': str(path), 'sha256': rc.digest(path.read_bytes())}


def artifact(root, role, source, code, name, window, fee, marks, events, mark_sha, stage):
    """Write a synthetic native-format report; production parser stays real."""
    root.mkdir(parents=True)
    begin, end = [datetime.strptime(t, '%Y%m%d').replace(tzinfo=timezone.utc) for t in window.split('-')]
    opened, closed = begin + timedelta(days=1), end - timedelta(days=1)
    profit = -500 * fee
    trade = dict(pair='XRP/USDT:USDT', open_date=opened.isoformat(), close_date=closed.isoformat(),
                 open_rate=100, close_rate=100, amount=2.5, stake_amount=250, leverage=1,
                 is_short=False, funding_fees=0, fee_open=fee, fee_close=fee, profit_abs=profit,
                 trade_duration=(closed-opened).total_seconds()/60, exit_reason='force_exit',
                 stop_loss_abs=0, initial_stop_loss_abs=0)
    report = dict(strategy_name=name, timeframe='1d', timeframe_detail=None, timerange=window,
                  backtest_start=begin.isoformat(), backtest_end=closed.isoformat(),
                  backtest_start_ts=int(begin.timestamp()*1000), backtest_end_ts=int(closed.timestamp()*1000),
                  trading_mode='futures', margin_mode='isolated', pairlist=['XRP/USDT:USDT'],
                  starting_balance=1000, stake_amount=250, max_open_trades=1, total_trades=1,
                  wins=0, draws=0, losses=1, trades=[trade], profit_total=profit/1000,
                  max_drawdown_account=-profit/1000, winrate=0, profit_factor=0, sharpe=None,
                  sortino=None, calmar=None, profit_total_long=profit/1000, profit_total_short=0)
    config = dict(strategy=name, exchange=dict(name='binance', pair_whitelist=['XRP/USDT:USDT']),
                  timeframe='1d', timeframe_detail=None, timerange=window, trading_mode='futures',
                  margin_mode='isolated', fee=fee, dry_run_wallet=1000, stake_amount=250, max_open_trades=1)
    stem = 'backtest-result-synthetic'
    report_bytes = json.dumps({'strategy': {name: report}}).encode()
    members = {stem+'.json': report_bytes, stem+'_config.json': json.dumps(config).encode(),
               stem+'_'+name+'.py': code.encode()}
    archive = root/(stem+'.zip')
    with zipfile.ZipFile(archive, 'w') as z:
        for n, b in members.items(): z.writestr(n, b)
    raw = root/'raw.zip'; raw.write_bytes(archive.read_bytes())
    meta = put(root/(stem+'.meta.json'), {})
    contract = dict(strategy=name, exchange='binance', trading_mode='futures', margin_mode='isolated',
                    pairs=['XRP/USDT:USDT'], timeframe='1d', detail_timeframe=None, timerange=window,
                    backtest_start_utc=begin.strftime('%Y-%m-%dT%H:%M:%SZ'),
                    backtest_end_utc=closed.strftime('%Y-%m-%dT%H:%M:%SZ'), starting_balance=1000,
                    stake_amount=250, max_open_trades=1, fee=fee, report_total_trades=1, wins=0, draws=0, losses=1)
    audit = audit_native_trades([trade], events, marks, symbol='XRPUSDT',
                               start_ms=int(begin.timestamp()*1000), end_ms=int(end.timestamp()*1000), starting_balance=1000)
    audit.update(scoring_timerange=window, mark_data_sha256=mark_sha,
                 source_events_sha256=rc.digest(json.dumps(events,sort_keys=True,separators=(',', ':')).encode()))
    provenance = dict(schema='freqtrade-lab-fixture-provenance-v1',
        freqtrade=dict(version='2026.7', tag='2026.7', commit=SUPPORTED_FREQTRADE_COMMIT),
        acquisition=dict(host='fapi.binance.com', authentication='none', retained_data_provenance_sha256=source['sha256']),
        artifact=dict(archive=archive.name, archive_sha256=rc.digest(archive.read_bytes()),
                      raw_archive_sha256=rc.digest(raw.read_bytes()), metadata=Path(meta['path']).name,
                      metadata_sha256=meta['sha256'], members={n:rc.digest(b) for n,b in members.items()}),
        generation={'scenario':rc.STAGES[stage] or 'DEVELOPMENT'},
        contract=contract, fee_evidence=dict(kind='configured parser-fixture assumption', rate=fee,
            claim='not an observed or public Binance account fee rate'), funding_audit=audit)
    prov = put(root/(stem+'.provenance.json'), provenance)
    return dict(artifact_root=str(root), archive=archive.name, strategy=name, provenance_sha256=prov['sha256'],
                retained_source=source, raw_archive={'path':str(raw),'sha256':rc.digest(raw.read_bytes())})


@pytest.fixture
def comparison(tmp_path, monkeypatch):
    db = _database_with_profile(tmp_path)
    with get_connection(db) as c:
        c.execute("UPDATE research_profiles SET domain='BINANCE_CRYPTO_PERP',exchange='binance',pairs_json='[\"XRP/USDT:USDT\"]',timeframe='1d',stake_amount=250,holdout_days=7")
    cid = _add_candidate(db, 'profile-btc-5m', 'SyntheticWeekly', 'trend', timeframe='1d')
    with get_connection(db) as c:
        c.execute('BEGIN')
        snap = cg.load_approved_candidate_snapshot(c, cid)
        candidate = dict(c.execute('SELECT * FROM candidates WHERE id=?', (cid,)).fetchone())
    benchmark_code = BENCHMARK_SOURCE
    windows = dict(S='20300107-20300114', D='20300114-20300121', H='20300121-20300128', STRESS='20300121-20300128')
    protocol = dict(schema=rc.SCHEMA, strategy_sha256=snap.code_sha256,
        benchmark_sha256=rc.digest(benchmark_code.encode()), benchmark_class='SyntheticBuyHold',
        research_design='Entirely invented test; no economic evidence.',
        stages={k:dict(timerange=v,fee=0.001 if k=='STRESS' else 0.0005) for k,v in windows.items()})
    protocol_receipt = put(tmp_path/'protocol.json', protocol)
    documents = {}
    bound = dict(profile_snapshot=snap.profile, binding=dict(search_timerange=windows['S'], development_timerange=windows['D']),
                 protocol_review_identity={})
    for stage, window in windows.items():
        root = tmp_path/stage; root.mkdir()
        begin, end = [int(datetime.strptime(t,'%Y%m%d').replace(tzinfo=timezone.utc).timestamp()*1000) for t in window.split('-')]
        marks = [[t,100.,101.,99.,100.] for t in range(begin,end,3_600_000)]
        frame = pd.DataFrame(marks,columns=['date','open','high','low','close'])
        frame['date'] = pd.to_datetime(frame['date'],unit='ms',utc=True)
        mark_path=root/'marks.feather'; frame.to_feather(mark_path)
        mark_sha=rc.digest(mark_path.read_bytes())
        events=[dict(symbol='XRPUSDT',fundingTime=t,fundingRate='0',markPrice='100') for t in range(begin,end,28_800_000)]
        raw=put(root/'retrieval_receipt.json',dict(host='fapi.binance.com',authentication='none',pair='XRP/USDT:USDT'))
        source = dict(host='fapi.binance.com', authentication='none', exchange='binance', funding_model=rc.CONTRACT,
                      pair='XRP/USDT:USDT', instrument_id='XRPUSDT', pair_family='XRP-USDT')
        if stage in ('H','STRESS'):
            er=put(root/'funding-events.json',events);source['funding_events_receipt']={'sha256':er['sha256']}
        else: source['funding_events']=events
        phase=dict(source=source,files={'retrieval_receipt.json':{'sha256':raw['sha256']}},
                   local_only_files={'data/binance/futures/XRP_USDT_USDT-1h-mark.feather':{'sha256':mark_sha}})
        phase_receipt=put(root/('acquisition' if stage=='S' else '.')/'retained-data-provenance.json',phase)
        doc=dict(schema=rc.SCHEMA,candidate_id=cid,stage=stage,campaign_id='synthetic-campaign',
                 research_run_id=None if stage=='S' else 'synthetic-run',protocol=protocol_receipt,
                 raw_source=raw,stage_source=phase_receipt,marks={'path':str(mark_path),'sha256':mark_sha})
        for role,code,name in (('primary',candidate['code_text'],candidate['class_name']),('benchmark',benchmark_code,'SyntheticBuyHold')):
            derived=deepcopy(phase);derived['files']['strategies/'+name+'.py']={'sha256':rc.digest(code.encode())}
            sr=put(root/(role+'-source.json'),derived)
            output=tmp_path/'comparison-artifacts'/'S' if stage=='S' and role=='primary' else root/role
            side=artifact(output,role,sr,code,name,window,protocol['stages'][stage]['fee'],marks,events,mark_sha,stage)
            if stage=='S' and role=='primary':
                raw_path=root/'search-results-round-1'/cid/'raw'/'backtest-result-synthetic.zip'
                raw_path.parent.mkdir(parents=True);raw_path.write_bytes(Path(side['raw_archive']['path']).read_bytes())
                side['raw_archive']['path']=str(raw_path)
            side['attempt']=put(root/(role+'-attempt.json'),dict(schema=rc.SCHEMA,role=role,stage=stage,native_calls=1,
                return_code=0,archive_sha256=side['raw_archive']['sha256'],strategy_sha256=rc.digest(code.encode()),
                source_sha256=sr['sha256'],raw_source_sha256=raw['sha256']))
            doc[role]=side
        if stage != 'S':
            doc['stage_source']=doc['primary']['retained_source']
            doc['primary']['raw_archive']=None
        documents[stage]=doc
    bound['protocol_review_identity']['data_provenance_sha256']=documents['S']['stage_source']['sha256']
    bound['binding']['terminal_sha256']=put(tmp_path/'S'/'search-terminal.json',{'campaign_id':'synthetic-campaign','status':'SEARCH_FINALIST_FROZEN'})['sha256']
    frozen_documents=deepcopy(documents)
    def binding(_c, doc, _candidate):
        primary=frozen_documents[doc['stage']]['primary']
        current={**bound,'archive_relative':str(Path(frozen_documents['S']['primary']['raw_archive']['path']).relative_to(tmp_path/'S')),
                 'archive_path':str(Path(primary['artifact_root'])/primary['archive'])}
        return current, primary['raw_archive']['sha256'] if doc['stage']=='S' else None, (
            None if doc['stage']=='S' else dict(archive_sha256=rc.digest((Path(primary['artifact_root'])/primary['archive']).read_bytes()),provenance_sha256=primary['provenance_sha256']))
    # Isolate campaign construction here; the separate evidence test below runs
    # the unpatched real persisted-campaign binding and stage-before-file gates.
    monkeypatch.setattr(rc,'_binding',binding)
    def attach(stage='S'):
        receipt=put(tmp_path/'comparison.json',documents[stage])
        return rc.attach_comparison(db,receipt['path'],receipt['sha256'],search_root=tmp_path/'S',artifact_root=tmp_path/'comparison-artifacts')
    return SimpleNamespace(**locals())


def test_stage_roundtrip_strict_public_and_unchanged_history(comparison, monkeypatch, capsys):
    e=comparison; before=state(e.db)
    # Run the actual argparse CLI entrypoint with real parser/auditor/SQLite.
    from scripts import attach_research_comparison as cli
    receipt=put(e.tmp_path/'comparison.json',e.documents['S'])
    monkeypatch.setattr(sys,'argv',['attach','--database',str(e.db),'--manifest',receipt['path'],'--manifest-sha256',receipt['sha256'],'--search-root',str(e.tmp_path/'S'),'--artifact-root',str(e.tmp_path/'comparison-artifacts')])
    assert cli.main()==0
    first=json.loads(capsys.readouterr().out)
    frozen=state(e.db); assert e.attach()==first and state(e.db)==frozen
    for stage in ('D','H','STRESS'): assert e.attach(stage)['stage']==stage
    public=cg.load_generation(e.db,e.candidate['generation_run_id'])['candidate']
    assert set(public['cost_comparisons'])==set(rc.STAGES) and public['review_status']=='APPROVED'
    assert public['cost_comparisons']['STRESS']['primary']['net_pct'] < first['primary']['net_pct']
    after=state(e.db)
    assert all(before[t]==after[t] for t in before if t!='candidates')
    with get_connection(e.db) as c:
        new=dict(c.execute('SELECT * FROM candidates WHERE id=?',(e.cid,)).fetchone())
    meta=json.loads(new.pop('metadata_json'));meta.pop('cost_comparisons')
    old=dict(e.candidate);assert meta==json.loads(old.pop('metadata_json'))
    new.pop('updated_at');old.pop('updated_at');assert new==old
    from lab.research_console import create_research_console_server
    from tests.test_research_console import _request
    runtime=e.tmp_path/'runtime';runtime.mkdir();pilot=e.tmp_path/'pilot';pilot.mkdir()
    server=create_research_console_server(e.db,runtime,pilot,port=0)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        status,_,_,payload=_request(server,'/api/generations/'+e.candidate['generation_run_id'])
        assert status==200 and payload['candidate']['cost_comparisons']==public['cost_comparisons']
        status,_,script,_=_request(server,'/console.js')
        assert status==200 and '这是诊断比较，不是完整策略资格'.encode() in script
    finally:
        server.research_console_controller.shutdown();server.shutdown();server.server_close();thread.join(timeout=5)


@pytest.mark.parametrize('mutation',['receipt','source','local_file','raw','attempt','benchmark_stop','fee','audit','wrong_primary','conflict','null','infinite','mixed_run'])
def test_invalid_evidence_rolls_back(comparison,mutation):
    e=comparison;doc=e.documents['S']
    if mutation in ('conflict','null','infinite','mixed_run'): e.attach()
    before=state(e.db)
    if mutation=='receipt': doc['marks']['sha256']='0'*64
    elif mutation=='source': doc['benchmark']['retained_source']=doc['raw_source']
    elif mutation=='local_file':
        path=Path(doc['benchmark']['retained_source']['path']);v=json.loads(path.read_bytes());v['local_only_files']={}
        doc['benchmark']['retained_source']=put(path,v)
        ap=Path(doc['benchmark']['attempt']['path']);a=json.loads(ap.read_bytes());a['source_sha256']=doc['benchmark']['retained_source']['sha256'];doc['benchmark']['attempt']=put(ap,a)
    elif mutation=='raw': Path(doc['primary']['raw_archive']['path']).write_bytes(b'changed')
    elif mutation=='attempt':
        path=Path(doc['benchmark']['attempt']['path']);v=json.loads(path.read_bytes());v['native_calls']=True;doc['benchmark']['attempt']=put(path,v)
    elif mutation in ('fee','audit','benchmark_stop'):
        side=doc['benchmark'];path=Path(side['artifact_root'])/'backtest-result-synthetic.provenance.json';v=json.loads(path.read_bytes())
        if mutation=='fee':v['contract']['fee']=0.2
        elif mutation=='audit':v['funding_audit']['mark_data_sha256']='0'*64
        else:v['contract']['strategy']='DifferentBenchmark'
        side['provenance_sha256']=put(path,v)['sha256']
    elif mutation=='wrong_primary': doc['primary'],doc['benchmark']=doc['benchmark'],doc['primary']
    elif mutation=='conflict': doc['campaign_id']='other-campaign'
    elif mutation=='mixed_run':e.documents['D']['research_run_id']='another-run'; e.attach('D');before=state(e.db)
    else:
        with get_connection(e.db) as c:
            meta=json.loads(c.execute('SELECT metadata_json FROM candidates WHERE id=?',(e.cid,)).fetchone()[0])
        meta['cost_comparisons']['S']['primary']['net_pct']=None if mutation=='null' else float('inf')
        with pytest.raises((rc.ComparisonError,ValueError)):
            rc.validate_comparisons(meta['cost_comparisons'],e.candidate)
        assert state(e.db)==before;return
    with pytest.raises(rc.ComparisonError):e.attach('H' if mutation=='mixed_run' else 'S')
    assert state(e.db)==before


def test_real_persisted_binding_blocks_unfinished_stage_before_files(evidence,monkeypatch):
    e=evidence
    doc=dict(campaign_id=e.campaign,stage='S',research_run_id=None,protocol={'sha256':e.identity['protocol_sha256']})
    with get_connection(e.env.database) as c:
        candidate=c.execute('SELECT * FROM candidates WHERE id=?',(e.cid,)).fetchone()
        result=rc._binding(c,doc,candidate)
        assert result[1]==e.identity['raw_artifact_sha256']
        doc.update(stage='H',research_run_id='missing')
        with pytest.raises(rc.ComparisonError,match='Run'):rc._binding(c,doc,candidate)
        c.execute("INSERT INTO research_runs (id,candidate_id,research_profile_id,trigger_type,status,stage,pipeline_version,input_snapshot_json,run_dir,created_at) VALUES ('run',?,?,'MANUAL','PENDING','PENDING','synthetic',?,'synthetic','2030-01-01')",
                  (e.cid,e.env.profile_id,json.dumps({'search_finalist_binding':e.binding})))
        doc['research_run_id']='run'
        with pytest.raises(rc.ComparisonError,match='completed scenario'):rc._binding(c,doc,candidate)
        c.execute("UPDATE research_runs SET input_snapshot_json='{}'")
        with pytest.raises(KeyError):rc._binding(c,doc,candidate)


def test_xrp_identity_transport_and_cli_failure(tmp_path):
    from lab.binance_source import bounded_url
    identity=binance_identity('XRP/USDT:USDT')
    assert identity['instrument_id']=='XRPUSDT' and identity['file_stem']=='XRP_USDT_USDT'
    assert 'symbol=XRPUSDT' in bounded_url('https://fapi.binance.com/fapi/v1/fundingRate?symbol=XRPUSDT&startTime=100','GET',100,200,pair=identity['pair'])
    with pytest.raises(ValueError):bounded_url('https://fapi.binance.com/fapi/v1/fundingRate?symbol=BNBUSDT&startTime=100','GET',100,200,pair=identity['pair'])
    with pytest.raises(ValueError):source_identity({'pair':identity['pair'],'instrument_id':'BCHUSDT'},identity['pair'])
    result=subprocess.run([sys.executable,str(Path(__file__).resolve().parents[1]/'scripts/attach_research_comparison.py'),
        '--database',str(tmp_path/'absent.sqlite'),'--manifest',str(tmp_path/'absent.json'),'--manifest-sha256','0'*64],capture_output=True,text=True)
    assert result.returncode==1 and json.loads(result.stderr)['error']=='invalid_cost_comparison'
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('stage',['S','D'])
@pytest.mark.parametrize('wrong',['source','artifact','window'])
def test_wrong_stage_rejected_before_protected_values(comparison,monkeypatch,wrong,stage):
    e=comparison;doc=e.documents[stage];protected=e.documents['H']
    if wrong=='source':doc['stage_source']=protected['stage_source']
    elif wrong=='artifact':doc['primary']['artifact_root']=protected['primary']['artifact_root']
    else:
        # A dishonest proposed protocol is rejected on the actual D artifact
        # window even with the campaign layer isolated in this test.
        p=deepcopy(e.protocol);p['stages']['D']['timerange']=e.windows['H']
        doc['protocol']=put(e.tmp_path/'wrong-protocol.json',p)
    real_read=rc.safe_read
    def guarded(path,*args):
        p=Path(path)
        if p in {Path(doc['stage_source']['path']),Path(protected['marks']['path']),
                 Path(e.tmp_path/'H'/'funding-events.json'),
                 Path(protected['primary']['artifact_root'])/protected['primary']['archive'],
                 (Path(protected['primary']['artifact_root'])/protected['primary']['archive']).with_suffix('.provenance.json')}:
            pytest.fail('must reject before opening protected phase values')
        return real_read(path,*args)
    monkeypatch.setattr(rc,'safe_read',guarded)
    before=state(e.db)
    with pytest.raises(rc.ComparisonError):e.attach(stage)
    assert state(e.db)==before


def test_descriptor_reader_rejects_parent_symlink(tmp_path):
    actual=tmp_path/'actual';actual.mkdir();put(actual/'value.json',{})
    alias=tmp_path/'alias';alias.symlink_to(actual,target_is_directory=True)
    with pytest.raises(ValueError):rc.read_receipt({'path':str(alias/'value.json'),'sha256':rc.digest((actual/'value.json').read_bytes())})


def test_benchmark_source_runner_boundary_and_real_sanitizer(comparison):
    """Only the native process is represented by an invented saved ZIP.

    Runner input verification, source derivation, producer sanitizer and parser
    are real; no call to Backtesting, no Candidate for the diagnostic strategy.
    """
    from lab import research_candidate as producer
    from scripts import run_freqtrade_backtest as runner
    e=comparison;doc=e.documents['S'];side=doc['benchmark']
    root=e.tmp_path/'benchmark-entrypoint';root.mkdir()
    strategies=root/'strategies';strategies.mkdir()
    strategy=strategies/'SyntheticBuyHold.py';strategy.write_text(BENCHMARK_SOURCE)
    original=rc.read_receipt(doc['stage_source']);before=json.dumps(original,sort_keys=True)
    derived=deepcopy(original)
    derived.update(portable_retained_fixture=True, contract={'strategy':'strategies/SyntheticBuyHold.py'})
    derived['files']['strategies/SyntheticBuyHold.py']={'bytes':len(strategy.read_bytes()),'sha256':rc.digest(strategy.read_bytes())}
    receipt=put(root/'retained-data-provenance.json',derived)
    assert runner._verify_strategy_input(strategies,strategy,rc.digest(strategy.read_bytes()),derived)==rc.digest(strategy.read_bytes())
    assert producer._validate_strategy(strategy,strategies,'SyntheticBuyHold')==strategy.read_bytes()
    assert json.dumps(rc.read_receipt(doc['stage_source']),sort_keys=True)==before
    data=root/'data'/'binance';(data/'futures').mkdir(parents=True)
    mark=data/'futures'/'XRP_USDT_USDT-1h-mark.feather';mark.write_bytes(Path(doc['marks']['path']).read_bytes())
    raw=root/'raw';raw.mkdir();stem='backtest-result-synthetic'
    (raw/(stem+'.zip')).write_bytes(Path(side['raw_archive']['path']).read_bytes())
    put(raw/(stem+'.meta.json'),{})
    core=dict(producer.SUPPORTED_OFFICIAL_CORE);core.pop('Okx');core['Binance']='freqtrade.exchange.binance'
    inputs={'data_sha256':{'futures/XRP_USDT_USDT-1h-mark.feather':doc['marks']['sha256']}}
    summary=dict(scenario='DEVELOPMENT',archive=stem+'.zip',metadata=stem+'.meta.json',total_trades=1,
        dependencies={'freqtrade':'2026.7',**producer.SUPPORTED_DEPENDENCIES},official_core=core,
        freqtrade_commit=SUPPORTED_FREQTRADE_COMMIT,source_tree_sha256='0'*64,runner_sha256='1'*64,
        data_provenance_sha256=receipt['sha256'],input_receipts=inputs,
        scenario_data_view=dict(exclusive_stop_utc='2030-01-14T00:00:00Z',files={n:{'rows':168,'sha256':v} for n,v in inputs['data_sha256'].items()}))
    output=root/'sanitized';output.mkdir()
    produced=producer._sanitize_raw_artifact(scenario='DEVELOPMENT',slug='diagnostic',raw_dir=raw,
        runner_summary=summary,completed=subprocess.CompletedProcess(['TEST_ONLY_SAVED_SYNTHETIC_ZIP'],0,'',''),
        command_shape=('TEST_ONLY_SAVED_SYNTHETIC_ZIP',),bundle_dir=output,strategy='SyntheticBuyHold',
        strategy_source=strategy.read_bytes(),data_provenance=derived,data_provenance_sha256=receipt['sha256'],
        expected_input_receipts=inputs,source_tree_sha256='0'*64,implementation_receipts={'runner':{'sha256':'1'*64}},
        timerange=e.windows['S'],network_policy='no process execution; invented ZIP only',funding_data_dir=data)
    parsed=rc.parse_backtest_artifact(output,produced.archive,'SyntheticBuyHold','2026.7',produced.provenance_sha256)
    assert parsed.strategy_source==BENCHMARK_SOURCE and parsed.total_trades==1 and parsed.funding_audit['cash_executable']
