"""Bounded PDF splitting and MinerU normalization. Runs in Document Worker only.

Unknown parser geometry is deliberately retained as page-only provenance. This
module never treats an arbitrary bbox or model-provided path as a source link.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import replace
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath

from .safety import (DocumentLimits, DocumentLimitError, _regular_file,
                     extract_validated_archive, preflight_archive)

NORMALIZER_VERSION = "mineru-content-list-v1/1"
MAX_JSON_BYTES = 32 * 1024**2
MAX_BLOCKS = 100_000
MAX_STRING = 2 * 1024**2
MAX_NODES = 1_000_000
MAX_DEPTH = 32
MAX_RESULT_BYTES = 1024**3


def digest_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024**2), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False,
                               separators=(",", ":")), encoding="utf-8")


def bounded_json(path: Path):
    if _regular_file(path).st_size > MAX_JSON_BYTES:
        raise DocumentLimitError("structure_json_size_limit")
    try:
        value = json.loads(path.read_text("utf-8"),
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError, RecursionError, UnicodeError) as exc:
        raise DocumentLimitError("structure_json_invalid") from exc
    stack = [(value, 0)]
    nodes = 0
    while stack:
        item, depth = stack.pop()
        nodes += 1
        if depth > MAX_DEPTH or nodes > MAX_NODES:
            raise DocumentLimitError("structure_json_complexity_limit")
        if isinstance(item, str) and len(item) > MAX_STRING:
            raise DocumentLimitError("structure_string_limit")
        if isinstance(item, dict):
            stack.extend((child, depth + 1) for child in item.values())
            stack.extend((key, depth + 1) for key in item.keys())
        elif isinstance(item, list):
            stack.extend((child, depth + 1) for child in item)
    return value


def _open_pdf(source: Path, limits: DocumentLimits):
    if _regular_file(source).st_size > limits.max_pdf_bytes:
        raise DocumentLimitError("upload_too_large")
    import fitz
    try:
        document = fitz.open(source)
        if not document.is_pdf or document.needs_pass:
            document.close()
            raise DocumentLimitError("pdf_encrypted_or_invalid")
        if not 0 < document.page_count <= limits.max_pdf_pages:
            document.close()
            raise DocumentLimitError("pdf_page_limit")
        return document
    except DocumentLimitError:
        raise
    except Exception as exc:
        raise DocumentLimitError("pdf_invalid") from exc


def page_geometry(document) -> list[dict]:
    pages = []
    for page in document:
        kind, raw = document.xref_get_key(page.xref, "UserUnit")
        unit = float(raw) if kind in {"int", "float"} else 1.0
        if not math.isfinite(unit) or not 0 < unit <= 75000:
            raise DocumentLimitError("pdf_geometry_invalid")
        media = list(page.mediabox)
        crop = list(page.cropbox)
        if any(not math.isfinite(x) for x in [*media, *crop]):
            raise DocumentLimitError("pdf_geometry_invalid")
        # PyMuPDF's matrix is the explicit PDF-user-space -> unrotated
        # top-left-page transform, including crop/user-unit handling.
        pages.append({"page": page.number + 1, "mediaBox": media,
                      "cropBox": crop, "userUnit": unit,
                      "rotation": page.rotation,
                      "width": page.rect.width, "height": page.rect.height,
                      "pdfToPage": list(page.transformation_matrix)})
    return pages


def manifest_for(output: Path, kind: str, *, ignored=()) -> dict:
    entries = []
    total = 0
    for path in sorted(output.rglob("*")):
        if path.is_dir():
            if path.is_symlink():
                raise DocumentLimitError("unsafe_worker_output")
            continue
        size = _regular_file(path).st_size
        relative = path.relative_to(output).as_posix()
        if relative == "manifest.json":
            continue
        total += size
        if total > MAX_RESULT_BYTES or len(entries) >= 2000:
            raise DocumentLimitError("structure_output_limit")
        entries.append({"path": relative, "size": size, "sha256": digest_file(path)})
    manifest = {"kind": kind, "entries": entries, "ignored": list(ignored),
                "expanded_bytes": total}
    write_json(output / "manifest.json", manifest)
    return manifest


def split_pdf(source: Path, output: Path, limits: DocumentLimits) -> None:
    import fitz
    with _open_pdf(source, limits) as document:
        geometry = page_geometry(document)
        output.mkdir(mode=0o700)
        parts = []
        total = 0

        def part(start: int, stop: int):
            nonlocal total
            target = output / f"part-{start + 1:06d}-{stop:06d}.pdf"
            with fitz.open() as subset:
                subset.insert_pdf(document, from_page=start, to_page=stop - 1)
                subset.save(target, garbage=4, deflate=True)
            size = target.stat().st_size
            if size > min(limits.max_pdf_bytes, 200 * 1024**2):
                target.unlink()
                if stop - start <= 1:
                    raise DocumentLimitError("pdf_page_too_large")
                middle = (start + stop) // 2
                part(start, middle)
                part(middle, stop)
                return
            total += size
            if total > MAX_RESULT_BYTES or len(parts) >= 1000:
                raise DocumentLimitError("pdf_split_size_limit")
            # Verify the generated PDF before any cloud task can be created.
            with _open_pdf(target, limits) as check:
                if check.page_count != stop - start:
                    raise DocumentLimitError("pdf_split_invalid")
                actual_geometry = page_geometry(check)
            parts.append({"path": target.name, "sha256": digest_file(target),
                          "size": size, "firstPage": start + 1, "lastPage": stop,
                          "pages": actual_geometry})

        for start in range(0, len(geometry), 200):
            part(start, min(start + 200, len(geometry)))
        write_json(output / "result.json", {"schema": 1, "sha256": digest_file(source),
                   "pageCount": len(geometry), "pages": geometry, "parts": parts})
    manifest_for(output, "pdf_split")


class _TableParser(HTMLParser):
    """Extract cells only. No upstream HTML, attributes or URLs reach rendering."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows = []
        self.cell = None
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.skip += 1
        if self.skip:
            return
        if tag == "tr":
            if len(self.rows) >= 2000:
                raise DocumentLimitError("structure_table_limit")
            self.rows.append([])
        elif tag in {"td", "th"}:
            if not self.rows:
                self.rows.append([])
            if len(self.rows[-1]) >= 200:
                raise DocumentLimitError("structure_table_limit")
            attributes = dict(attrs)
            try:
                span = {key: max(1, min(200, int(attributes.get(key, 1))))
                        for key in ("rowspan", "colspan")}
            except (TypeError, ValueError):
                span = {"rowspan": 1, "colspan": 1}
            self.cell = {"text": "", "header": tag == "th", **span}
            self.rows[-1].append(self.cell)

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.skip = max(0, self.skip - 1)
        if tag in {"td", "th"}:
            self.cell = None

    def handle_data(self, data):
        if self.cell is not None and not self.skip:
            self.cell["text"] += data


