"""Offline migration and key lifecycle for encrypted agentic credentials."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from paperpilot.security.credentials import (
    ALLOWED_SECRET_NAMES,
    SettingsCredentialCipher,
    generate_settings_key,
)


SECRET_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS agentic_secrets (
    name TEXT PRIMARY KEY,
    ciphertext TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK (name IN ('translate', 'interpret', 'dailyArxiv', 'mineru'))
)
"""


class AgenticSecretMigrationError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_settings(connection: sqlite3.Connection) -> dict[str, Any]:
    try:
        row = connection.execute(
            "SELECT value FROM user_settings WHERE key = 'agentic_settings'"
        ).fetchone()
    except sqlite3.Error as exc:
        raise AgenticSecretMigrationError("agentic_settings_table_unreadable") from exc
    if not row or not row[0]:
        return {}
    try:
        settings = json.loads(row[0])
    except (TypeError, json.JSONDecodeError) as exc:
        raise AgenticSecretMigrationError("agentic_settings_invalid_json") from exc
    if not isinstance(settings, dict):
        raise AgenticSecretMigrationError("agentic_settings_invalid_json")
    return settings


def _extract_plaintext(settings: dict[str, Any]) -> dict[str, str]:
    found: dict[str, str] = {}
    legacy = settings.get("llmApiKey")
    configs = settings.get("llmConfigs")
    for name in ("translate", "interpret", "dailyArxiv"):
        value: Any = None
        if isinstance(configs, dict) and isinstance(configs.get(name), dict):
            value = configs[name].get("llmApiKey")
        if not isinstance(value, str) or not value.strip():
            value = legacy
        if isinstance(value, str) and value.strip():
            found[name] = value.strip()
    mineru = settings.get("mineruApiToken")
    if isinstance(mineru, str) and mineru.strip():
        found["mineru"] = mineru.strip()
    return found


def _scrub_settings(settings: dict[str, Any]) -> dict[str, Any]:
    sanitized = json.loads(json.dumps(settings))
    sanitized.pop("llmApiKey", None)
    sanitized.pop("mineruApiToken", None)
    configs = sanitized.get("llmConfigs")
    if isinstance(configs, dict):
        for name in ("translate", "interpret", "dailyArxiv"):
            config = configs.get(name)
            if isinstance(config, dict):
                config.pop("llmApiKey", None)
    return sanitized


def inspect_database(db_path: str | os.PathLike[str]) -> dict[str, Any]:
    target = Path(db_path).resolve()
    if not target.is_file() or target.is_symlink():
        raise AgenticSecretMigrationError("database_not_regular_file")
    connection = sqlite3.connect(target)
    try:
        settings = _read_settings(connection)
        plaintext = _extract_plaintext(settings)
        encrypted_names: list[str] = []
        table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='agentic_secrets'"
        ).fetchone()
        if table:
            encrypted_names = [
                str(row[0])
                for row in connection.execute(
                    "SELECT name FROM agentic_secrets ORDER BY name"
                ).fetchall()
            ]
        overlap = sorted(set(plaintext) & set(encrypted_names))
        if overlap:
            raise AgenticSecretMigrationError("plaintext_encrypted_secret_conflict")
        return {
            "database": str(target),
            "plaintext_secret_names": sorted(plaintext),
            "encrypted_secret_names": encrypted_names,
            "requires_migration": bool(plaintext),
        }
    finally:
        connection.close()


def assert_no_plaintext_credentials(db_path: str | os.PathLike[str]) -> None:
    inspection = inspect_database(db_path)
    if inspection["requires_migration"]:
        raise AgenticSecretMigrationError("plaintext_agentic_credentials_require_migration")


def _assert_exclusive_access(db_path: Path) -> None:
    connection = sqlite3.connect(db_path, timeout=0)
    try:
        connection.execute("BEGIN EXCLUSIVE")
        connection.rollback()
    except sqlite3.OperationalError as exc:
        raise AgenticSecretMigrationError("database_is_in_use") from exc
    finally:
        connection.close()


def _backup_database(db_path: Path, backup_dir: Path) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(backup_dir, 0o700)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup_path = backup_dir / f"paperpilot-pre-agentic-secrets-{timestamp}.db"
    source = sqlite3.connect(db_path)
    backup = sqlite3.connect(backup_path)
    try:
        source.backup(backup)
    finally:
        backup.close()
        source.close()
    os.chmod(backup_path, 0o600)
    return backup_path


