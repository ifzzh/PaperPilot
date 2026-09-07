from __future__ import annotations

import os
import stat
import uuid
from pathlib import Path
from typing import Iterable


_CATEGORY_NAMESPACE = uuid.uuid5(
    uuid.NAMESPACE_URL,
    "https://github.com/ifzzh/PaperPilot/category-storage/v1",
)


class PathSecurityError(ValueError):
    """Raised when a filesystem path violates PaperPilot storage policy."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _as_text(value: os.PathLike[str] | str) -> str:
    text = os.fspath(value)
    if "\x00" in text:
        raise PathSecurityError("nul_byte")
    return text


def _canonical_root(root: os.PathLike[str] | str) -> Path:
    root_path = Path(_as_text(root)).absolute()
    if root_path.is_symlink():
        raise PathSecurityError("symlink_root")
    try:
        resolved = root_path.resolve(strict=True)
    except (FileNotFoundError, OSError) as exc:
        raise PathSecurityError("missing_root") from exc
    if not resolved.is_dir():
        raise PathSecurityError("root_not_directory")
    return resolved


def _reject_parent_references(path: Path) -> None:
    if any(part == ".." for part in path.parts):
        raise PathSecurityError("parent_reference")


def _reject_symlink_components(root: Path, relative_parts: Iterable[str]) -> None:
    current = root
    for part in relative_parts:
        current = current / part
        try:
            mode = os.lstat(current).st_mode
        except FileNotFoundError:
            break
        except OSError as exc:
            raise PathSecurityError("path_unreadable") from exc
        if stat.S_ISLNK(mode):
            raise PathSecurityError("symlink_component")


def ensure_confined(
    root: os.PathLike[str] | str,
    candidate: os.PathLike[str] | str,
    *,
    must_exist: bool = False,
    require_file: bool = False,
) -> Path:
    """Return a canonical path strictly below root with no symlink components."""
    root_path = _canonical_root(root)
    candidate_text = _as_text(candidate)
    raw_candidate = Path(candidate_text)
    _reject_parent_references(raw_candidate)

    if raw_candidate.is_absolute():
        candidate_path = Path(os.path.abspath(candidate_text))
    else:
        candidate_path = Path(os.path.abspath(root_path / raw_candidate))

    try:
        relative = candidate_path.relative_to(root_path)
    except ValueError as exc:
        raise PathSecurityError("outside_root") from exc
    if not relative.parts:
        raise PathSecurityError("root_target")

    _reject_symlink_components(root_path, relative.parts)
    try:
        resolved = candidate_path.resolve(strict=must_exist)
    except FileNotFoundError as exc:
        raise PathSecurityError("missing_path") from exc
    except OSError as exc:
        raise PathSecurityError("path_unreadable") from exc

    try:
        resolved.relative_to(root_path)
    except ValueError as exc:
        raise PathSecurityError("outside_root") from exc

    if must_exist and not resolved.exists():
        raise PathSecurityError("missing_path")
    if require_file and not resolved.is_file():
        raise PathSecurityError("not_regular_file")
    return resolved


def safe_join(
    root: os.PathLike[str] | str,
    *relative_parts: os.PathLike[str] | str,
    must_exist: bool = False,
    require_file: bool = False,
) -> Path:
    """Join untrusted relative parts below root and apply confinement checks."""
    combined = Path()
    for value in relative_parts:
        text = _as_text(value)
        path = Path(text)
        if path.is_absolute() or "\\" in text:
            raise PathSecurityError("absolute_or_foreign_separator")
        _reject_parent_references(path)
        combined /= path
    return ensure_confined(
        root,
        combined,
        must_exist=must_exist,
        require_file=require_file,
    )


def validate_filename(value: object) -> str:
    """Validate one server-managed filename component without rewriting it."""
    if not isinstance(value, str):
        raise PathSecurityError("invalid_filename")
    text = _as_text(value)
    if (
        not text
        or text in {".", ".."}
        or Path(text).is_absolute()
        or "/" in text
        or "\\" in text
        or any(ord(character) < 32 for character in text)
    ):
        raise PathSecurityError("invalid_filename")
    return text


def category_storage_id(category_id: object) -> str:
    """Return a stable, path-safe UUIDv5 for a logical category ID."""
    if not isinstance(category_id, str) or not category_id:
        raise PathSecurityError("invalid_category_id")
    return uuid.uuid5(_CATEGORY_NAMESPACE, category_id).hex


def category_directory(
    root: os.PathLike[str] | str,
    category_id: str,
    *,
    create: bool = False,
) -> Path:
    directory = safe_join(root, ".categories", category_storage_id(category_id))
    if create:
        directory.mkdir(parents=True, exist_ok=True)
        directory = ensure_confined(root, directory, must_exist=True)
    return directory


def paper_directory(
    root: os.PathLike[str] | str,
    category_id: str,
    *,
    create: bool = False,
) -> Path:
    if category_id == "reading_list_temp":
        directory = safe_join(root, "_ReadingListTemp")
        if create:
            directory.mkdir(parents=True, exist_ok=True)
            directory = ensure_confined(root, directory, must_exist=True)
        return directory
    return category_directory(root, category_id, create=create)


def paper_path(
    root: os.PathLike[str] | str,
    category_id: str,
    filename: object,
    *,
    create_parent: bool = False,
    must_exist: bool = False,
) -> Path:
    directory = paper_directory(root, category_id, create=create_parent)
    return ensure_confined(
        root,
        directory / validate_filename(filename),
        must_exist=must_exist,
        require_file=must_exist,
    )


def verified_paper_path(
    root: os.PathLike[str] | str,
    category_id: str,
    filename: object,
    stored_path: object,
    *,
    must_exist: bool = True,
) -> Path:
    if not isinstance(stored_path, (str, os.PathLike)):
        raise PathSecurityError("invalid_stored_path")
    expected = paper_path(
        root,
        category_id,
        filename,
        must_exist=must_exist,
    )
    stored = ensure_confined(
        root,
        stored_path,
        must_exist=must_exist,
        require_file=must_exist,
    )
    if stored != expected:
        raise PathSecurityError("stored_path_mismatch")
    return expected
