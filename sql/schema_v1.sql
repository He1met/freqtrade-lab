CREATE TABLE IF NOT EXISTS research_profiles (
    id TEXT PRIMARY KEY NOT NULL,
    name TEXT NOT NULL UNIQUE,
    domain TEXT NOT NULL CHECK (domain IN ('OKX_CRYPTO_PERP', 'OKX_STOCK_PERP')),
    exchange TEXT NOT NULL DEFAULT 'okx',
    trading_mode TEXT NOT NULL DEFAULT 'futures' CHECK (trading_mode = 'futures'),
    margin_mode TEXT NOT NULL DEFAULT 'isolated' CHECK (margin_mode IN ('isolated', 'cross')),
    pairs_json TEXT NOT NULL CHECK (json_valid(pairs_json) AND json_type(pairs_json) = 'array'),
    timeframe TEXT NOT NULL,
    detail_timeframe TEXT,
    history_start_date TEXT NOT NULL,
    smoke_days INTEGER NOT NULL CHECK (smoke_days > 0),
    holdout_days INTEGER NOT NULL CHECK (holdout_days > 0),
    starting_balance REAL NOT NULL CHECK (starting_balance > 0),
    stake_amount REAL CHECK (stake_amount IS NULL OR stake_amount > 0),
    max_open_trades INTEGER NOT NULL CHECK (max_open_trades > 0),
    taker_fee_rate REAL NOT NULL CHECK (taker_fee_rate >= 0),
    stress_fee_multiplier REAL NOT NULL CHECK (stress_fee_multiplier >= 1),
    max_drawdown_pct REAL NOT NULL CHECK (max_drawdown_pct > 0 AND max_drawdown_pct <= 100),
    min_development_trades INTEGER NOT NULL CHECK (min_development_trades >= 0),
    min_holdout_trades INTEGER NOT NULL CHECK (min_holdout_trades >= 0),
    min_profit_factor REAL NOT NULL CHECK (min_profit_factor >= 0),
    is_default INTEGER NOT NULL DEFAULT 0 CHECK (is_default IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS generation_runs (
    id TEXT PRIMARY KEY NOT NULL,
    research_profile_id TEXT NOT NULL,
    source TEXT NOT NULL CHECK (source IN ('DEEPSEEK', 'CODEX', 'MANUAL')),
    model TEXT,
    status TEXT NOT NULL CHECK (status IN ('RUNNING', 'COMPLETED', 'FAILED')),
    request_json TEXT NOT NULL CHECK (json_valid(request_json)),
    response_raw_text TEXT,
    response_json TEXT CHECK (response_json IS NULL OR json_valid(response_json)),
    returned_strategy_count INTEGER NOT NULL DEFAULT 0 CHECK (returned_strategy_count >= 0),
    parse_report_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(parse_report_json)),
    error_message TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (research_profile_id) REFERENCES research_profiles(id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS candidates (
    id TEXT PRIMARY KEY NOT NULL,
    generation_run_id TEXT NOT NULL,
    source_item_index INTEGER NOT NULL CHECK (source_item_index >= 0),
    parent_candidate_id TEXT,
    display_name TEXT NOT NULL,
    class_name TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    strategy_family TEXT,
    idea TEXT,
    expected_failure_mode TEXT,
    code_text TEXT NOT NULL CHECK (length(code_text) > 0),
    code_sha256 TEXT NOT NULL UNIQUE,
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata_json)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (generation_run_id, source_item_index),
    FOREIGN KEY (generation_run_id) REFERENCES generation_runs(id) ON DELETE RESTRICT,
    FOREIGN KEY (parent_candidate_id) REFERENCES candidates(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS research_runs (
    id TEXT PRIMARY KEY NOT NULL,
    candidate_id TEXT NOT NULL,
    research_profile_id TEXT NOT NULL,
    trigger_type TEXT NOT NULL CHECK (trigger_type IN ('AUTO', 'MANUAL', 'RETRY')),
    status TEXT NOT NULL CHECK (status IN ('PENDING', 'RUNNING', 'COMPLETED', 'FAILED', 'INTERRUPTED', 'CANCELLED')),
    stage TEXT NOT NULL CHECK (stage IN ('PENDING', 'CONTRACT', 'SECURITY', 'LOAD', 'SMOKE_BACKTEST', 'LOOKAHEAD', 'DEVELOPMENT_BACKTEST', 'HOLDOUT_BACKTEST', 'HOLDOUT_STRESS_BACKTEST', 'FINALIZE', 'COMPLETED')),
    verdict TEXT CHECK (verdict IS NULL OR verdict IN ('PASSED', 'REJECTED')),
    pipeline_version TEXT NOT NULL,
    freqtrade_version TEXT,
    input_snapshot_json TEXT NOT NULL CHECK (json_valid(input_snapshot_json)),
    checks_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(checks_json)),
    run_dir TEXT NOT NULL,
    rejection_reasons_json TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(rejection_reasons_json) AND json_type(rejection_reasons_json) = 'array'),
    error_stage TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    FOREIGN KEY (candidate_id) REFERENCES candidates(id) ON DELETE RESTRICT,
    FOREIGN KEY (research_profile_id) REFERENCES research_profiles(id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS backtest_executions (
    id TEXT PRIMARY KEY NOT NULL,
    research_run_id TEXT NOT NULL,
    scenario TEXT NOT NULL CHECK (scenario IN ('SMOKE', 'DEVELOPMENT', 'HOLDOUT', 'HOLDOUT_STRESS')),
    status TEXT NOT NULL CHECK (status IN ('PENDING', 'RUNNING', 'SUCCEEDED', 'FAILED', 'SKIPPED')),
    sequence INTEGER NOT NULL CHECK (sequence >= 1),
    timerange_start TEXT NOT NULL,
    timerange_end TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    detail_timeframe TEXT,
    fee_rate REAL NOT NULL CHECK (fee_rate >= 0),
    fee_multiplier REAL NOT NULL CHECK (fee_multiplier >= 1),
    command_json TEXT NOT NULL CHECK (json_valid(command_json)),
    config_path TEXT NOT NULL,
    strategy_path TEXT NOT NULL,
    result_archive_path TEXT,
    stdout_path TEXT,
    stderr_path TEXT,
    return_code INTEGER,
    total_trades INTEGER CHECK (total_trades IS NULL OR total_trades >= 0),
    profit_pct REAL,
    max_drawdown_pct REAL,
    win_rate REAL,
    profit_factor REAL,
    sharpe REAL,
    sortino REAL,
    calmar REAL,
    long_profit_pct REAL,
    short_profit_pct REAL,
    metrics_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metrics_json)),
    scenario_passed INTEGER CHECK (scenario_passed IS NULL OR scenario_passed IN (0, 1)),
    error_message TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    UNIQUE (research_run_id, scenario),
    UNIQUE (research_run_id, sequence),
    FOREIGN KEY (research_run_id) REFERENCES research_runs(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS releases (
    id TEXT PRIMARY KEY NOT NULL,
    research_run_id TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    release_dir TEXT NOT NULL UNIQUE,
    strategy_sha256 TEXT NOT NULL,
    config_sha256 TEXT NOT NULL,
    manifest_json TEXT NOT NULL CHECK (json_valid(manifest_json)),
    manifest_sha256 TEXT NOT NULL UNIQUE,
    freqtrade_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    archived_at TEXT,
    FOREIGN KEY (research_run_id) REFERENCES research_runs(id) ON DELETE RESTRICT
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_research_profiles_single_default
    ON research_profiles(is_default) WHERE is_default = 1;

CREATE INDEX IF NOT EXISTS ix_generation_runs_profile_created
    ON generation_runs(research_profile_id, created_at);
CREATE INDEX IF NOT EXISTS ix_generation_runs_source_created
    ON generation_runs(source, created_at);
CREATE INDEX IF NOT EXISTS ix_generation_runs_status_created
    ON generation_runs(status, created_at);

CREATE INDEX IF NOT EXISTS ix_candidates_generation_run
    ON candidates(generation_run_id);
CREATE INDEX IF NOT EXISTS ix_candidates_parent
    ON candidates(parent_candidate_id);
CREATE INDEX IF NOT EXISTS ix_candidates_created
    ON candidates(created_at);

CREATE INDEX IF NOT EXISTS ix_research_runs_candidate_created
    ON research_runs(candidate_id, created_at);
CREATE INDEX IF NOT EXISTS ix_research_runs_profile_created
    ON research_runs(research_profile_id, created_at);
CREATE INDEX IF NOT EXISTS ix_research_runs_status_created
    ON research_runs(status, created_at);
CREATE INDEX IF NOT EXISTS ix_research_runs_verdict_created
    ON research_runs(verdict, created_at);

CREATE INDEX IF NOT EXISTS ix_backtest_executions_status_created
    ON backtest_executions(status, created_at);

CREATE INDEX IF NOT EXISTS ix_releases_created
    ON releases(created_at);
CREATE INDEX IF NOT EXISTS ix_releases_archived
    ON releases(archived_at);

CREATE TRIGGER IF NOT EXISTS validate_release_before_insert
BEFORE INSERT ON releases
FOR EACH ROW
BEGIN
    SELECT CASE
        WHEN COALESCE(
            (SELECT status FROM research_runs WHERE id = NEW.research_run_id),
            ''
        ) <> 'COMPLETED'
        THEN RAISE(ABORT, 'Release requires a COMPLETED ResearchRun')
    END;

    SELECT CASE
        WHEN COALESCE(
            (SELECT verdict FROM research_runs WHERE id = NEW.research_run_id),
            ''
        ) <> 'PASSED'
        THEN RAISE(ABORT, 'Release requires a PASSED ResearchRun')
    END;

    SELECT CASE
        WHEN NEW.strategy_sha256 <> COALESCE(
            (
                SELECT candidates.code_sha256
                FROM research_runs
                JOIN candidates ON candidates.id = research_runs.candidate_id
                WHERE research_runs.id = NEW.research_run_id
            ),
            ''
        )
        THEN RAISE(ABORT, 'Release strategy_sha256 does not match Candidate code_sha256')
    END;
END;