def _text(value) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(item for item in value if isinstance(item, str))
    return ""


def _source(item: dict, pages: list[dict], layout_pages: dict) -> dict:
    idx = item.get("page_idx")
    if type(idx) is not int or not 0 <= idx < len(pages):
        return {"precision": "none", "regions": [], "reason": "page_unverified"}
    geometry = pages[idx]
    source = {"page": idx + 1, "precision": "page", "regions": [],
              "parserCoordinates": "mineru-content-list-normalized-1000" if layout_pages else "unverified",
              "parserPageIndex":idx}
    layout = layout_pages.get(idx)
    bbox = item.get("bbox")
    if isinstance(bbox,list) and len(bbox)==4 and all(type(v) in (int,float) and math.isfinite(v) for v in bbox):
        source["parserBox"]=bbox
    # The tested unrotated, uncropped 1-unit page path. Other page geometry
    # remains usable at page precision until its parser transform is proven.
    media, crop = geometry["mediaBox"], geometry["cropBox"]
    if (not layout or geometry["rotation"] != 0 or geometry["userUnit"] != 1
            or media != crop or media[:2] != [0.0, 0.0]
            or not isinstance(bbox, list) or len(bbox) != 4
            or any(type(v) not in (int, float) or not math.isfinite(v) for v in bbox)
            or not (0 <= bbox[0] < bbox[2] <= 1000 and 0 <= bbox[1] < bbox[3] <= 1000)):
        return source
    size = layout.get("page_size")
    if (not isinstance(size, list) or len(size) != 2
            or any(type(v) not in (int, float) or not math.isfinite(v) for v in size)
            or abs(size[0] - geometry["width"]) > 1
            or abs(size[1] - geometry["height"]) > 1):
        return source
    # Convert the known top-left normalized page convention through the inverse
    # page matrix, instead of accidentally storing screen or rotated coords.
    import fitz
    inverse = ~fitz.Matrix(*geometry["pdfToPage"])
    rect = fitz.Rect(bbox[0] * size[0] / 1000, bbox[1] * size[1] / 1000,
                     bbox[2] * size[0] / 1000, bbox[3] * size[1] / 1000) * inverse
    source.update(precision="region", regions=[{"page": idx + 1, "rect": list(rect)}])
    return source


