"""Bounded funding security and real local HTTP tests; all evidence synthetic."""
import ast
import json
import threading
from types import SimpleNamespace

import pytest

from lab import codex_generation as generation, development_run, search_campaign
from lab.bounded_strategy import analyze_bounded_causal_strategy, BoundedStrategyError
from lab.database import get_connection
from lab.lagged_funding import FAMILY, FACTOR, funding_source, signal_contract
from tests.test_exploratory_session import EXPLORATION


def test_exact_fixed_template_and_single_factor():
    parent=SimpleNamespace(code_text=funding_source(),class_name='LaggedFundingR1')
    child=SimpleNamespace(code_text=funding_source('LaggedFundingR2',True),class_name='LaggedFundingR2')
    for item in (parent,child):
        analysis=analyze_bounded_causal_strategy(item.code_text,item.class_name)
        assert (analysis.startup_candle_count,analysis.max_lookback)==(289,289)
    assert search_campaign._single_factor_change(parent,child,FACTOR)
    assert not search_campaign._single_factor_change(parent,parent,FACTOR)
    assert not search_campaign._single_factor_change(child,parent,FACTOR)


def test_placeholder_like_class_names_do_not_change_either_template():
    from tests.test_bounded_strategy import _source, CLASS_NAME
    for name in ('FooEXTRA', 'CLASS_NAME', 'EXTRACLASS_NAME'):
        assert analyze_bounded_causal_strategy(funding_source(name),name).max_lookback==289
        ordinary=_source().replace(CLASS_NAME,name)
        analyze_bounded_causal_strategy(ordinary,name)


@pytest.mark.parametrize('old,new',[
    ('metadata["pair"]','"BTC/USDT:USDT"'), ('timeframe="1h"','timeframe="8h"'),
    ('self.dp.get_pair_dataframe','self.dp.funding_rate'), ('funding["open"]','funding["close"]'),
    ('rolling(3)','rolling(4)'), ('shift(288)','shift(-288)'), ('shift(288)','shift(287)'),
    ('115200','86400'), ('ffill=True','ffill=False'), ('% 8 == 0','% 4 == 0'),
    ('> 0.0001','> 0.0002'), (' & dataframe["funding_valid"]',''),
    (' & dataframe["time_valid"]',''), (' & dataframe["price_valid"]',''),
    ('hour == 8','hour == 9'), ('hour == 0','hour == 1'),
    ('startup_candle_count = 289','startup_candle_count = 288'),
    ('stoploss = -0.03','stoploss = -0.04'), ('minimal_roi = {}','minimal_roi = {"0": 0}'),
    ('return dataframe','return dataframe.bfill()'),
    ('from pandas import DataFrame','from pandas import DataFrame\nimport os'),
])
def test_no_template_or_guard_drift(old,new):
    source=funding_source('LaggedFundingR2',True)
    assert old in source
    mutated=source.replace(old,new)
    with pytest.raises(BoundedStrategyError):
        analyze_bounded_causal_strategy(mutated,'LaggedFundingR2')
    parent=SimpleNamespace(code_text=funding_source(),class_name='LaggedFundingR1')
    child=SimpleNamespace(code_text=mutated,class_name='LaggedFundingR2')
    assert not search_campaign._single_factor_change(parent,child,FACTOR)
    # Coordinated drift in both rounds cannot remove or redefine the shared guard.
    parent.code_text=parent.code_text.replace(old,new)
    assert not search_campaign._single_factor_change(parent,child,FACTOR)


def funding_database(tmp_path):
    from tests.test_codex_generation_http import _database,PROFILE_ID
    db=_database(tmp_path)
    with get_connection(db) as con:
        con.execute("UPDATE research_profiles SET pairs_json='[\"LINK/USDT:USDT\"]', history_start_date='2024-01-01', stake_amount=400, starting_balance=2000")
        con.commit()
    return db,PROFILE_ID


