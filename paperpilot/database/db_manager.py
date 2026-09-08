import sqlite3

from .models import SCHEMA_SCRIPT


def init_db_schema(db_path: str = "db/paperpilot.db") -> None:
    """Initialize and verify the SQLite schema before serving requests."""
    with sqlite3.connect(db_path) as connection:
        connection.executescript(SCHEMA_SCRIPT)
        result = connection.execute("PRAGMA integrity_check").fetchone()
        if not result or result[0] != "ok":
            raise sqlite3.DatabaseError("database integrity check failed")
