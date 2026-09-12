from __future__ import annotations

from ipaper.environment import getenv as brand_getenv

import hashlib
import json
import os
import re
import stat
import tempfile
import unicodedata
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import BinaryIO
from xml.etree import ElementTree


MIB = 1024 * 1024
_CONFIG_JSON_NAMES = frozenset({
    "categories.json",
    "reading_list.json",
    "user_settings.json",
    "reading_history.json",
    "agentic_settings.json",
    "daily_arxiv_settings.json",
})
_DRIVE_RE = re.compile(r"^[A-Za-z]:")
_MINERU_ORIGIN_PDF_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}_origin\.pdf"
)


class DocumentLimitError(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class DocumentLimits:
    max_pdf_bytes: int = 100 * MIB
    max_archive_bytes: int = 200 * MIB
    max_expanded_bytes: int = 2 * 1024 * MIB
    max_entries: int = 2000
    max_import_papers: int = 500
    max_entry_bytes: int = 100 * MIB
    max_compression_ratio: int = 100
    max_path_depth: int = 8
    max_path_bytes: int = 1024
    max_component_bytes: int = 255
    max_json_bytes: int = 4 * MIB
    max_markdown_bytes: int = 64 * MIB
    max_rdf_bytes: int = 25 * MIB
    max_rdf_records: int = 500
    max_pdf_pages: int = 2000
    max_thumbnail_dimension: int = 1600
    max_thumbnail_pixels: int = 20_000_000
    max_result_image_pixels: int = 50_000_000
    max_thumbnail_bytes: int = 10 * MIB

    @classmethod
    def from_env(cls) -> "DocumentLimits":
        def value(name: str, default: int) -> int:
            raw = brand_getenv(name)
            if raw is None:
                return default
            try:
                parsed = int(raw)
            except ValueError as exc:
                raise DocumentLimitError("invalid_document_limit") from exc
            if parsed <= 0:
                raise DocumentLimitError("invalid_document_limit")
            return parsed

        defaults = cls()
        return cls(
            max_pdf_bytes=value("IPAPER_MAX_PDF_BYTES", defaults.max_pdf_bytes),
            max_archive_bytes=value("IPAPER_MAX_ARCHIVE_BYTES", defaults.max_archive_bytes),
            max_expanded_bytes=value(
                "IPAPER_MAX_ARCHIVE_EXPANDED_BYTES", defaults.max_expanded_bytes
            ),
            max_entries=value("IPAPER_MAX_ARCHIVE_ENTRIES", defaults.max_entries),
            max_import_papers=value("IPAPER_MAX_IMPORT_PAPERS", defaults.max_import_papers),
            max_entry_bytes=defaults.max_entry_bytes,
            max_compression_ratio=defaults.max_compression_ratio,
            max_path_depth=defaults.max_path_depth,
            max_path_bytes=defaults.max_path_bytes,
            max_component_bytes=defaults.max_component_bytes,
            max_json_bytes=defaults.max_json_bytes,
            max_markdown_bytes=defaults.max_markdown_bytes,
            max_rdf_bytes=defaults.max_rdf_bytes,
            max_rdf_records=defaults.max_rdf_records,
            max_pdf_pages=defaults.max_pdf_pages,
            max_thumbnail_dimension=defaults.max_thumbnail_dimension,
            max_thumbnail_pixels=defaults.max_thumbnail_pixels,
            max_result_image_pixels=defaults.max_result_image_pixels,
            max_thumbnail_bytes=defaults.max_thumbnail_bytes,
        )


@dataclass(frozen=True)
class ArchiveEntry:
    path: str
    size: int
    sha256: str


@dataclass(frozen=True)
class ArchiveManifest:
    kind: str
    entries: tuple[ArchiveEntry, ...]
    ignored: list[str]
    expanded_bytes: int

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "entries": [entry.__dict__ for entry in self.entries],
            "ignored": list(self.ignored),
            "expanded_bytes": self.expanded_bytes,
        }


