"""Exploratory contract binding and fixed clock surface; no market observations."""
import json
from dataclasses import replace

import pytest

from lab import bounded_research as pilot, codex_generation as generation, development_run, search_campaign
from lab.bounded_strategy import analyze_bounded_causal_strategy, BoundedStrategyError
from lab.database import get_connection
from tests.test_bounded_strategy import _source, CLASS_NAME
from tests.test_development_run import _approved_candidate_database, NOW


EXPLORATION = {
    "protocol": pilot.EXPLORATORY_PROTOCOL,
    "status": "NOT_INDEPENDENTLY_VALIDATED",
    "exposure_audit_sha256": "a" * 64,
    "prior_research": ["synthetic-test-reference"],
}


def session_source(class_name=CLASS_NAME, agreement=False):
    clock = 'dataframe["date"].dt.tz_convert("America/New_York").dt.'
    indicators = '\n'.join([
        f'dataframe["ny_hour"] = {clock}hour',
        f'dataframe["ny_minute"] = {clock}minute',
        f'dataframe["ny_weekday"] = {clock}dayofweek',
        'dataframe["morning"] = dataframe["close"].shift(66) / dataframe["open"].shift(71) - 1',
        'return dataframe',
    ])
    entry = []
    for signal, op in (("enter_long", ">"), ("enter_short", "<")):
        mask = f'(dataframe["ny_weekday"] < 5) & (dataframe["ny_hour"] == 15) & (dataframe["ny_minute"] == 25) & (dataframe["morning"] {op} 0) & (dataframe["volume"] > 0)'
        if agreement:
            mask = f'({mask}) & ((dataframe["close"] / dataframe["open"].shift(5) - 1) {op} 0)'
        entry.append(f'dataframe.loc[{mask}, "{signal}"] = 1')
    entry.append('return dataframe')
    exit_ = '\n'.join(f'dataframe.loc[(dataframe["ny_hour"] == 15) & (dataframe["ny_minute"] == 55), "{signal}"] = 1' for signal in ("exit_long", "exit_short")) + '\nreturn dataframe'
    return _source(indicators, '\n'.join(entry), exit_, startup_candle_count=72).replace(CLASS_NAME, class_name).replace('minimal_roi = {"0": 0.0}', 'minimal_roi = {}')


def test_clock_lookback_and_exact_r2():
    source = session_source()
    assert analyze_bounded_causal_strategy(source, CLASS_NAME).max_lookback == 72
    from types import SimpleNamespace
    parent = SimpleNamespace(code_text=source, class_name=CLASS_NAME)
    child = SimpleNamespace(code_text=session_source("SessionChild", True), class_name="SessionChild")
    assert search_campaign._single_factor_change(parent, child, search_campaign.SESSION_PRE_ENTRY_AGREEMENT_V1)
    for old, new in [('shift(5)', 'shift(6)'), ('stoploss = -0.02', 'stoploss = -0.03'), ('== 25', '== 20')]:
        mutated = SimpleNamespace(code_text=child.code_text.replace(old, new), class_name=child.class_name)
        assert not search_campaign._single_factor_change(parent, mutated, search_campaign.SESSION_PRE_ENTRY_AGREEMENT_V1)


def test_low_activity_factor_is_exact_and_preserves_every_other_setting():
    from types import SimpleNamespace
    indicator = 'dataframe["prior_volume_mean"] = dataframe["volume"].shift(1).rolling(72).mean()\nreturn dataframe'
    def source(filtered):
        entries = []
        for signal, operator in (("enter_long", ">"), ("enter_short", "<")):
            mask = f'(dataframe["close"] {operator} dataframe["open"]) & (dataframe["volume"] > 0)'
            if filtered:
                mask += ' & (dataframe["volume"] < dataframe["prior_volume_mean"] * 0.5)'
            entries.append(f'dataframe.loc[{mask}, "{signal}"] = 1')
        return _source(indicator, '\n'.join(entries + ['return dataframe']), startup_candle_count=73)
    parent = SimpleNamespace(code_text=source(False), class_name=CLASS_NAME)
    child = SimpleNamespace(code_text=source(True), class_name=CLASS_NAME)
    factor = search_campaign.ENTRY_LOW_ACTIVITY_FILTER_72_V1
    assert search_campaign._single_factor_change(parent, child, factor)
    for old, new in [(' * 0.5', ' * 0.6'), ('shift(1)', 'shift(2)'),
                     ('stoploss = -0.02', 'stoploss = -0.03'), ('startup_candle_count = 73', 'startup_candle_count = 74')]:
        assert not search_campaign._single_factor_change(parent, replace_source(child, old, new), factor)
    # Even coordinated parent/child drift cannot change the frozen prior-volume definition.
    assert not search_campaign._single_factor_change(
        replace_source(parent, 'rolling(72)', 'rolling(71)'),
        replace_source(child, 'rolling(72)', 'rolling(71)'), factor)
    assert not search_campaign._single_factor_change(parent, parent, factor)


