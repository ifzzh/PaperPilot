import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from paperpilot.database.db_manager import init_db_schema
from paperpilot.migrations.v0103_daily_assets import apply, inspect, rollback


class DailyAssetMigrationTests(unittest.TestCase):
    def test_apply_requeues_without_replacing_database_and_rollback_restores(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database = root / "paperpilot.db"
            init_db_schema(str(database))
            with sqlite3.connect(database) as connection:
                connection.execute(
                    """INSERT INTO daily_arxiv_candidates
                       (owner_id,arxiv_id,release_date,artifact_status,retry_count,
                        next_retry_at,updated_at)
                       VALUES (?,?,?,?,?,?,?)""",
                    ("owner", "2609.00001", "2026-09-09", "retry_wait", 3,
                     "2099-01-01T00:00:00+00:00", "2026-09-09T00:00:00+00:00"),
                )
            os.chmod(database, 0o660)
            inode = database.stat().st_ino
            self.assertEqual(inspect(database)["will_requeue"], 1)
            manifest = apply(database, root / "backups")
            self.assertEqual(database.stat().st_ino, inode)
            self.assertEqual(database.stat().st_mode & 0o777, 0o660)
            with sqlite3.connect(database) as connection:
                row = connection.execute(
                    "SELECT artifact_status,retry_count,next_retry_at FROM daily_arxiv_candidates"
                ).fetchone()
            self.assertEqual(row, ("queued", 3, None))
            rollback(database, manifest)
            self.assertEqual(database.stat().st_ino, inode)
            with sqlite3.connect(database) as connection:
                row = connection.execute(
                    "SELECT artifact_status,retry_count,next_retry_at FROM daily_arxiv_candidates"
                ).fetchone()
            self.assertEqual(row, ("retry_wait", 3, "2099-01-01T00:00:00+00:00"))


if __name__ == "__main__":
    unittest.main()
