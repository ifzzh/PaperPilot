import json
import os
import sqlite3
import tempfile
import unittest
import uuid
from pathlib import Path

from ipaper.migrations.tenant_storage import (
    TenantMigrationError,
    apply,
    assert_tenant_migrated,
    inspect,
    rollback,
)
from ipaper.security.credentials import SettingsCredentialCipher


LEGACY_SCHEMA = """
CREATE TABLE papers (
 id TEXT PRIMARY KEY,title TEXT,file_path TEXT,thumbnail_path TEXT,metadata TEXT
);
CREATE TABLE categories (id TEXT PRIMARY KEY,name TEXT NOT NULL,parent_id TEXT,display_name TEXT);
CREATE TABLE reading_history (id INTEGER PRIMARY KEY,date TEXT,paper_id TEXT,duration INTEGER,timestamp INTEGER);
CREATE TABLE chats (session_id TEXT PRIMARY KEY,paper_id TEXT,history TEXT,created_at TEXT,updated_at TEXT,title TEXT);
CREATE TABLE reading_list (paper_id TEXT PRIMARY KEY,added_at TEXT,status TEXT);
CREATE TABLE translation_jobs (job_id TEXT PRIMARY KEY,paper_id TEXT,status TEXT,progress INTEGER,created_at TEXT,updated_at TEXT,completed_at TEXT,error TEXT);
CREATE TABLE document_jobs (job_id TEXT PRIMARY KEY,kind TEXT,paper_id TEXT,status TEXT,progress INTEGER,created_at TEXT,updated_at TEXT,completed_at TEXT,error TEXT);
CREATE TABLE user_settings (key TEXT PRIMARY KEY,value TEXT);
CREATE TABLE daily_arxiv_tasks (date TEXT,category TEXT,status TEXT,metadata TEXT,PRIMARY KEY(date,category));
CREATE TABLE institution_map (original_name TEXT PRIMARY KEY,normalized_name TEXT);
CREATE TABLE daily_arxiv_reads (arxiv_id TEXT PRIMARY KEY,read_at INTEGER);
CREATE TABLE agentic_secrets (name TEXT PRIMARY KEY,ciphertext TEXT,created_at TEXT,updated_at TEXT);
"""


class TestTenantStorageMigration(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.db = self.base / "ipaper.db"
        self.root = self.base / "papers"
        self.root.mkdir()
        self.backups = self.base / "backups"
        self.key = self.base / "settings.key"
        self.key.write_bytes(os.urandom(32))
        self.owner_id = str(uuid.uuid4())
        old_category = self.root / ".categories" / "legacy-category"
        old_category.mkdir(parents=True)
        (old_category / "paper.pdf").write_bytes(b"%PDF-1.4\n%%EOF")
        with sqlite3.connect(self.db) as connection:
            connection.executescript(LEGACY_SCHEMA)
            now = 1_700_000_000
            connection.execute(
                """CREATE TABLE users (
                    id TEXT PRIMARY KEY,username TEXT,username_normalized TEXT,
                    password_hash TEXT,role TEXT,status TEXT,must_change_password INTEGER,
                    created_at INTEGER,updated_at INTEGER,password_changed_at INTEGER)"""
            )
            connection.execute(
                "INSERT INTO users VALUES (?,?,?,?,?,?,?,?,?,NULL)",
                (self.owner_id, "ifzzh", "ifzzh", "hash", "admin", "active", 1, now, now),
            )
            pdf = str(old_category / "paper.pdf")
            connection.execute(
                "INSERT INTO papers(id,title,file_path,metadata) VALUES ('paper-1','Legacy',?, '{}')",
                (pdf,),
            )
            connection.execute(
                "INSERT INTO categories VALUES ('category-1','Legacy',NULL,NULL)"
            )
            connection.execute(
                "INSERT INTO user_settings VALUES ('user_settings','{\"theme\":\"dark\"}')"
            )
            cipher = SettingsCredentialCipher.from_file(self.key)
            connection.execute(
                "INSERT INTO agentic_secrets VALUES ('translate',?,'now','now')",
                (cipher.encrypt("translate", "legacy-secret"),),
            )

    def tearDown(self):
        self.temp.cleanup()

    def test_apply_assigns_rows_moves_files_and_rollback_restores_both(self):
        report = inspect(self.db, self.root, "ifzzh")
        self.assertIn("papers", report["missing_owner_columns"])
        self.assertEqual(report["moves"], [".categories"])

        manifest = apply(self.db, self.root, "ifzzh", self.key, self.backups)
        data = json.loads(manifest.read_text(encoding="utf-8"))
        self.assertEqual(data["state"], "completed")
        migrated_pdf = self.root / ".users" / self.owner_id / ".categories" / "legacy-category" / "paper.pdf"
        self.assertTrue(migrated_pdf.is_file())
        assert_tenant_migrated(str(self.root), str(self.db))
        with sqlite3.connect(self.db) as connection:
            owner, path = connection.execute(
                "SELECT owner_id,file_path FROM papers WHERE id='paper-1'"
            ).fetchone()
            self.assertEqual(owner, self.owner_id)
            self.assertEqual(path, str(migrated_pdf))
            self.assertEqual(
                connection.execute(
                    "SELECT value FROM user_settings_v2 WHERE owner_id=?",
                    (self.owner_id,),
                ).fetchone()[0],
                '{"theme":"dark"}',
            )

        rollback(self.db, self.root, manifest)
        self.assertTrue((self.root / ".categories" / "legacy-category" / "paper.pdf").is_file())
        with sqlite3.connect(self.db) as connection:
            self.assertNotIn(
                "owner_id",
                {row[1] for row in connection.execute("PRAGMA table_info(papers)")},
            )

    def test_unfinished_manifest_blocks_startup_and_new_apply(self):
        directory = self.root / ".paperpilot-migrations"
        directory.mkdir()
        (directory / "tenant-storage-interrupted.json").write_text(
            json.dumps({"version": 1, "state": "moving_files"}), encoding="utf-8"
        )
        with self.assertRaisesRegex(TenantMigrationError, "tenant_migration_interrupted"):
            inspect(self.db, self.root, "ifzzh")
        with self.assertRaisesRegex(TenantMigrationError, "tenant_migration_interrupted"):
            assert_tenant_migrated(str(self.root), str(self.db))


if __name__ == "__main__":
    unittest.main()
