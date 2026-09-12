import os
import tempfile
import unittest
import uuid
from pathlib import Path

from flask import Flask

from ipaper.core.base_paper import Paper
from ipaper.core.paper_store import PaperStore
from ipaper.database import connection
from ipaper.database.dao.paper_dao import PaperDAO
from ipaper.database.dao.settings_dao import SettingsDAO
from ipaper.database.db_manager import init_db_schema
from ipaper.security.agentic_credentials import AgenticCredentialStore
from ipaper.security.identity import Identity, reset_background_identity, set_background_identity
from ipaper.security.paths import category_directory


class TestTenantIsolation(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "papers"
        self.root.mkdir()
        self.original_path = connection.DB_PATH
        connection.DB_PATH = str(Path(self.temp.name) / "ipaper.db")
        init_db_schema(connection.DB_PATH)
        self.app = Flask(__name__)
        self.context = self.app.app_context()
        self.context.push()
        self.user_a = str(uuid.uuid4())
        self.user_b = str(uuid.uuid4())
        key_file = Path(self.temp.name) / "key"
        key_file.write_bytes(os.urandom(32))
        self.credentials = AgenticCredentialStore.from_key_file(str(key_file))

    def tearDown(self):
        connection.close_db()
        self.context.pop()
        connection.DB_PATH = self.original_path
        self.temp.cleanup()

    def _as(self, user_id):
        return set_background_identity(Identity(user_id, user_id[:8], "user"))

    def test_database_cache_files_and_secrets_are_scoped(self):
        token = self._as(self.user_a)
        try:
            PaperDAO.save_paper({"id": "paper-a", "title": "private A"})
            SettingsDAO.save_setting("user_settings", {"theme": "a"})
            self.credentials.set("translate", "secret-a")
            directory_a = category_directory(self.root, "category", create=True)
            store = PaperStore()
            store.upsert(Paper(id="paper-a", title="private A"), category_id="category", category_path=[])
        finally:
            reset_background_identity(token)

        token = self._as(self.user_b)
        try:
            self.assertIsNone(PaperDAO.get_paper("paper-a"))
            self.assertEqual(SettingsDAO.get_setting("user_settings", {}), {})
            self.assertEqual(self.credentials.get("translate"), "")
            directory_b = category_directory(self.root, "category", create=True)
            self.assertNotEqual(directory_a, directory_b)
            self.assertIsNone(store.get("paper-a"))
        finally:
            reset_background_identity(token)

    def test_guessed_global_ids_cannot_overwrite_another_owner(self):
        token = self._as(self.user_a)
        try:
            PaperDAO.save_paper({"id": "shared-id", "title": "owner A"})
        finally:
            reset_background_identity(token)

        token = self._as(self.user_b)
        try:
            with self.assertRaises(PermissionError):
                PaperDAO.save_paper({"id": "shared-id", "title": "owner B"})
            self.assertIsNone(PaperDAO.get_paper("shared-id"))
        finally:
            reset_background_identity(token)

        token = self._as(self.user_a)
        try:
            self.assertEqual(PaperDAO.get_paper("shared-id")["title"], "owner A")
        finally:
            reset_background_identity(token)

if __name__ == "__main__":
    unittest.main()
