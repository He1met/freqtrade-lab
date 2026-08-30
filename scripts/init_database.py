#!/usr/bin/env python3
"""Initialize the freqtrade-lab SQLite database."""

import argparse
import sys
from contextlib import closing
from pathlib import Path
from typing import Optional, Sequence


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from lab.database import DEFAULT_DB_PATH, get_connection, get_schema_version, init_database


BUSINESS_TABLES = (
    "research_profiles",
    "generation_runs",
    "candidates",
    "research_runs",
    "backtest_executions",
    "releases",
)


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--path",
        type=Path,
        default=DEFAULT_DB_PATH,
        help="SQLite database path (default: workspace/lab.sqlite)",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    db_path = args.path.expanduser().resolve()
    init_database(db_path)

    placeholders = ", ".join("?" for _ in BUSINESS_TABLES)
    with closing(get_connection(db_path)) as connection:
        row = connection.execute(
            f"SELECT COUNT(*) FROM sqlite_master "
            f"WHERE type = 'table' AND name IN ({placeholders})",
            BUSINESS_TABLES,
        ).fetchone()
        table_count = int(row[0]) if row is not None else 0

    print("Database initialized")
    print(f"Path: {db_path}")
    print(f"Schema version: {get_schema_version(db_path)}")
    print(f"Tables: {table_count}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Database initialization failed: {exc}", file=sys.stderr)
        raise