def _regular_file(path: Path, *, reason: str = "unsafe_input") -> os.stat_result:
    if path.is_symlink():
        raise DocumentLimitError(reason)
    try:
        details = path.stat()
    except OSError as exc:
        raise DocumentLimitError(reason) from exc
    if not stat.S_ISREG(details.st_mode):
        raise DocumentLimitError(reason)
    return details


def bounded_copy(source: BinaryIO, destination: Path | str, max_bytes: int) -> int:
    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")
    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_symlink():
        raise DocumentLimitError("unsafe_input")
    temporary = target.with_name(f".{target.name}.{os.getpid()}.upload")
    total = 0
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        with os.fdopen(descriptor, "wb") as output:
            while True:
                chunk = source.read(min(1024 * 1024, max_bytes + 1 - total))
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise DocumentLimitError("upload_too_large")
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, target)
        return total
    except Exception:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise


def _canonical_member(info: zipfile.ZipInfo, limits: DocumentLimits) -> str:
    raw = info.filename
    if not raw or "\\" in raw or "\x00" in raw or _DRIVE_RE.match(raw):
        raise DocumentLimitError("archive_path_invalid")
    if raw.startswith("/") or any(ord(char) < 32 or ord(char) == 127 for char in raw):
        raise DocumentLimitError("archive_path_invalid")
    normalized = unicodedata.normalize("NFC", raw)
    if normalized != raw:
        raise DocumentLimitError("archive_path_invalid")
    path = PurePosixPath(normalized.rstrip("/"))
    if not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise DocumentLimitError("archive_path_invalid")
    if len(path.parts) > limits.max_path_depth:
        raise DocumentLimitError("archive_path_invalid")
    if len(str(path).encode("utf-8")) > limits.max_path_bytes:
        raise DocumentLimitError("archive_path_invalid")
    if any(len(part.encode("utf-8")) > limits.max_component_bytes for part in path.parts):
        raise DocumentLimitError("archive_path_invalid")
    return str(path)


def _check_member_type(info: zipfile.ZipInfo) -> None:
    if info.flag_bits & 0x1:
        raise DocumentLimitError("archive_encrypted")
    unix_mode = info.external_attr >> 16
    file_type = stat.S_IFMT(unix_mode)
    if file_type not in {0, stat.S_IFREG, stat.S_IFDIR}:
        raise DocumentLimitError("archive_link_forbidden")


def _member_policy(path: str, kind: str, limits: DocumentLimits, size: int) -> str:
    suffix = PurePosixPath(path).suffix.lower()
    if kind == "metadata_zip":
        if path.startswith("papers/.avatars/"):
            return "ignore"
        if not path.startswith("papers/") or suffix != ".json":
            raise DocumentLimitError("archive_type_forbidden")
        if size > limits.max_json_bytes:
            raise DocumentLimitError("archive_entry_too_large")
        return "include"
    if kind == "mineru_zip":
        # Cloud bundles a redundant source PDF. Treat it as opaque discarded
        # input, never as a readable/extracted result. All archive-level checks
        # (regular file, path, count, size and ratio) precede this decision.
        if _MINERU_ORIGIN_PDF_RE.fullmatch(path):
            if size > limits.max_pdf_bytes:
                raise DocumentLimitError("archive_entry_too_large")
            return "ignore"
        if suffix not in {".md", ".json", ".png", ".jpg", ".jpeg"}:
            raise DocumentLimitError("archive_type_forbidden")
        if suffix == ".md" and size > limits.max_markdown_bytes:
            raise DocumentLimitError("archive_entry_too_large")
        if suffix == ".json" and size > limits.max_json_bytes:
            raise DocumentLimitError("archive_entry_too_large")
        return "include"
    raise DocumentLimitError("unsupported_document_kind")


