"""Offline v0.9 migration from the single-user database and paper root."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import time
from pathlib import Path

from ipaper.database.models import SCHEMA_SCRIPT
from ipaper.database.db_manager import _ensure_translation_columns
from ipaper.security.credentials import SettingsCredentialCipher
from ipaper.security.paths import ensure_confined, user_storage_root


class TenantMigrationError(RuntimeError):
    pass


OWNED_TABLES = (
    "papers", "categories", "reading_history", "chats", "reading_list",
    "translation_jobs", "document_jobs",
)
LEGACY_COPIES = (
    ("user_settings", "user_settings_v2", ("key", "value")),
    ("daily_arxiv_tasks", "daily_arxiv_tasks_v2", ("date", "category", "status", "metadata")),
    ("institution_map", "institution_map_v2", ("original_name", "normalized_name")),
    ("daily_arxiv_reads", "daily_arxiv_reads_v2", ("arxiv_id", "read_at")),
)


def _columns(connection, table):
    return {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_manifest(path: Path, data: dict) -> None:
    """Durably replace a migration manifest without exposing partial JSON."""
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.chmod(temporary, 0o600)
    with temporary.open("rb") as stream:
        os.fsync(stream.fileno())
    temporary.replace(path)
    directory_fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _unfinished_manifests(papers_root: Path) -> list[Path]:
    directory = papers_root / ".paperpilot-migrations"
    if not directory.exists():
        return []
    unfinished = []
    for path in directory.glob("tenant-storage-*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise TenantMigrationError("tenant_migration_manifest_invalid") from exc
        if data.get("state") not in {"completed", "rolled_back", "rolled_back_after_error"}:
            unfinished.append(path)
    return unfinished


def inspect(db_path: Path, papers_root: Path, username: str) -> dict:
    if _unfinished_manifests(papers_root):
        raise TenantMigrationError("tenant_migration_interrupted")
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        user = connection.execute(
            "SELECT id FROM users WHERE username_normalized=? AND role='admin'",
            (username.strip().lower(),),
        ).fetchone()
        if user is None:
            raise TenantMigrationError("bootstrap_administrator_not_found")
        missing = [table for table in OWNED_TABLES if "owner_id" not in _columns(connection, table)]
        counts = {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in OWNED_TABLES
        }
    entries = []
    for child in papers_root.iterdir():
        if child.name in {".users", ".paperpilot-migrations"}:
            continue
        if child.is_symlink():
            raise TenantMigrationError("tenant_migration_symlink_forbidden")
        entries.append(child.name)
    return {"owner_id": user["id"], "missing_owner_columns": missing, "row_counts": counts, "moves": sorted(entries)}


def apply(db_path: Path, papers_root: Path, username: str, key_file: Path, backup_dir: Path) -> Path:
    report = inspect(db_path, papers_root, username)
    owner_id = report["owner_id"]
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    target_root = user_storage_root(papers_root, owner_id)
    moves = []
    for name in report["moves"]:
        source = ensure_confined(papers_root, papers_root / name, must_exist=True)
        target = ensure_confined(papers_root, target_root / name)
        if target.exists():
            raise TenantMigrationError("tenant_migration_target_conflict")
        moves.append({"source": name, "target": str(target.relative_to(papers_root))})

    # All preflight checks must finish before creating a backup, directory, or
    # migration marker. From this point onward the manifest is the recovery log.
    cipher = SettingsCredentialCipher.from_file(key_file)
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = backup_dir / f"ipaper-pre-v0.9-{stamp}.db"
    with sqlite3.connect(db_path) as source, sqlite3.connect(backup) as target:
        source.backup(target)
    os.chmod(backup, 0o600)

    manifest_dir = papers_root / ".paperpilot-migrations"
    manifest_dir.mkdir(exist_ok=True)
    manifest = manifest_dir / f"tenant-storage-{stamp}.json"
    manifest_data = {
        "version": 1,
        "state": "planned",
        "owner_id": owner_id,
        "backup": str(backup),
        "backup_sha256": _sha256(backup),
        "moves": moves,
        "completed_moves": [],
    }
    _write_manifest(manifest, manifest_data)

    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        # executescript may commit implicitly, so create additive v0.9 tables
        # before beginning the transaction that assigns legacy rows.
        _ensure_translation_columns(connection)
        connection.executescript(SCHEMA_SCRIPT)
        connection.execute("BEGIN EXCLUSIVE")
        for table in report["missing_owner_columns"]:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN owner_id TEXT")
        for table in OWNED_TABLES:
            connection.execute(
                f"UPDATE {table} SET owner_id=? WHERE owner_id IS NULL OR owner_id=''", (owner_id,)
            )
        for legacy, destination, columns in LEGACY_COPIES:
            names = ",".join(columns)
            placeholders = ",".join("?" for _ in columns)
            rows = connection.execute(f"SELECT {names} FROM {legacy}").fetchall()
            for row in rows:
                connection.execute(
                    f"INSERT OR IGNORE INTO {destination}(owner_id,{names}) VALUES (?,{placeholders})",
                    (owner_id, *(row[column] for column in columns)),
                )
        if "agentic_secrets" in {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}:
            for row in connection.execute("SELECT name,ciphertext,created_at,updated_at FROM agentic_secrets"):
                plaintext = cipher.decrypt(row["name"], row["ciphertext"])
                envelope = cipher.encrypt(row["name"], plaintext, owner_id=owner_id)
                connection.execute(
                    "INSERT OR REPLACE INTO agentic_secrets_v2(owner_id,name,ciphertext,created_at,updated_at) VALUES (?,?,?,?,?)",
                    (owner_id, row["name"], envelope, row["created_at"], row["updated_at"]),
                )
        old_prefix, new_prefix = str(papers_root), str(target_root)
        for column in ("file_path", "thumbnail_path"):
            connection.execute(
                f"UPDATE papers SET {column}=? || substr({column}, ?) WHERE owner_id=? AND {column} LIKE ?",
                (new_prefix, len(old_prefix) + 1, owner_id, old_prefix + "/%"),
            )
        connection.commit()

    manifest_data["state"] = "database_committed"
    _write_manifest(manifest, manifest_data)

    try:
        target_root.mkdir(parents=True, exist_ok=True)
        for move in moves:
            source, target = papers_root / move["source"], papers_root / move["target"]
            target.parent.mkdir(parents=True, exist_ok=True)
            source.rename(target)
            manifest_data["completed_moves"].append(move)
            manifest_data["state"] = "moving_files"
            _write_manifest(manifest, manifest_data)
    except OSError as exc:
        for move in reversed(manifest_data["completed_moves"]):
            (papers_root / move["target"]).rename(papers_root / move["source"])
        with sqlite3.connect(backup) as source, sqlite3.connect(db_path) as target:
            source.backup(target)
        manifest_data["state"] = "rolled_back_after_error"
        _write_manifest(manifest, manifest_data)
        raise TenantMigrationError("tenant_file_move_failed") from exc

    manifest_data["state"] = "completed"
    _write_manifest(manifest, manifest_data)
    return manifest


def rollback(db_path: Path, papers_root: Path, manifest_path: Path) -> None:
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    backup = Path(data["backup"])
    if _sha256(backup) != data["backup_sha256"]:
        raise TenantMigrationError("tenant_backup_hash_mismatch")
    # Inspect every planned move. A power loss can occur after rename(2) but
    # before the corresponding completed_moves update reaches disk.
    moves_to_restore = []
    for move in data.get("moves", []):
        source = papers_root / move["target"]
        target = papers_root / move["source"]
        if source.exists() and not target.exists():
            moves_to_restore.append(move)
        elif source.exists() == target.exists():
            raise TenantMigrationError("tenant_rollback_conflict")
    for move in reversed(moves_to_restore):
        source, target = papers_root / move["target"], papers_root / move["source"]
        source.rename(target)
    with sqlite3.connect(backup) as source, sqlite3.connect(db_path) as target:
        source.backup(target)
    data["state"] = "rolled_back"
    _write_manifest(manifest_path, data)


def assert_tenant_migrated(papers_root: str, db_path: str) -> None:
    root = Path(papers_root)
    if _unfinished_manifests(root):
        raise TenantMigrationError("tenant_migration_interrupted")
    with sqlite3.connect(db_path) as connection:
        admins = connection.execute(
            "SELECT id FROM users WHERE role='admin' AND status='active'"
        ).fetchall()
        if not admins:
            raise TenantMigrationError("bootstrap_administrator_not_found")
        for table in OWNED_TABLES:
            if "owner_id" not in _columns(connection, table):
                raise TenantMigrationError("tenant_migration_required")
            if connection.execute(
                f"SELECT 1 FROM {table} WHERE owner_id IS NULL OR owner_id='' LIMIT 1"
            ).fetchone():
                raise TenantMigrationError("tenant_migration_incomplete")
    legacy = [p for p in root.iterdir() if p.name not in {".users", ".paperpilot-migrations"}]
    if legacy:
        raise TenantMigrationError("tenant_storage_migration_required")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--papers-root", required=True)
    parser.add_argument("--owner", default="ifzzh")
    parser.add_argument("--key-file")
    parser.add_argument("--backup-dir")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--rollback")
    args = parser.parse_args(argv)
    db_path, papers_root = Path(args.db), Path(args.papers_root)
    if args.dry_run:
        print(json.dumps(inspect(db_path, papers_root, args.owner), indent=2))
    elif args.apply:
        if not args.key_file or not args.backup_dir:
            parser.error("--key-file and --backup-dir are required for --apply")
        print(apply(db_path, papers_root, args.owner, Path(args.key_file), Path(args.backup_dir)))
    else:
        rollback(db_path, papers_root, Path(args.rollback))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
