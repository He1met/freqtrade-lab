"""SQLite connection and schema initialization helpers."""

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Union


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = PROJECT_ROOT / "workspace" / "lab.sqlite"
SCHEMA_PATH = PROJECT_ROOT / "sql" / "schema_v1.sql"
SCHEMA_VERSION = 1

PathLike = Union[str, Path]


def get_connection(db_path: PathLike = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Return a new configured SQLite connection for ``db_path``."""
    path = Path(db_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(str(path))
    try:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
    except Exception:
        connection.close()
        raise
    return connection


def init_database(db_path: PathLike = DEFAULT_DB_PATH) -> Path:
    """Create schema version 1 atomically and return the database path."""
    path = Path(db_path).expanduser()
    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
    transaction_sql = (
        "BEGIN IMMEDIATE;\n"
        f"{schema_sql}\n"
        f"PRAGMA user_version = {SCHEMA_VERSION};\n"
        "COMMIT;"
    )

    with closing(get_connection(path)) as connection:
        try:
            connection.executescript(transaction_sql)
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise
    return path


def get_schema_version(db_path: PathLike = DEFAULT_DB_PATH) -> int:
    """Return the SQLite ``user_version`` value for ``db_path``."""
    with closing(get_connection(db_path)) as connection:
        row = connection.execute("PRAGMA user_version").fetchone()
        if row is None:
            raise RuntimeError("PRAGMA user_version returned no value")
        return int(row[0])
