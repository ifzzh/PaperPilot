"""Offline v0.10.3 migration for the persistent Daily arXiv asset queue."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import stat
import time
from pathlib import Path

from paperpilot.database.db_manager import _ensure_daily_asset_columns


class DailyAssetMigrationError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, payload: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def inspect(db_path: Path) -> dict:
    if not db_path.is_file():
        raise DailyAssetMigrationError("database_not_found")
    with sqlite3.connect(db_path) as connection:
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise DailyAssetMigrationError("database_integrity_failed")
        columns = {row[1] for row in connection.execute(
            "PRAGMA table_info(daily_arxiv_candidates)"
        )}
        statuses = dict(connection.execute(
            "SELECT artifact_status,COUNT(*) FROM daily_arxiv_candidates GROUP BY artifact_status"
        ))
    return {
        "database": str(db_path),
        "schema_upgrade_required": "asset_job_id" not in columns,
        "status_counts": statuses,
        "will_requeue": sum(statuses.get(name, 0) for name in (
            "candidate", "queued", "downloading", "validating", "retry_wait"
        )),
    }


def _restore_content(source: Path, destination: Path) -> None:
    with source.open("rb") as reader, destination.open("r+b") as writer:
        writer.seek(0)
        writer.truncate()
        shutil.copyfileobj(reader, writer)
        writer.flush()
        os.fsync(writer.fileno())


def apply(db_path: Path, backup_dir: Path) -> Path:
    report = inspect(db_path)
    original = db_path.stat()
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = backup_dir / f"paperpilot-pre-v0.10.3-{stamp}.db"
    manifest = backup_dir / f"paperpilot-v0.10.3-{stamp}.manifest.json"
    with sqlite3.connect(db_path, timeout=0.2) as source:
        try:
            source.execute("BEGIN EXCLUSIVE")
        except sqlite3.OperationalError as exc:
            raise DailyAssetMigrationError("application_must_be_stopped") from exc
        source.rollback()
        with sqlite3.connect(backup) as target:
            source.backup(target)
    os.chmod(backup, 0o600)
    try:
        with sqlite3.connect(db_path) as connection:
            _ensure_daily_asset_columns(connection)
            connection.execute(
                """CREATE INDEX IF NOT EXISTS idx_daily_candidates_asset_queue
                   ON daily_arxiv_candidates(artifact_status,next_retry_at,updated_at)"""
            )
            now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            connection.execute(
                """UPDATE daily_arxiv_candidates
                   SET artifact_status='queued', next_retry_at=NULL,
                       asset_job_id=NULL, claimed_at=NULL,
                       artifact_error_code=CASE
                         WHEN artifact_status IN ('downloading','validating') THEN 'interrupted'
                         ELSE artifact_error_code END,
                       updated_at=?
                   WHERE artifact_status IN
                     ('candidate','queued','downloading','validating','retry_wait')""",
                (now,),
            )
            connection.commit()
            if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise DailyAssetMigrationError("database_integrity_failed")
    except Exception:
        _restore_content(backup, db_path)
        raise
    # The live bind mount depends on this inode and group-write mode.
    if db_path.stat().st_ino != original.st_ino:
        raise DailyAssetMigrationError("database_inode_changed")
    os.chmod(db_path, stat.S_IMODE(original.st_mode))
    try:
        os.chown(db_path, original.st_uid, original.st_gid)
    except PermissionError:
        if (db_path.stat().st_uid, db_path.stat().st_gid) != (original.st_uid, original.st_gid):
            raise DailyAssetMigrationError("database_ownership_changed")
    _write_json(manifest, {
        "version": "0.10.3",
        "state": "completed",
        "created_at": stamp,
        "database_backup": str(backup),
        "database_sha256": _sha256(backup),
        "database_inode": original.st_ino,
        "database_mode": oct(stat.S_IMODE(original.st_mode)),
        "report": report,
    })
    return manifest


def rollback(db_path: Path, manifest_path: Path) -> None:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("version") != "0.10.3" or manifest.get("state") != "completed":
        raise DailyAssetMigrationError("migration_manifest_invalid")
    backup = Path(manifest["database_backup"])
    if _sha256(backup) != manifest.get("database_sha256"):
        raise DailyAssetMigrationError("database_backup_hash_mismatch")
    inode = db_path.stat().st_ino
    _restore_content(backup, db_path)
    if db_path.stat().st_ino != inode:
        raise DailyAssetMigrationError("database_inode_changed")
    manifest["state"] = "rolled_back"
    _write_json(manifest_path, manifest)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--backup-dir")
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--dry-run", action="store_true")
    actions.add_argument("--apply", action="store_true")
    actions.add_argument("--rollback")
    args = parser.parse_args(argv)
    db_path = Path(args.db)
    if args.dry_run:
        print(json.dumps(inspect(db_path), ensure_ascii=False, indent=2))
    elif args.apply:
        if not args.backup_dir:
            parser.error("--backup-dir is required with --apply")
        print(apply(db_path, Path(args.backup_dir)))
    else:
        rollback(db_path, Path(args.rollback))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
