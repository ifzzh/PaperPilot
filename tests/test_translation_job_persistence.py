from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ipaper.database import connection
from ipaper.database.dao.translation_job_dao import TranslationJobDAO
from ipaper.database.models import SCHEMA_SCRIPT


class TranslationJobPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp.name) / "ipaper.db")
        db = sqlite3.connect(self.db_path)
        db.executescript(SCHEMA_SCRIPT)
        db.execute("INSERT INTO papers (id, title) VALUES ('paper-1', 'Test')")
        db.commit()
        db.close()
        connection.close_db()
        self.path_patch = patch.object(connection, "DB_PATH", self.db_path)
        self.path_patch.start()

    def tearDown(self):
        connection.close_db()
        self.path_patch.stop()
        self.temp.cleanup()

    def test_job_state_survives_new_database_connection_without_credentials(self):
        TranslationJobDAO.create("job-1", "paper-1")
        TranslationJobDAO.update("job-1", "running", progress=27)
        TranslationJobDAO.append_event(
            "job-1", kind="progress", stage="translate", progress=27,
            stage_progress=40, stage_current=2, stage_total=5,
        )
        connection.close_db()

        restored = TranslationJobDAO.get("job-1")

        self.assertEqual(restored["paper_id"], "paper-1")
        self.assertEqual(restored["status"], "running")
        self.assertEqual(restored["progress"], 27)
        self.assertNotIn("api_key", restored)
        self.assertNotIn("base_url", restored)
        events = TranslationJobDAO.list_events(job_id="job-1")
        self.assertEqual([item["kind"] for item in events], ["status", "progress"])
        self.assertEqual(events[-1]["stage_current"], 2)

    def test_only_unfinished_jobs_are_recovered(self):
        TranslationJobDAO.create("active", "paper-1")
        TranslationJobDAO.create("done", "paper-1")
        TranslationJobDAO.update("done", "completed", progress=100)

        self.assertEqual(
            [item["job_id"] for item in TranslationJobDAO.list_active()],
            ["active"],
        )

    def test_jobs_and_events_are_tenant_scoped(self):
        TranslationJobDAO.create("owned", "paper-1", config_fingerprint="abc")
        self.assertEqual(TranslationJobDAO.get("owned")["config_fingerprint"], "abc")
        with patch("ipaper.database.dao.translation_job_dao.current_user_id", return_value="other"):
            self.assertIsNone(TranslationJobDAO.get("owned"))
            self.assertEqual(TranslationJobDAO.list_events(), [])


if __name__ == "__main__":
    unittest.main()