def preflight_archive(
    archive_path: Path | str,
    kind: str,
    limits: DocumentLimits | None = None,
) -> ArchiveManifest:
    limits = limits or DocumentLimits()
    source = Path(archive_path)
    details = _regular_file(source)
    if details.st_size > limits.max_archive_bytes:
        raise DocumentLimitError("archive_too_large")
    entries: list[ArchiveEntry] = []
    ignored: list[str] = []
    seen: set[str] = set()
    expanded = 0
    paper_count = 0
    try:
        with zipfile.ZipFile(source, "r") as archive:
            members = archive.infolist()
            if len(members) > limits.max_entries:
                raise DocumentLimitError("archive_entry_limit")
            for info in members:
                _check_member_type(info)
                path = _canonical_member(info, limits)
                collision_key = path.casefold()
                if collision_key in seen:
                    raise DocumentLimitError("archive_duplicate_entry")
                seen.add(collision_key)
                if info.is_dir():
                    continue
                if info.file_size > limits.max_entry_bytes:
                    raise DocumentLimitError("archive_entry_too_large")
                expanded += info.file_size
                if expanded > limits.max_expanded_bytes:
                    raise DocumentLimitError("archive_expanded_limit")
                ratio = info.file_size / max(info.compress_size, 1)
                if ratio > limits.max_compression_ratio:
                    raise DocumentLimitError("archive_ratio_limit")
                policy = _member_policy(path, kind, limits, info.file_size)
                if policy == "ignore":
                    if kind == "mineru_zip" and ignored:
                        raise DocumentLimitError("archive_origin_pdf_limit")
                    ignored.append(path)
                    continue
                if kind == "metadata_zip" and PurePosixPath(path).name not in _CONFIG_JSON_NAMES:
                    paper_count += 1
                    if paper_count > limits.max_import_papers:
                        raise DocumentLimitError("archive_paper_limit")
                digest = hashlib.sha256()
                actual = 0
                with archive.open(info, "r") as member:
                    while True:
                        chunk = member.read(1024 * 1024)
                        if not chunk:
                            break
                        actual += len(chunk)
                        if actual > info.file_size or actual > limits.max_entry_bytes:
                            raise DocumentLimitError("archive_expanded_limit")
                        digest.update(chunk)
                if actual != info.file_size:
                    raise DocumentLimitError("archive_size_mismatch")
                entries.append(ArchiveEntry(path, actual, digest.hexdigest()))
    except DocumentLimitError:
        raise
    except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
        raise DocumentLimitError("archive_invalid") from exc
    return ArchiveManifest(kind, tuple(entries), ignored, expanded)


def extract_validated_archive(
    archive_path: Path | str,
    destination: Path | str,
    manifest: ArchiveManifest,
    limits: DocumentLimits | None = None,
) -> None:
    limits = limits or DocumentLimits()
    source = Path(archive_path)
    current = preflight_archive(source, manifest.kind, limits)
    if current != manifest:
        raise DocumentLimitError("archive_changed")
    output_root = Path(destination)
    if output_root.exists() and (output_root.is_symlink() or any(output_root.iterdir())):
        raise DocumentLimitError("unsafe_output")
    output_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    expected = {entry.path: entry for entry in manifest.entries}
    try:
        with zipfile.ZipFile(source, "r") as archive:
            for info in archive.infolist():
                path = _canonical_member(info, limits)
                entry = expected.get(path)
                if entry is None:
                    continue
                target = output_root.joinpath(*PurePosixPath(path).parts)
                target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                with archive.open(info, "r") as member:
                    bounded_copy(member, target, entry.size)
                if target.stat().st_size != entry.size:
                    raise DocumentLimitError("archive_size_mismatch")
                if hashlib.sha256(target.read_bytes()).hexdigest() != entry.sha256:
                    raise DocumentLimitError("archive_hash_mismatch")
                if manifest.kind == "mineru_zip" and target.suffix.lower() in {".png", ".jpg", ".jpeg"}:
                    _validate_result_image(target, limits)
        manifest_path = output_root / "manifest.json"
        manifest_path.write_text(json.dumps(manifest.to_dict(), sort_keys=True), encoding="utf-8")
        os.chmod(manifest_path, 0o600)
    except Exception:
        # The caller owns the job directory and removes it as one confined tree.
        raise


