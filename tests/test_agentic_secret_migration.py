import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from paperpilot.database.models import SCHEMA_SCRIPT
from paperpilot.migrations.agentic_secrets import (
    AgenticSecretMigrationError,
    apply_migration,
    inspect_database,
    rollback_migration,
    rotate_key,
)
from paperpilot.security.credentials import SettingsCredentialCipher, generate_settings_key


class AgenticSecretMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = self.root / "paperpilot.db"
        self.key = self.root / "settings.key"
        self.backups = self.root / "backups"
        generate_settings_key(self.key)
        connection = sqlite3.connect(self.db)
        connection.executescript(SCHEMA_SCRIPT)
        connection.execute(
            "INSERT INTO user_settings(key, value) VALUES (?, ?)",
            (
                "agentic_settings",
                json.dumps(
                    {
                        "llmConfigs": {
                            "translate": {"llmModel": "model", "llmApiKey": "translate-secret"},
                            "interpret": {"llmApiKey": "interpret-secret"},
                            "dailyArxiv": {"llmApiKey": ""},
                        },
                        "mineruApiToken": "mineru-secret",
                    }
                ),
            ),
        )
        connection.commit()
        connection.close()

    def tearDown(self):
        self.temp.cleanup()

    def test_dry_run_lists_names_without_values(self):
        plan = inspect_database(self.db)
        self.assertEqual(
            plan["plaintext_secret_names"], ["interpret", "mineru", "translate"]
        )
        self.assertNotIn("translate-secret", json.dumps(plan))

    def test_apply_encrypts_scrubs_and_rollback_restores(self):
        manifest = apply_migration(self.db, self.key, self.backups)
        active_bytes = self.db.read_bytes()
        self.assertNotIn(b"translate-secret", active_bytes)
        self.assertNotIn(b"mineru-secret", active_bytes)
        connection = sqlite3.connect(self.db)
        settings = json.loads(
            connection.execute(
                "SELECT value FROM user_settings WHERE key='agentic_settings'"
            ).fetchone()[0]
        )
        envelopes = dict(connection.execute("SELECT name, ciphertext FROM agentic_secrets"))
        connection.close()
        self.assertNotIn("llmApiKey", settings["llmConfigs"]["translate"])
        self.assertNotIn("mineruApiToken", settings)
        cipher = SettingsCredentialCipher.from_file(self.key)
        self.assertEqual(cipher.decrypt("translate", envelopes["translate"]), "translate-secret")
        manifest_data = manifest.read_text(encoding="utf-8")
        self.assertNotIn("translate-secret", manifest_data)

        rollback_migration(manifest)
        connection = sqlite3.connect(self.db)
        restored = connection.execute(
            "SELECT value FROM user_settings WHERE key='agentic_settings'"
        ).fetchone()[0]
        connection.close()
        self.assertIn("translate-secret", restored)

    def test_second_apply_is_idempotent(self):
        apply_migration(self.db, self.key, self.backups)
        second = apply_migration(self.db, self.key, self.backups)
        self.assertTrue(second.exists())
        self.assertFalse(inspect_database(self.db)["requires_migration"])

    def test_plaintext_and_ciphertext_conflict_fails_before_backup(self):
        connection = sqlite3.connect(self.db)
        connection.execute(
            "INSERT INTO agentic_secrets(name,ciphertext,created_at,updated_at) VALUES (?,?,?,?)",
            ("translate", "v1:invalid", "now", "now"),
        )
        connection.commit()
        connection.close()
        with self.assertRaisesRegex(
            AgenticSecretMigrationError, "plaintext_encrypted_secret_conflict"
        ):
            apply_migration(self.db, self.key, self.backups)
        self.assertFalse(self.backups.exists())

    def test_key_rotation_reencrypts_all_values(self):
        apply_migration(self.db, self.key, self.backups)
        new_key = self.root / "new.key"
        generate_settings_key(new_key)
        rotate_key(self.db, self.key, new_key, self.backups)
        connection = sqlite3.connect(self.db)
        envelope = connection.execute(
            "SELECT ciphertext FROM agentic_secrets WHERE name='mineru'"
        ).fetchone()[0]
        connection.close()
        self.assertEqual(
            SettingsCredentialCipher.from_file(new_key).decrypt("mineru", envelope),
            "mineru-secret",
        )
        with self.assertRaises(Exception):
            SettingsCredentialCipher.from_file(self.key).decrypt("mineru", envelope)


if __name__ == "__main__":
    unittest.main()
