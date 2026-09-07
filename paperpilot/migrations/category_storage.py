from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from paperpilot.security.paths import (
    PathSecurityError,
    category_directory,
    ensure_confined,
    ensure_confined_tree,
    paper_asset_paths,
    safe_join,
    validate_category_name,
)

MANIFEST_DIRECTORY = ".paperpilot-migrations"


class MigrationError(RuntimeError):
    pass


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _read_categories(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    connection.row_factory = sqlite3.Row
    try:
        rows = [dict(row) for row in connection.execute(
            "SELECT id, name, parent_id FROM categories"
        )]
    except sqlite3.Error as exc:
        raise MigrationError("categories table is unavailable") from exc
    ids = [row["id"] for row in rows]
    if len(ids) != len(set(ids)):
        raise MigrationError("duplicate category id")
    return rows


def _legacy_directories(
    papers_root: Path, categories: list[dict[str, Any]]
) -> dict[str, Path]:
    by_id = {row["id"]: row for row in categories}
    resolved: dict[str, Path] = {}

    def resolve(category_id: str, visiting: set[str]) -> Path:
        if category_id in resolved:
            return resolved[category_id]
        if category_id in visiting:
            raise MigrationError("category parent cycle")
        row = by_id.get(category_id)
        if row is None:
            raise MigrationError("orphan category")
        if category_id == "root":
            result = papers_root
        else:
            name = validate_category_name(row["name"])
            parent_id = row.get("parent_id") or "root"
            parent = resolve(parent_id, visiting | {category_id})
            result = safe_join(papers_root, parent.relative_to(papers_root), name)
        resolved[category_id] = result
        return result

    for category_id in by_id:
        resolve(category_id, set())
    return resolved


def _replace_path(value: str, replacements: list[tuple[str, str]]) -> str:
    candidate = os.path.abspath(value)
    for old, new in sorted(replacements, key=lambda pair: len(pair[0]), reverse=True):
        try:
            relative = Path(candidate).relative_to(old)
        except ValueError:
            continue
        return str(Path(new) / relative)
    return value


def _rewrite_metadata(value: Any, replacements: list[tuple[str, str]]) -> Any:
    if isinstance(value, str):
        return _replace_path(value, replacements) if os.path.isabs(value) else value
    if isinstance(value, list):
        return [_rewrite_metadata(item, replacements) for item in value]
    if isinstance(value, dict):
        return {key: _rewrite_metadata(item, replacements) for key, item in value.items()}
    return value


def build_plan(papers_dir: str, db_path: str) -> dict[str, Any]:
    root = Path(papers_dir).resolve(strict=True)
    if not root.is_dir() or root.is_symlink():
        raise MigrationError("invalid papers root")
    connection = sqlite3.connect(db_path)
    try:
        categories = _read_categories(connection)
        legacy = _legacy_directories(root, categories)
        moves: list[dict[str, str]] = []
        for row in categories:
            category_id = row["id"]
            if category_id == "root":
                continue
            source = legacy[category_id]
            target = category_directory(root, category_id)
            if source.exists():
                ensure_confined_tree(root, source)
                if target.exists():
                    raise MigrationError("legacy and id category directories conflict")
                moves.append({"source": str(source), "target": str(target)})

        # Move deepest legacy directories first so nested categories are flattened.
        moves.sort(key=lambda item: len(Path(item["source"]).parts), reverse=True)
        replacements = [(item["source"], item["target"]) for item in moves]

        # Root-category papers are moved as exact bundles, never as a broad root move.
        for row in connection.execute("SELECT file_path FROM papers WHERE file_path IS NOT NULL"):
            stored = row[0]
            try:
                stored_path = ensure_confined(root, stored)
            except PathSecurityError as exc:
                raise MigrationError("unsafe stored paper path") from exc
            if stored_path.parent != root:
                continue
            assets = paper_asset_paths(root, stored_path)
            target_pdf = category_directory(root, "root") / stored_path.name
            target_assets = paper_asset_paths(root, target_pdf)
            for source, target in (
                (assets.pdf, target_assets.pdf),
                (assets.metadata, target_assets.metadata),
                (assets.chinese_dual, target_assets.chinese_dual),
                (assets.chinese_mono, target_assets.chinese_mono),
                (assets.translation_log, target_assets.translation_log),
                (assets.analysis_directory, target_assets.analysis_directory),
            ):
                if source.exists():
                    if source.is_dir():
                        ensure_confined_tree(root, source)
                    else:
                        ensure_confined(root, source, must_exist=True, require_file=True)
                    if target.exists():
                        raise MigrationError("root paper destination conflict")
                    moves.append({"source": str(source), "target": str(target)})
                    replacements.append((str(source), str(target)))

        updates = []
        for row in connection.execute(
            "SELECT id, file_path, thumbnail_path, metadata FROM papers"
        ):
            paper_id, file_path, thumbnail_path, metadata_text = row
            new_file = _replace_path(file_path, replacements) if file_path else file_path
            new_thumbnail = (
                _replace_path(thumbnail_path, replacements)
                if thumbnail_path else thumbnail_path
            )
            metadata = json.loads(metadata_text) if metadata_text else {}
            new_metadata = _rewrite_metadata(metadata, replacements)
            if (new_file, new_thumbnail, new_metadata) != (
                file_path, thumbnail_path, metadata
            ):
                updates.append({
                    "id": paper_id,
                    "file_path": new_file,
                    "thumbnail_path": new_thumbnail,
                    "metadata": json.dumps(new_metadata, ensure_ascii=False),
                })
        return {"moves": moves, "updates": updates}
    finally:
        connection.close()


def apply_migration(
    papers_dir: str, db_path: str, backup_dir: str
) -> Path:
    plan = build_plan(papers_dir, db_path)
    stamp = _utc_stamp()
    backup_root = Path(backup_dir).resolve()
    backup_root.mkdir(parents=True, exist_ok=True)
    backup_path = backup_root / f"paperpilot-{stamp}.db"
    manifest_root = safe_join(papers_dir, MANIFEST_DIRECTORY)
    manifest_root.mkdir(parents=True, exist_ok=True)
    manifest_path = manifest_root / f"category-storage-{stamp}.json"
    manifest = {
        "version": 1,
        "state": "planned",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "papers_dir": str(Path(papers_dir).resolve()),
        "db_path": str(Path(db_path).resolve()),
        "backup_path": str(backup_path),
        **plan,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    connection = sqlite3.connect(db_path, timeout=1)
    completed_moves: list[dict[str, str]] = []
    try:
        # Fail quickly when another process holds the database. Release this probe
        # transaction before using SQLite's backup API, which cannot progress while
        # the source connection itself owns an exclusive write transaction.
        connection.execute("BEGIN EXCLUSIVE")
        connection.rollback()
        with sqlite3.connect(backup_path) as backup:
            connection.backup(backup)
        connection.execute("BEGIN EXCLUSIVE")
        manifest["state"] = "applying"
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        for move in plan["moves"]:
            source, target = Path(move["source"]), Path(move["target"])
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(target))
            completed_moves.append(move)
        for update in plan["updates"]:
            connection.execute(
                "UPDATE papers SET file_path=?, thumbnail_path=?, metadata=? WHERE id=?",
                (update["file_path"], update["thumbnail_path"], update["metadata"], update["id"]),
            )
        connection.commit()
        manifest["state"] = "complete"
        manifest["completed_at"] = datetime.now(timezone.utc).isoformat()
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return manifest_path
    except Exception:
        connection.rollback()
        for move in reversed(completed_moves):
            source, target = Path(move["source"]), Path(move["target"])
            if target.exists() and not source.exists():
                source.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(target), str(source))
        manifest["state"] = "failed"
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        raise
    finally:
        connection.close()


