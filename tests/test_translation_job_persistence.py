from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from paperpilot.database import connection
from paperpilot.database.dao.translation_job_dao import TranslationJobDAO
from paperpilot.database.models import SCHEMA_SCRIPT


class TranslationJobPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp.name) / "paperpilot.db")
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
        connection.close_db()

        restored = TranslationJobDAO.get("job-1")

        self.assertEqual(restored["paper_id"], "paper-1")
        self.assertEqual(restored["status"], "running")
        self.assertEqual(restored["progress"], 27)
        self.assertNotIn("api_key", restored)
        self.assertNotIn("base_url", restored)

    def test_only_unfinished_jobs_are_recovered(self):
        TranslationJobDAO.create("active", "paper-1")
        TranslationJobDAO.create("done", "paper-1")
        TranslationJobDAO.update("done", "completed", progress=100)

        self.assertEqual(
            [item["job_id"] for item in TranslationJobDAO.list_active()],
            ["active"],
        )


if __name__ == "__main__":
    unittest.main()
