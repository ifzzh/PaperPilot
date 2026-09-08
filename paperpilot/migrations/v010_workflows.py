"""Offline v0.10 migration for translation events and personalized Daily arXiv."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import time
from pathlib import Path

from paperpilot.database.models import SCHEMA_SCRIPT
from paperpilot.database.db_manager import _ensure_translation_columns
from paperpilot.tools.basic_tools.daily_arxiv_profile import DEFAULT_RESEARCH_TOPICS


class WorkflowMigrationError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def inspect(db_path: Path, settings_path: Path) -> dict:
    if not db_path.is_file():
        raise WorkflowMigrationError("database_not_found")
    with sqlite3.connect(db_path) as connection:
        result = connection.execute("PRAGMA integrity_check").fetchone()
        if not result or result[0] != "ok":
            raise WorkflowMigrationError("database_integrity_failed")
        daily_count = connection.execute(
            "SELECT COUNT(*) FROM papers WHERE is_daily=1"
        ).fetchone()[0]
        translation_count = connection.execute(
            "SELECT COUNT(*) FROM translation_jobs"
        ).fetchone()[0]
    settings = {}
    if settings_path.is_file():
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
    return {
        "database": str(db_path),
        "settings": str(settings_path),
        "daily_candidates": daily_count,
        "translation_jobs_preserved": translation_count,
        "settings_will_change": settings.get("topicFilteringEnabled") is not True,
    }


def _write_json(path: Path, data: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(path)


def _write_existing_settings(path: Path, data: dict) -> None:
    """Preserve the container-owned inode and its group-writable permissions."""
    if not path.exists():
        _write_json(path, data)
        return
    with path.open("w", encoding="utf-8") as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def _restore_existing_file(source: Path, destination: Path) -> None:
    """Restore content without replacing the deployment-owned inode or mode."""
    if destination.exists():
        with source.open("rb") as input_stream, destination.open("wb") as output_stream:
            shutil.copyfileobj(input_stream, output_stream)
            output_stream.flush()
            os.fsync(output_stream.fileno())
        return
    shutil.copyfile(source, destination)


def apply(db_path: Path, settings_path: Path, backup_dir: Path) -> Path:
    report = inspect(db_path, settings_path)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    backup_dir.mkdir(parents=True, exist_ok=True)
    db_backup = backup_dir / f"paperpilot-pre-v0.10-{stamp}.db"
    settings_backup = backup_dir / f"daily-arxiv-pre-v0.10-{stamp}.json"
    manifest = backup_dir / f"paperpilot-v0.10-{stamp}.manifest.json"

    with sqlite3.connect(db_path, timeout=0.2) as source:
        try:
            source.execute("BEGIN EXCLUSIVE")
        except sqlite3.OperationalError as exc:
            raise WorkflowMigrationError("application_must_be_stopped") from exc
        source.rollback()
        with sqlite3.connect(db_backup) as target:
            source.backup(target)
    os.chmod(db_backup, 0o600)
    if settings_path.is_file():
        shutil.copy2(settings_path, settings_backup)
        os.chmod(settings_backup, 0o600)

    data = json.loads(settings_path.read_text(encoding="utf-8")) if settings_path.is_file() else {}
    data.update({
        "categories": ["cs.RO", "cs.CV", "cs.AI", "cs.LG", "cs.DC", "cs.NI", "cs.OS", "cs.PF", "cs.CL"],
        "retentionDays": 7,
        "maxDailyPapers": 24,
        "researchTopics": DEFAULT_RESEARCH_TOPICS,
        "topicFilteringEnabled": True,
    })

    try:
        with sqlite3.connect(db_path) as connection:
            connection.row_factory = sqlite3.Row
            _ensure_translation_columns(connection)
            connection.executescript(SCHEMA_SCRIPT)
            now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            owners = [row[0] for row in connection.execute("SELECT id FROM users")]
            for owner_id in owners:
                connection.execute("DELETE FROM daily_arxiv_topics WHERE owner_id=?", (owner_id,))
                for topic in DEFAULT_RESEARCH_TOPICS:
                    connection.execute(
                        "INSERT INTO daily_arxiv_topics VALUES (?,?,?,?,?,?)",
                        (owner_id, topic["id"], topic["name"], topic["quota"],
                         json.dumps(topic, ensure_ascii=False), now),
                    )
            for row in connection.execute(
                "SELECT owner_id,arxiv_id,daily_date,file_path,metadata FROM papers WHERE is_daily=1"
            ):
                metadata = json.loads(row["metadata"] or "{}")
                matches = metadata.get("matched_topics") or []
                topic_id = matches[0].get("id") if matches and isinstance(matches[0], dict) else None
                connection.execute(
                    '''INSERT OR REPLACE INTO daily_arxiv_candidates
                       VALUES (?,?,?,?,?,?,?,?,?,?)''',
                    (row["owner_id"], row["arxiv_id"], row["daily_date"], topic_id,
                     float(metadata.get("relevance_score", 0) or 0),
                     metadata.get("selection_reason") or "历史记录，等待重新评估",
                     metadata.get("artifact_status") or ("ready" if row["file_path"] else "candidate"),
                     int(metadata.get("asset_retry_count", 0) or 0),
                     metadata.get("asset_next_retry_at"), now),
                )
            connection.commit()
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        _write_existing_settings(settings_path, data)
    except Exception:
        _restore_existing_file(db_backup, db_path)
        if settings_backup.exists():
            _restore_existing_file(settings_backup, settings_path)
        raise

    _write_json(manifest, {
        "version": "0.10.0", "state": "completed", "created_at": stamp,
        "database_backup": str(db_backup), "database_sha256": _sha256(db_backup),
        "settings_backup": str(settings_backup) if settings_backup.exists() else None,
        "settings_sha256": _sha256(settings_backup) if settings_backup.exists() else None,
        "report": report,
    })
    return manifest


def rollback(db_path: Path, settings_path: Path, manifest_path: Path) -> None:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("version") != "0.10.0" or manifest.get("state") != "completed":
        raise WorkflowMigrationError("migration_manifest_invalid")
    backup = Path(manifest["database_backup"])
    if _sha256(backup) != manifest["database_sha256"]:
        raise WorkflowMigrationError("database_backup_hash_mismatch")
    _restore_existing_file(backup, db_path)
    if manifest.get("settings_backup"):
        source = Path(manifest["settings_backup"])
        if _sha256(source) != manifest["settings_sha256"]:
            raise WorkflowMigrationError("settings_backup_hash_mismatch")
        _restore_existing_file(source, settings_path)
    manifest["state"] = "rolled_back"
    _write_json(manifest_path, manifest)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--settings", required=True)
    parser.add_argument("--backup-dir")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--dry-run", action="store_true")
    action.add_argument("--apply", action="store_true")
    action.add_argument("--rollback")
    args = parser.parse_args(argv)
    db_path, settings_path = Path(args.db), Path(args.settings)
    if args.dry_run:
        print(json.dumps(inspect(db_path, settings_path), ensure_ascii=False, indent=2))
    elif args.apply:
        if not args.backup_dir:
            parser.error("--backup-dir is required with --apply")
        print(apply(db_path, settings_path, Path(args.backup_dir)))
    else:
        rollback(db_path, settings_path, Path(args.rollback))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