def rollback_migration(manifest_file: str) -> None:
    manifest_path = Path(manifest_file).resolve(strict=True)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("state") != "complete":
        raise MigrationError("only a completed migration can be rolled back")
    root = Path(manifest["papers_dir"]).resolve(strict=True)
    ensure_confined(root, manifest_path, must_exist=True, require_file=True)
    for move in reversed(manifest["moves"]):
        source, target = Path(move["source"]), Path(move["target"])
        ensure_confined(root, target, must_exist=True)
        if source.exists():
            raise MigrationError("rollback destination conflict")
        source.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(target), str(source))
    shutil.copy2(manifest["backup_path"], manifest["db_path"])
    manifest["state"] = "rolled_back"
    manifest["rolled_back_at"] = datetime.now(timezone.utc).isoformat()
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def assert_storage_migrated(papers_dir: str, db_path: str) -> None:
    root = Path(papers_dir).resolve(strict=True)
    manifests = root / MANIFEST_DIRECTORY
    if manifests.exists():
        ensure_confined_tree(root, manifests)
        for item in manifests.glob("*.json"):
            state = json.loads(item.read_text(encoding="utf-8")).get("state")
            if state in {"planned", "applying", "failed"}:
                raise MigrationError("interrupted category storage migration")
    plan = build_plan(str(root), db_path)
    if plan["moves"] or plan["updates"]:
        raise MigrationError("legacy category storage detected; run the offline migration")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Migrate PaperPilot category storage")
    parser.add_argument("--papers-dir", required=True)
    parser.add_argument("--db", required=True)
    parser.add_argument("--backup-dir")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--dry-run", action="store_true")
    action.add_argument("--apply", action="store_true")
    action.add_argument("--rollback", metavar="MANIFEST")
    args = parser.parse_args(argv)
    try:
        if args.dry_run:
            print(json.dumps(build_plan(args.papers_dir, args.db), indent=2))
        elif args.apply:
            if not args.backup_dir:
                parser.error("--backup-dir is required with --apply")
            print(apply_migration(args.papers_dir, args.db, args.backup_dir))
        else:
            rollback_migration(args.rollback)
        return 0
    except (MigrationError, PathSecurityError, OSError, sqlite3.Error, ValueError) as exc:
        print(f"migration refused: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
