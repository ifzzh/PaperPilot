import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ipaper.database import connection
from ipaper.database.dao.document_job_dao import DocumentJobDAO
from ipaper.database.models import SCHEMA_SCRIPT


class DocumentJobPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp.name) / "ipaper.db")
        sqlite3.connect(self.db_path).executescript(SCHEMA_SCRIPT).close()
        connection.close_db()
        self.path_patch = patch.object(connection, "DB_PATH", self.db_path)
        self.path_patch.start()

    def tearDown(self):
        connection.close_db()
        self.path_patch.stop()
        self.temp.cleanup()

    def test_jobs_persist_without_paths_or_tokens(self):
        DocumentJobDAO.create("job", "metadata_zip")
        DocumentJobDAO.update("job", "running", progress=25)
        connection.close_db()
        restored = DocumentJobDAO.get("job")
        self.assertEqual(restored["status"], "running")
        self.assertNotIn("path", restored)
        self.assertNotIn("token", restored)


if __name__ == "__main__":
    unittest.main()
