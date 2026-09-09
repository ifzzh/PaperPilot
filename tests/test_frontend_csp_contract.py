import hashlib
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = tuple((ROOT / "templates").glob("*.html"))
FRONTEND_SOURCES = (*TEMPLATES, *(ROOT / "static" / "js").glob("*.js"))


def test_templates_have_no_inline_scripts_or_event_attributes():
    inline_script = re.compile(r"<script(?![^>]*\bsrc=)[^>]*>", re.IGNORECASE)
    inline_event = re.compile(r"\son[a-z]+\s*=", re.IGNORECASE)

    for path in TEMPLATES:
        source = path.read_text(encoding="utf-8")
        assert not inline_script.search(source), path
        assert not inline_event.search(source), path


def test_frontend_does_not_generate_inline_event_handlers():
    for path in FRONTEND_SOURCES:
        source = path.read_text(encoding="utf-8")
        assert "onclick=" not in source.lower(), path
        assert "onerror=" not in source.lower(), path


def test_templates_load_executable_assets_only_from_static_vendor():
    remote_script = re.compile(r"<script[^>]+src=[\"']https?://", re.IGNORECASE)
    remote_style = re.compile(
        r"<link[^>]+rel=[\"']stylesheet[\"'][^>]+href=[\"']https?://",
        re.IGNORECASE,
    )
    combined = "\n".join(path.read_text(encoding="utf-8") for path in TEMPLATES)
    assert not remote_script.search(combined)
    assert not remote_style.search(combined)
    for asset in (
        "vendor/marked/marked.min.js",
        "vendor/highlight/highlight.min.js",
        "vendor/mathjax/tex-chtml.js",
        "vendor/fontawesome/css/all.min.css",
    ):
        assert asset in combined


def test_vendor_manifest_covers_every_committed_asset():
    vendor_root = ROOT / "static" / "vendor"
    manifest = json.loads((vendor_root / "manifest.json").read_text(encoding="utf-8"))
    declared = manifest["files"]
    actual = {
        path.relative_to(vendor_root).as_posix()
        for path in vendor_root.rglob("*")
        if path.is_file() and path.name != "manifest.json"
    }
    assert set(declared) == actual
    for relative, expected in declared.items():
        digest = hashlib.sha256((vendor_root / relative).read_bytes()).hexdigest()
        assert digest == expected["sha256"]
        assert expected["package"] in manifest["packages"]


def test_dormant_browser_pdf_parser_is_removed():
    index = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    app_source = (ROOT / "static" / "js" / "app.js").read_text(encoding="utf-8")
    assert "pdf.js" not in index.lower()
    assert "parsePdfWithPdfjs" not in app_source
    assert "pdfjsLib.getDocument" not in app_source
