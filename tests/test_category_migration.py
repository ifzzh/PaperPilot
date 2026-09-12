import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from ipaper.migrations.category_storage import (
    MigrationError,
    apply_migration,
    assert_storage_migrated,
    build_plan,
    rollback_migration,
)
from ipaper.security.paths import category_directory


class TestCategoryStorageMigration(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        base = Path(self.tempdir.name)
        self.root = base / "papers"
        self.root.mkdir()
        self.db = base / "ipaper.db"
        self.backups = base / "backups"
        with sqlite3.connect(self.db) as connection:
            connection.executescript(
                """
                CREATE TABLE categories (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, parent_id TEXT
                );
                CREATE TABLE papers (
                    id TEXT PRIMARY KEY, file_path TEXT,
                    thumbnail_path TEXT, metadata TEXT
                );
                INSERT INTO categories VALUES ('root', 'Root', NULL);
                INSERT INTO categories VALUES ('parent', 'Same', 'root');
                INSERT INTO categories VALUES ('child', 'Same', 'parent');
                """
            )

    def tearDown(self):
        self.tempdir.cleanup()

    def _seed_nested_paper(self):
        legacy = self.root / "Same" / "Same"
        legacy.mkdir(parents=True)
        pdf = legacy / "paper.pdf"
        pdf.write_bytes(b"pdf")
        (legacy / "paper.zh.dual.pdf").write_bytes(b"translated")
        result = legacy / "outputs" / "paper" / "vlm" / "result.md"
        result.parent.mkdir(parents=True)
        result.write_text("analysis", encoding="utf-8")
        with sqlite3.connect(self.db) as connection:
            connection.execute(
                "INSERT INTO papers VALUES (?, ?, ?, ?)",
                (
                    "paper-1",
                    str(pdf),
                    None,
                    json.dumps({"analysis_result_path": str(result)}),
                ),
            )

    def test_dry_run_is_read_only_and_flattens_nested_categories(self):
        self._seed_nested_paper()
        plan = build_plan(str(self.root), str(self.db))
        self.assertTrue((self.root / "Same" / "Same" / "paper.pdf").exists())
        self.assertEqual(len(plan["moves"]), 2)
        child_target = category_directory(self.root, "child")
        self.assertEqual(plan["updates"][0]["file_path"], str(child_target / "paper.pdf"))

    def test_apply_is_idempotent_and_rollback_restores_layout_and_database(self):
        self._seed_nested_paper()
        manifest = apply_migration(str(self.root), str(self.db), str(self.backups))
        child_target = category_directory(self.root, "child")
        self.assertTrue((child_target / "paper.pdf").is_file())
        self.assertEqual(build_plan(str(self.root), str(self.db)), {"moves": [], "updates": []})
        assert_storage_migrated(str(self.root), str(self.db))
        rollback_migration(str(manifest))
        legacy_pdf = self.root / "Same" / "Same" / "paper.pdf"
        self.assertTrue(legacy_pdf.is_file())
        with sqlite3.connect(self.db) as connection:
            stored = connection.execute(
                "SELECT file_path FROM papers WHERE id='paper-1'"
            ).fetchone()[0]
        self.assertEqual(stored, str(legacy_pdf))

    def test_conflicting_target_fails_without_changes(self):
        self._seed_nested_paper()
        category_directory(self.root, "child", create=True)
        with self.assertRaises(MigrationError):
            build_plan(str(self.root), str(self.db))
        self.assertTrue((self.root / "Same" / "Same" / "paper.pdf").exists())

    def test_symlink_in_legacy_tree_is_rejected(self):
        legacy = self.root / "Same"
        legacy.mkdir()
        outside = Path(self.tempdir.name) / "outside"
        outside.mkdir()
        (legacy / "escape").symlink_to(outside, target_is_directory=True)
        with self.assertRaises((MigrationError, ValueError)):
            build_plan(str(self.root), str(self.db))

    def test_incomplete_manifest_blocks_startup(self):
        manifests = self.root / ".paperpilot-migrations"
        manifests.mkdir()
        (manifests / "broken.json").write_text(
            json.dumps({"state": "applying"}), encoding="utf-8"
        )
        with self.assertRaises(MigrationError):
            assert_storage_migrated(str(self.root), str(self.db))


if __name__ == "__main__":
    unittest.main()