def _write_manifest(backup_path: Path, db_path: Path, names: list[str]) -> Path:
    manifest_path = backup_path.with_suffix(".manifest.json")
    payload = {
        "version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "database": str(db_path),
        "backup": str(backup_path),
        "backup_sha256": _sha256(backup_path),
        "migrated_secret_names": sorted(names),
    }
    descriptor = os.open(manifest_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(descriptor, json.dumps(payload, indent=2, sort_keys=True).encode("utf-8"))
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return manifest_path


def apply_migration(
    db_path: str | os.PathLike[str],
    key_file: str | os.PathLike[str],
    backup_dir: str | os.PathLike[str],
) -> Path:
    target = Path(db_path).resolve()
    inspection = inspect_database(target)
    cipher = SettingsCredentialCipher.from_file(key_file)
    _assert_exclusive_access(target)
    backup_path = _backup_database(target, Path(backup_dir).resolve())

    connection = sqlite3.connect(target)
    try:
        settings = _read_settings(connection)
        plaintext = _extract_plaintext(settings)
        connection.execute("PRAGMA secure_delete=ON")
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(SECRET_TABLE_SQL)
        now = datetime.now(timezone.utc).isoformat()
        for name, value in plaintext.items():
            connection.execute(
                """
                INSERT INTO agentic_secrets(name, ciphertext, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET ciphertext=excluded.ciphertext,
                    updated_at=excluded.updated_at
                """,
                (name, cipher.encrypt(name, value), now, now),
            )
        connection.execute(
            "INSERT OR REPLACE INTO user_settings(key, value) VALUES (?, ?)",
            ("agentic_settings", json.dumps(_scrub_settings(settings), ensure_ascii=False)),
        )
        connection.commit()
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        connection.execute("VACUUM")
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    return _write_manifest(
        backup_path,
        target,
        inspection["plaintext_secret_names"],
    )


def rollback_migration(manifest_file: str | os.PathLike[str]) -> Path:
    manifest_path = Path(manifest_file).resolve()
    if not manifest_path.is_file() or manifest_path.is_symlink():
        raise AgenticSecretMigrationError("manifest_not_regular_file")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        target = Path(manifest["database"]).resolve()
        backup = Path(manifest["backup"]).resolve()
        expected_hash = str(manifest["backup_sha256"])
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise AgenticSecretMigrationError("invalid_migration_manifest") from exc
    if not target.is_file() or target.is_symlink() or not backup.is_file() or backup.is_symlink():
        raise AgenticSecretMigrationError("migration_file_not_regular")
    if _sha256(backup) != expected_hash:
        raise AgenticSecretMigrationError("migration_backup_hash_mismatch")
    _assert_exclusive_access(target)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".paperpilot-rollback-", dir=target.parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        shutil.copy2(backup, temporary)
        os.chmod(temporary, 0o660)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def rotate_key(
    db_path: str | os.PathLike[str],
    old_key_file: str | os.PathLike[str],
    new_key_file: str | os.PathLike[str],
    backup_dir: str | os.PathLike[str],
) -> Path:
    target = Path(db_path).resolve()
    _assert_exclusive_access(target)
    old_cipher = SettingsCredentialCipher.from_file(old_key_file)
    new_cipher = SettingsCredentialCipher.from_file(new_key_file)
    backup_path = _backup_database(target, Path(backup_dir).resolve())
    connection = sqlite3.connect(target)
    try:
        rows = connection.execute(
            "SELECT name, ciphertext FROM agentic_secrets ORDER BY name"
        ).fetchall()
        plaintext = {
            str(name): old_cipher.decrypt(str(name), str(envelope))
            for name, envelope in rows
        }
        connection.execute("BEGIN IMMEDIATE")
        now = datetime.now(timezone.utc).isoformat()
        for name, value in plaintext.items():
            connection.execute(
                "UPDATE agentic_secrets SET ciphertext=?, updated_at=? WHERE name=?",
                (new_cipher.encrypt(name, value), now, name),
            )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    return _write_manifest(backup_path, target, sorted(plaintext))


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage encrypted PaperPilot agentic secrets")
    parser.add_argument("--db", default="db/paperpilot.db")
    parser.add_argument("--key-file")
    parser.add_argument("--backup-dir", default="db/backups")
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--dry-run", action="store_true")
    actions.add_argument("--apply", action="store_true")
    actions.add_argument("--rollback")
    actions.add_argument("--generate-key")
    actions.add_argument("--rotate-key")
    args = parser.parse_args()
    try:
        if args.generate_key:
            print(generate_settings_key(args.generate_key))
        elif args.rollback:
            print(rollback_migration(args.rollback))
        elif args.dry_run:
            print(json.dumps(inspect_database(args.db), indent=2, sort_keys=True))
        elif args.apply:
            if not args.key_file:
                parser.error("--key-file is required with --apply")
            print(apply_migration(args.db, args.key_file, args.backup_dir))
        elif args.rotate_key:
            if not args.key_file:
                parser.error("--key-file must point to the old key with --rotate-key")
            print(rotate_key(args.db, args.key_file, args.rotate_key, args.backup_dir))
    except (AgenticSecretMigrationError, OSError, sqlite3.Error, ValueError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
