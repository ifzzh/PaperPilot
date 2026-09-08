import json
import sqlite3

from paperpilot.database.db_manager import init_db_schema
from paperpilot.migrations.v010_workflows import apply, inspect, rollback


def test_v010_migration_updates_profile_preserves_jobs_and_rolls_back(tmp_path):
    database = tmp_path / "paperpilot.db"
    settings = tmp_path / "daily_arxiv_settings.json"
    backups = tmp_path / "backups"
    init_db_schema(str(database))
    settings.write_text(json.dumps({"categories": ["cs.CV"], "retentionDays": 2}), encoding="utf-8")
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO users (id,username,username_normalized,password_hash,role,status,must_change_password,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
            ("u1", "ifzzh", "ifzzh", "hash", "admin", "active", 0, 1, 1),
        )
        connection.commit()
        connection.execute("DROP TABLE translation_jobs")
        connection.execute(
            "CREATE TABLE translation_jobs (job_id TEXT PRIMARY KEY,paper_id TEXT NOT NULL,status TEXT NOT NULL,progress INTEGER NOT NULL DEFAULT 0,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,completed_at TEXT,error TEXT,owner_id TEXT)"
        )
        connection.commit()

    assert inspect(database, settings)["settings_will_change"] is True
    manifest = apply(database, settings, backups)
    migrated = json.loads(settings.read_text(encoding="utf-8"))
    assert migrated["maxDailyPapers"] == 24
    assert migrated["retentionDays"] == 7
    assert [topic["quota"] for topic in migrated["researchTopics"]] == [12, 8, 4]
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM daily_arxiv_topics").fetchone()[0] == 3
        columns = {row[1] for row in connection.execute("PRAGMA table_info(translation_jobs)")}
        assert {"queue_order", "stage", "worker_event_sequence"} <= columns

    rollback(database, settings, manifest)
    restored = json.loads(settings.read_text(encoding="utf-8"))
    assert restored == {"categories": ["cs.CV"], "retentionDays": 2}