def create_synthetic_candidate(db,profile_id,*,parent=None,index=1):
    request=generation.validate_generation_request({'profile_id':profile_id,'idea':'SYNTHETIC fixed funding test','strategy_family':FAMILY,'parent_candidate_id':parent})
    when=f'2026-09-05T00:00:0{index}Z'
    prepared=generation.start_generation(db,f'funding-test-{index}',request,model='synthetic-test-only',started_at=when,exploration=EXPLORATION)
    name=f'LaggedFundingR{index}'
    raw=json.dumps({'display_name':'SYNTHETIC funding','class_name':name,'code_text':funding_source(name,index==2)}).encode()
    candidate=generation.complete_generation(db,prepared,generation.parse_candidate_output(raw,timeframe='5m'),raw_output=raw,jsonl_summary={'event_count':4,'tool_event_count':0},finished_at=when)
    generation.review_generation(db,prepared.generation_id,'APPROVED',decided_at=when)
    return candidate


@pytest.mark.parametrize('location',['request','metadata','both','family'])
def test_missing_signal_binding_cannot_downgrade_to_ordinary_candidate(tmp_path,location):
    db,profile_id=funding_database(tmp_path)
    candidate=create_synthetic_candidate(db,profile_id)
    with get_connection(db) as con:
        if location in {'request','both'}:
            con.execute("UPDATE generation_runs SET request_json=json_remove(request_json,'$.signal_contract')")
        if location in {'metadata','both'}:
            con.execute("UPDATE candidates SET metadata_json=json_remove(metadata_json,'$.provenance.signal_contract')")
        if location=='family':
            con.execute("UPDATE generation_runs SET request_json=json_remove(json_set(request_json,'$.input.strategy_family','ordinary'),'$.signal_contract')")
            con.execute("UPDATE candidates SET strategy_family='ordinary',metadata_json=json_remove(metadata_json,'$.provenance.signal_contract')")
        con.commit();con.execute('BEGIN')
        with pytest.raises(generation.GenerationContractError):
            generation.load_approved_candidate_snapshot(con,candidate)


def test_signal_requires_exploration_and_cannot_create_development(tmp_path):
    db,profile_id=funding_database(tmp_path)
    request=generation.validate_generation_request({'profile_id':profile_id,'idea':'Synthetic','strategy_family':FAMILY})
    with pytest.raises(generation.GenerationContractError,match='exploratory'):
        generation.start_generation(db,'bad',request,model='synthetic-test-only',started_at='2026-09-05T00:00:00Z')
    candidate=create_synthetic_candidate(db,profile_id)
    with get_connection(db) as con:
        con.execute('BEGIN')
        with pytest.raises(development_run.DevelopmentRunError,match='independent validation'):
            development_run._bound_candidate(con,candidate)
        assert all(con.execute(f'SELECT count(*) FROM {table}').fetchone()[0]==0 for table in ('research_runs','backtest_executions','releases'))