def replace_source(snapshot, old, new):
    from types import SimpleNamespace
    return SimpleNamespace(code_text=snapshot.code_text.replace(old, new), class_name=snapshot.class_name)


@pytest.mark.parametrize('old,new', [
    ('America/New_York', 'UTC'), ('tz_convert', 'tz_localize'),
    ('.dt.hour', '.dt.date'), ('["date"].dt', '["close"].dt'),
    ('.dt.hour', '.dt.hour.values'), ('shift(71)', 'shift(-71)'),
    ('startup_candle_count = 72', 'startup_candle_count = 71'),
])
def test_clock_rejects_other_chains_and_future(old, new):
    with pytest.raises(BoundedStrategyError):
        analyze_bounded_causal_strategy(session_source().replace(old, new), CLASS_NAME)


def exploratory_candidate(tmp_path):
    db, prior_id = _approved_candidate_database(tmp_path)
    # This record must sort after the original fixture, independently of UUIDs.
    later = '2026-01-02T00:00:00.000Z'
    assert later > NOW
    with get_connection(db, read_only=True) as con:
        con.execute('BEGIN')
        prior = generation.load_approved_candidate_snapshot(con, prior_id)
    request = generation.validate_generation_request({'profile_id': prior.profile_id, 'idea': 'Synthetic session', 'strategy_family': 'session'})
    prepared = generation.start_generation(db, 'exploratory-generation', request, model='test', started_at=later, exploration=EXPLORATION)
    output = pilot.canonical({'class_name': CLASS_NAME, 'display_name': 'Session', 'code_text': session_source()})
    candidate_id = generation.complete_generation(db, prepared, generation.parse_candidate_output(output, timeframe='5m'), raw_output=output, jsonl_summary={'event_count':4, 'tool_event_count':0}, finished_at=later)
    generation.review_generation(db, prepared.generation_id, 'APPROVED', decided_at=later)
    return db, candidate_id


def test_exploratory_candidate_cannot_enter_development(tmp_path):
    db, candidate_id = exploratory_candidate(tmp_path)
    with get_connection(db) as con:
        con.execute('BEGIN')
        snapshot = generation.load_approved_candidate_snapshot(con, candidate_id)
        assert snapshot.exploration == EXPLORATION
        with pytest.raises(development_run.DevelopmentRunError, match='independent validation'):
            development_run._bound_candidate(con, candidate_id)
        assert [con.execute(f'SELECT count(*) FROM {table}').fetchone()[0] for table in ('research_runs','backtest_executions','releases')] == [0,0,0]
    public = generation.load_generation(db, 'exploratory-generation')
    assert public['research_mode'] == 'EXPLORATORY'
    assert generation.load_generation_context(db)['latest_generation_id'] == 'exploratory-generation'


@pytest.mark.parametrize('location', ['request', 'metadata', 'both'])
def test_missing_exploration_label_fails_binding(tmp_path, location):
    db, candidate_id = exploratory_candidate(tmp_path)
    with get_connection(db) as con:
        if location in {'request','both'}:
            con.execute("UPDATE generation_runs SET request_json=json_remove(request_json,'$.exploration') WHERE id='exploratory-generation'")
        if location in {'metadata','both'}:
            con.execute("UPDATE candidates SET metadata_json=json_remove(metadata_json,'$.provenance.exploration') WHERE id=?",(candidate_id,))
        con.commit(); con.execute('BEGIN')
        with pytest.raises(generation.GenerationContractError):
            generation.load_approved_candidate_snapshot(con, candidate_id)