def normalize_mineru(archive: Path, source: Path, output: Path,
                     limits: DocumentLimits) -> None:
    # Structure limits are local to this new task; legacy mineru_zip stays 4 MiB.
    structured_limits = replace(limits, max_json_bytes=MAX_JSON_BYTES)
    manifest = preflight_archive(archive, "mineru_zip", structured_limits)
    output.mkdir(mode=0o700)
    raw = output / "raw"
    extract_validated_archive(archive, raw, manifest, structured_limits)
    (raw / "manifest.json").rename(raw / "archive-manifest.json")
    json_values = {}
    json_total = 0
    for entry in manifest.entries:
        path = raw / entry.path
        if path.suffix.lower() == ".json":
            json_total += path.stat().st_size
            if json_total > 128*1024**2:
                raise DocumentLimitError("structure_json_total_limit")
            value=bounded_json(path)
            if entry.path.endswith("_content_list.json") or PurePosixPath(entry.path).name in {"content_list.json","layout.json"}:
                json_values[entry.path]=value
            # Model/intermediate JSON is validated and retained on disk, but
            # not all retained in memory simultaneously.
            del value
    candidates = [(name, value) for name, value in json_values.items()
                  if name.endswith("_content_list.json") or name == "content_list.json"]
    if len(candidates) != 1 or not isinstance(candidates[0][1], list):
        raise DocumentLimitError("structure_content_schema_unsupported")
    name, content = candidates[0]
    if len(content) > MAX_BLOCKS:
        raise DocumentLimitError("structure_block_limit")
    layouts = [value for name, value in json_values.items()
               if PurePosixPath(name).name == "layout.json"]
    layout_pages = {}
    parser_version = layouts[0].get("_version_name") if len(layouts)==1 and isinstance(layouts[0],dict) else None
    parser_backend = layouts[0].get("_backend") if len(layouts)==1 and isinstance(layouts[0],dict) else None
    # This exact output convention has real-archive geometry evidence. Future
    # versions remain readable at page precision until revalidated.
    if parser_version == "3.4.4" and parser_backend == "hybrid" and isinstance(layouts[0].get("pdf_info"),list):
        for page in layouts[0]["pdf_info"]:
            if isinstance(page, dict) and type(page.get("page_idx")) is int:
                layout_pages[page["page_idx"]] = page
    with _open_pdf(source, limits) as document:
        pages = page_geometry(document)
    assets = {entry.path for entry in manifest.entries
              if PurePosixPath(entry.path).suffix.lower() in {".png", ".jpg", ".jpeg"}}
    blocks = []
    for order, item in enumerate(content):
        if not isinstance(item, dict) or not isinstance(item.get("type"), str):
            raise DocumentLimitError("structure_content_schema_unsupported")
        kind = item["type"]
        text = _text(item.get("text"))
        table = None
        caption = ""
        if kind == "table":
            parser = _TableParser()
            parser.feed(_text(item.get("table_body")))
            table = parser.rows or None
            text = "\n".join("\t".join(cell["text"] for cell in row) for row in table or [])
            caption = _text(item.get("table_caption")) + "\n" + _text(item.get("table_footnote"))
        elif kind == "image":
            caption = _text(item.get("image_caption")) + "\n" + _text(item.get("image_footnote"))
        image = item.get("img_path")
        image_path = None
        if isinstance(image, str):
            relative = (PurePosixPath(name).parent / image).as_posix()
            if relative in assets:
                image_path = "raw/" + relative
        source_ref = _source(item, pages, layout_pages)
        text_hash = hashlib.sha256((text + "\n" + caption.strip()).encode()).hexdigest()
        blocks.append({"id": f"b{order:06d}-{text_hash[:12]}", "order": order,
                       "type": kind, "text": text, "textHash": text_hash,
                       "level": item.get("text_level") if type(item.get("text_level")) is int else None,
                       "table": table, "caption": caption.strip(), "image": image_path,
                       "source": source_ref})
    # Preserve upstream sequence within each known page; asynchronous part merge
    # will later add its global page offset. Unknown pages retain original order.
    with (output / "blocks.jsonl").open("w", encoding="utf-8") as handle:
        for block in blocks:
            handle.write(json.dumps(block, ensure_ascii=False, allow_nan=False) + "\n")
    write_json(output / "result.json", {"schema": 1, "normalizer": NORMALIZER_VERSION,
               "sourceSha256": digest_file(source), "pageCount": len(pages),
               "pages": pages, "parserVersion":parser_version,"parserBackend":parser_backend,
               "blockCount": len(blocks), "blocks": "blocks.jsonl"})
    manifest_for(output, "mineru_structure", ignored=manifest.ignored)


def extract_page_text(source: Path, selection: Path, output: Path, limits: DocumentLimits):
    request = bounded_json(selection)
    if not isinstance(request, dict) or set(request) != {"page"} or type(request["page"]) is not int:
        raise DocumentLimitError("invalid_page_request")
    with _open_pdf(source, limits) as document:
        number = request["page"]
        if not 1 <= number <= document.page_count:
            raise DocumentLimitError("invalid_page_request")
        page = document.load_page(number - 1)
        text = page.get_text(sort=True)
        if len(text) > 131072:
            raise DocumentLimitError("page_text_limit")
        output.mkdir(mode=0o700)
        write_json(output / "result.json", {"sha256": digest_file(source), "page": number,
             "pageCount": document.page_count, "pages": page_geometry(document), "text": text})
