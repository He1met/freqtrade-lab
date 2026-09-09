"""Read-only transaction binding of this approved candidate and Profile."""
import json
from contextlib import closing
from dataclasses import asdict
from lab import codex_generation as generation
from lab.database import get_connection

TABLES=('research_profiles','generation_runs','candidates','research_runs','backtest_executions','releases')


def logical_snapshot(database, profile_id, candidate_id):
    with closing(get_connection(database,read_only=True)) as connection:
        connection.execute('BEGIN')
        profile=generation.load_profile_snapshot(connection,profile_id)
        approved=generation.load_approved_candidate_snapshot(connection,candidate_id)
        candidate=dict(connection.execute('SELECT * FROM candidates WHERE id=?',(candidate_id,)).fetchone())
        gen=dict(connection.execute('SELECT * FROM generation_runs WHERE id=?',(approved.generation_run_id,)).fetchone())
        counts={t:connection.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in TABLES}
        assert approved.profile==profile
        result={'profile':profile,'approved_candidate':asdict(approved),'candidate_row':candidate,'generation_row':gen,'counts':counts}
        connection.rollback()
        return json.loads(json.dumps(result))