def test_search_without_dev_requires_frozen_exploration(tmp_path):
    db, candidate_id = exploratory_candidate(tmp_path)
    with get_connection(db, read_only=True) as con:
        con.execute('BEGIN')
        snapshot = generation.load_approved_candidate_snapshot(con,candidate_id)
    contract = pilot.profile_search_contract(snapshot.profile,'20260201-20260301',None,72,exploration=EXPLORATION)
    assert contract['development_timerange'] is None
    assert contract['holdout'] == 'SEALED_UNREAD'
    for changes in ({'exploration':None},{'development_timerange':'20260301-20260401'}):
        with pytest.raises(pilot.PilotError):
            pilot.validate_profile_search_contract({**contract,**changes})
    del contract['exploration']
    with pytest.raises(pilot.PilotError):
        pilot.validate_profile_search_contract(contract)


def test_t2_exploratory_source_retains_only_search_and_rejects_label_drift(tmp_path):
    from tests.test_search_data_producer import _source_acquisition, _profile_prepare_kwargs
    source, provenance_sha, receipt_sha = _source_acquisition(tmp_path, exploration=EXPLORATION)
    kwargs = _profile_prepare_kwargs(tmp_path)
    kwargs.update(development_timerange=None, exploration=EXPLORATION)
    output = tmp_path / 'exploratory-search'
    pilot.prepare_search_data(source, output, provenance_sha, receipt_sha, **kwargs)
    snapshot = search_campaign._acquisition_snapshot(output, kwargs['database_path'])
    assert snapshot['development_timerange'] is None
    assert snapshot['exploration'] == EXPLORATION
    assert not (output / 'development').exists()
    provenance_path = output / 'acquisition' / 'retained-data-provenance.json'
    document = json.loads(provenance_path.read_text())
    del document['contract']['exploration']
    provenance_path.write_bytes(pilot.canonical(document))
    with pytest.raises(search_campaign.SearchCampaignError):
        search_campaign._acquisition_snapshot(output, kwargs['database_path'])


@pytest.mark.parametrize('case', ['valid', 'source-nonexploratory', 'target-nonexploratory',
    'source-sha', 'receipt-sha', 'pair', 'window', 'pre-roll', 'exposure', 'fee', 'gate', 'later-data'])
def test_shared_exploratory_source_has_a_closed_profile_whitelist(tmp_path, case):
    from tests.test_search_data_producer import _source_acquisition, _profile_prepare_kwargs
    source, provenance_sha, receipt_sha = _source_acquisition(
        tmp_path, exploration=None if case == 'source-nonexploratory' else EXPLORATION)
    kwargs = _profile_prepare_kwargs(tmp_path)
    kwargs.update(development_timerange=None, exploration=EXPLORATION)
    database = kwargs['database_path']
    with get_connection(database) as con:
        source_profile = dict(con.execute('SELECT * FROM research_profiles').fetchone())
        target = {**source_profile, 'id':'different-consumer', 'name':'Different consumer',
                  'stake_amount':200., 'min_development_trades':12, 'min_holdout_trades':12}
        if case == 'pair': target['pairs_json'] = '["ETH/USDT:USDT"]'
        if case == 'fee': target['taker_fee_rate'] = 0.001
        if case == 'gate': target['min_profit_factor'] = 1.2
        columns = ','.join(target)
        con.execute(f'INSERT INTO research_profiles ({columns}) VALUES ({",".join("?" for _ in target)})',tuple(target.values()))
        con.commit()
    kwargs['profile_id'] = target['id']
    if case == 'target-nonexploratory':
        kwargs.update(exploration=None, development_timerange='20260701-20260801')
    if case == 'source-sha': provenance_sha = '0'*64
    if case == 'receipt-sha': receipt_sha = '0'*64
    if case == 'window': kwargs['search_timerange'] = '20260602-20260701'
    if case == 'pre-roll': kwargs['pre_roll_candles'] -= 1
    if case == 'exposure': kwargs['exploration'] = {**EXPLORATION, 'exposure_audit_sha256':'c'*64}
    if case == 'later-data':
        import pyarrow as pa
        import pyarrow.feather as feather
        from datetime import datetime, timezone
        path = next((source/'data').rglob('*-5m-futures.feather'))
        table = feather.read_table(path)
        extra = table.slice(table.num_rows-1).set_column(0, table.schema.field(0),
            pa.array([datetime(2026,7,1,tzinfo=timezone.utc)],type=table.schema.field(0).type))
        feather.write_feather(pa.concat_tables([table,extra]),path)
    source_hashes = {str(path.relative_to(source)):pilot.digest(path.read_bytes())
                     for path in source.rglob('*') if path.is_file()}
    database_hash = pilot.digest(database.read_bytes())
    output = tmp_path/'consumer'
    if case == 'valid':
        pilot.prepare_search_data(source,output,provenance_sha,receipt_sha,**kwargs)
        public = search_campaign._acquisition_snapshot(output,database)
        assert public['profile_snapshot']['id'] == target['id']
        assert public['profile_snapshot']['stake_amount'] == 200.
        receipt = json.loads((output/'acquisition'/'retained-data-provenance.json').read_bytes())
        assert receipt['source_acquisition']['provenance_sha256'] == provenance_sha
        original = json.loads((source/'retained-data-provenance.json').read_bytes())
        assert original['contract']['profile_acquisition']['profile_snapshot']['id'] == source_profile['id']
        config = json.loads((output/'acquisition'/'config.json').read_bytes())
        assert config['stake_amount'] == 200.
    else:
        with pytest.raises(pilot.PilotError):
            pilot.prepare_search_data(source,output,provenance_sha,receipt_sha,**kwargs)
        assert not output.exists()
        assert not list(tmp_path.glob('.search-data-*'))
    assert pilot.digest(database.read_bytes()) == database_hash
    assert source_hashes == {str(path.relative_to(source)):pilot.digest(path.read_bytes())
                             for path in source.rglob('*') if path.is_file()}