@pytest.mark.parametrize('fault',['missing','duplicate','unordered','wrong_grid','wrong_column','nan','null'])
def test_bad_original_funding_fails_actual_source_consumer(tmp_path,fault):
    from lab import bounded_research as pilot
    from tests.test_search_data_producer import _source_acquisition,_profile_prepare_kwargs
    pa=pytest.importorskip('pyarrow')
    feather=pytest.importorskip('pyarrow.feather')
    source,_,receipt_sha=_source_acquisition(tmp_path,exploration=EXPLORATION)
    kwargs=_profile_prepare_kwargs(tmp_path)
    kwargs.update(development_timerange=None,exploration=EXPLORATION)
    path=next((source/'data').rglob('*-funding_rate.feather'))
    table=feather.read_table(path)
    if fault=='missing': table=pa.concat_tables([table.slice(0,3),table.slice(4)])
    elif fault=='duplicate': table=pa.concat_tables([table.slice(0,3),table.slice(2)])
    elif fault=='unordered': table=table.take(pa.array([1,0,*range(2,table.num_rows)]))
    elif fault=='wrong_grid':
        from datetime import timedelta
        dates=table.column('date').to_pylist();dates[3]+=timedelta(minutes=1)
        table=table.set_column(0,table.schema.field('date'),pa.array(dates,type=table.schema.field('date').type))
    else:
        column='close' if fault=='wrong_column' else 'open'
        values=table.column(column).to_pylist()
        values[3]=.0001 if fault=='wrong_column' else float('nan') if fault=='nan' else None
        table=table.set_column(table.column_names.index(column),column,pa.array(values,type=pa.float64()))
    feather.write_feather(table,path)
    # Update the synthetic source SHA honestly, so rejection tests content/grid,
    # not merely a stale checksum. No consumer document is fabricated.
    provenance_path=source/'retained-data-provenance.json'
    provenance=json.loads(provenance_path.read_bytes())
    record=provenance['local_only_files'][path.relative_to(source).as_posix()]
    record.update(bytes=path.stat().st_size,sha256=pilot.digest(path.read_bytes()))
    provenance_path.write_bytes(pilot.canonical(provenance))
    db_sha=pilot.digest(kwargs['database_path'].read_bytes())
    output=tmp_path/'consumer'
    with pytest.raises(pilot.PilotError):
        pilot.prepare_search_data(source,output,pilot.digest(provenance_path.read_bytes()),receipt_sha,**kwargs)
    assert not output.exists() and not list(tmp_path.glob('.search-data-*'))
    assert pilot.digest(kwargs['database_path'].read_bytes())==db_sha


def test_t2_http_fixed_generation_parent_and_binding(tmp_path):
    from lab import research_console
    from tests.test_codex_generation_http import _fake_codex,_request,_wait_generation
    db,profile_id=funding_database(tmp_path)
    executable,marker=_fake_codex(tmp_path,'synthetic_funding')
    runtime=tmp_path/'runtime';runtime.mkdir()
    pilot=tmp_path/'pilot';pilot.mkdir()
    search=tmp_path/'search';search.mkdir()
    server=research_console.create_research_console_server(db,runtime,pilot,0,search_root=search,codex_binary=executable,exploration_contract=EXPLORATION)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    ids=[]
    try:
        for index in (1,2):
            payload={'profile_id':profile_id,'idea':'SYNTHETIC fixed funding test','strategy_family':FAMILY}
            if ids: payload['parent_candidate_id']=ids[0]
            status,created,_=_request(server,'/api/generations',method='POST',payload=payload)
            assert status==202,created
            status,finished,_=_wait_generation(server,created['id'])
            assert status==200 and finished['status']=='COMPLETED',finished
            status,approved,_=_request(server,f'/api/generations/{created["id"]}/actions',method='POST',payload={'action':'APPROVE'})
            assert status==200,approved
            with get_connection(db,read_only=True) as con:
                con.execute('BEGIN')
                row=con.execute('SELECT * FROM candidates WHERE generation_run_id=?',(created['id'],)).fetchone()
                ids.append(row['id'])
                snapshot=generation.load_approved_candidate_snapshot(con,row['id'])
                assert snapshot.exploration==EXPLORATION
                assert row['code_text']==funding_source(f'LaggedFundingR{index}',index==2)
                assert json.loads(row['metadata_json'])['provenance']['signal_contract']==signal_contract()
                assert analyze_bounded_causal_strategy(snapshot.code_text,snapshot.class_name).max_lookback==289
                if index==2:
                    parent=generation.load_approved_candidate_snapshot(con,ids[0])
                    assert search_campaign._single_factor_change(parent,snapshot,FACTOR)
        context=json.loads(json.loads(marker.read_text())['prompt'].split('BUSINESS_CONTEXT_JSON:\n')[1])
        assert context['signal_contract']==signal_contract()
        with get_connection(db,read_only=True) as con:
            assert all(con.execute(f'SELECT count(*) FROM {table}').fetchone()[0]==0 for table in ('research_runs','backtest_executions','releases'))
    finally:
        server.research_console_controller.shutdown();server.shutdown();server.server_close();thread.join(timeout=5)