def _validate_result_image(path: Path, limits: DocumentLimits) -> None:
    try:
        from PIL import Image

        with Image.open(path) as image:
            width, height = image.size
            if width <= 0 or height <= 0 or width * height > limits.max_result_image_pixels:
                raise DocumentLimitError("image_pixel_limit")
            image.verify()
    except DocumentLimitError:
        raise
    except Exception as exc:
        raise DocumentLimitError("image_invalid") from exc


def inspect_pdf(
    pdf_path: Path | str,
    output_dir: Path | str,
    limits: DocumentLimits | None = None,
) -> dict:
    limits = limits or DocumentLimits()
    source = Path(pdf_path)
    details = _regular_file(source)
    if details.st_size > limits.max_pdf_bytes:
        raise DocumentLimitError("upload_too_large")
    with source.open("rb") as handle:
        if b"%PDF-" not in handle.read(1024):
            raise DocumentLimitError("pdf_invalid")
    try:
        import fitz

        document = fitz.open(source)
        try:
            page_count = document.page_count
            if page_count <= 0:
                raise DocumentLimitError("pdf_invalid")
            if page_count > limits.max_pdf_pages:
                raise DocumentLimitError("pdf_page_limit")
            page = document.load_page(0)
            rectangle = page.rect
            if rectangle.width <= 0 or rectangle.height <= 0:
                raise DocumentLimitError("pdf_invalid")
            scale = min(
                limits.max_thumbnail_dimension / rectangle.width,
                limits.max_thumbnail_dimension / rectangle.height,
                2.0,
            )
            width = max(1, int(rectangle.width * scale))
            height = max(1, int(rectangle.height * scale))
            if width * height > limits.max_thumbnail_pixels:
                raise DocumentLimitError("thumbnail_pixel_limit")
            pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
            thumbnail = pixmap.tobytes("jpeg")
            if len(thumbnail) > limits.max_thumbnail_bytes:
                raise DocumentLimitError("thumbnail_too_large")
            destination = Path(output_dir)
            destination.mkdir(mode=0o700, parents=True, exist_ok=False)
            bounded_copy(io_bytes(thumbnail), destination / "thumbnail.jpg", limits.max_thumbnail_bytes)
            metadata = document.metadata or {}
            from .structure import page_geometry, digest_file
            result = {
                "sha256": digest_file(source),
                "pages": page_geometry(document),
                "page_count": page_count,
                "first_page_text": (page.get_text() or "")[:65536],
                "metadata": {
                    name: str(metadata.get(name) or "")[:4096]
                    for name in ("title", "author", "subject", "keywords")
                },
                "thumbnail": "thumbnail.jpg",
            }
            metadata_path = destination / "result.json"
            metadata_path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
            os.chmod(metadata_path, 0o600)
            return result
        finally:
            document.close()
    except DocumentLimitError:
        raise
    except Exception as exc:
        raise DocumentLimitError("pdf_invalid") from exc


def io_bytes(value: bytes):
    from io import BytesIO

    return BytesIO(value)


def validate_zotero_rdf(data: bytes, limits: DocumentLimits | None = None) -> int:
    limits = limits or DocumentLimits()
    if len(data) > limits.max_rdf_bytes:
        raise DocumentLimitError("upload_too_large")
    lowered = data.lower()
    if b"<!doctype" in lowered or b"<!entity" in lowered:
        raise DocumentLimitError("rdf_unsafe_xml")
    try:
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError as exc:
        raise DocumentLimitError("rdf_invalid") from exc
    count = sum(1 for element in root.iter() if element.tag.rsplit("}", 1)[-1] == "Description")
    if count > limits.max_rdf_records:
        raise DocumentLimitError("rdf_record_limit")
    return count
