import sqlite3

from .models import SCHEMA_SCRIPT


_TRANSLATION_COLUMNS = {
    "error_code": "TEXT",
    "stage": "TEXT",
    "stage_progress": "INTEGER NOT NULL DEFAULT 0",
    "stage_current": "INTEGER NOT NULL DEFAULT 0",
    "stage_total": "INTEGER NOT NULL DEFAULT 0",
    "attempt_count": "INTEGER NOT NULL DEFAULT 0",
    "heartbeat_at": "TEXT",
    "queue_order": "INTEGER NOT NULL DEFAULT 0",
    "config_fingerprint": "TEXT",
    "recoverable_until": "TEXT",
}


def _ensure_translation_columns(connection: sqlite3.Connection) -> None:
    existing = {
        row[1] for row in connection.execute("PRAGMA table_info(translation_jobs)")
    }
    for name, declaration in _TRANSLATION_COLUMNS.items():
        if name not in existing:
            connection.execute(
                f"ALTER TABLE translation_jobs ADD COLUMN {name} {declaration}"
            )


def init_db_schema(db_path: str = "db/paperpilot.db") -> None:
    """Initialize and verify the SQLite schema before serving requests."""
    with sqlite3.connect(db_path) as connection:
        connection.executescript(SCHEMA_SCRIPT)
        _ensure_translation_columns(connection)
        connection.execute(
            """CREATE INDEX IF NOT EXISTS idx_translation_jobs_queue
               ON translation_jobs(status, queue_order, created_at)"""
        )
        result = connection.execute("PRAGMA integrity_check").fetchone()
        if not result or result[0] != "ok":
            raise sqlite3.DatabaseError("database integrity check failed")