def test_exploratory_plan_limits_and_no_finalist_handoff(tmp_path):
    db, candidate_id = exploratory_candidate(tmp_path)
    with get_connection(db, read_only=True) as con:
        con.execute('BEGIN')
        candidate = generation.load_approved_candidate_snapshot(con,candidate_id)
    capability = search_campaign.FrozenSearchCapability(
        status='READY', reason='Synthetic', profile_snapshot=candidate.profile,
        profile_snapshot_sha256=pilot.digest(pilot.canonical(candidate.profile)),
        search_timerange='20260201-20260301', development_timerange=None,
        pre_roll_candles=72, exploration=EXPLORATION, data_provenance_sha256='b'*64,
    )
    plan = search_campaign._search_plan(capability,'synthetic-campaign',1,
        [search_campaign._candidate_plan(candidate,'strategies/source.py',round_number=1,changed_factor=None,parent_sha256=None)],
        strategy_analyses={candidate_id:{'timeframe':'5m','startup_candle_count':72,'maximum_lookback':72}})
    pilot.validate_profile_search_plan(plan)
    assert plan['active_attempt_limit']==2
    assert capability.public()['research_mode']=='EXPLORATORY'
    with pytest.raises(search_campaign.SearchCampaignError, match='independent validation'):
        search_campaign.verified_finalist_binding(db,capability,candidate_id)
    with pytest.raises(pilot.PilotError):
        pilot.validate_profile_search_plan({**plan,'active_attempt_limit':3})
    with pytest.raises(pilot.PilotError):
        pilot.validate_profile_search_plan({**plan,'candidates':plan['candidates']*2})
    with pytest.raises(search_campaign.SearchCampaignError):
        search_campaign._profile_bound(candidate,replace(capability,exploration=None))


def test_t2_console_predata_generation_is_exploratory_and_dev_closed(tmp_path):
    from lab.research_console import create_research_console_server
    from tests.test_codex_generation_http import _database, _fake_codex, VALID_REQUEST
    db=_database(tmp_path); runtime=tmp_path/'runtime';runtime.mkdir();pilot_root=tmp_path/'pilot';pilot_root.mkdir()
    binary,_=_fake_codex(tmp_path,'valid')
    server=create_research_console_server(db,runtime,pilot_root,0,search_root=tmp_path/'not-yet-acquired',exploration_contract=EXPLORATION,codex_binary=binary)
    try:
        controller=server.research_console_controller
        assert controller._search_capability.public()['research_mode']=='EXPLORATORY'
        assert controller._development_capability.status=='EXPLORATORY_ONLY'
        assert controller._holdout_capability.status=='SEALED_UNREAD'
        result=controller.create_generation(generation.validate_generation_request(VALID_REQUEST))
        assert result['research_mode']=='EXPLORATORY'
    finally:
        server.research_console_controller.shutdown();server.server_close()
