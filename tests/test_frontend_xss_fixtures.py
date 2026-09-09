import json
from pathlib import Path


FIXTURE_PATH = Path(__file__).with_name("frontend_xss_cases.json")
ROOT = Path(__file__).resolve().parents[1]


def test_frontend_xss_fixture_covers_required_attack_families():
    cases = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    names = [case["name"] for case in cases]

    assert len(names) == len(set(names))
    assert {
        "script_element",
        "image_event_handler",
        "svg_event_handler",
        "mathml_script_url",
        "attribute_breakout",
        "javascript_link",
        "data_image",
        "malformed_html",
    } <= set(names)

    for case in cases:
        assert case["payload"]
        assert case["plain_text"] == case["payload"]
        assert case["forbidden_selectors"]


def test_sanitizer_is_self_hosted_and_loaded_before_application_code():
    for template_name in ("index.html", "analysis_viewer.html"):
        source = (ROOT / "templates" / template_name).read_text(encoding="utf-8")
        purifier = source.index("vendor/dompurify/purify.min.js")
        security = source.index("js/content_security.js")
        assert purifier < security

    index = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    assert index.index("js/content_security.js") < index.index("js/auth.js")


def test_markdown_and_plain_text_sinks_use_security_layer():
    app_source = (ROOT / "static" / "js" / "app.js").read_text(encoding="utf-8")
    viewer_source = (ROOT / "static" / "js" / "analysis_viewer.js").read_text(encoding="utf-8")

    assert "sanitizeMarkdownHtml(marked.parse(markdown)" in app_source
    assert "renderChatMarkdown(fullResponse) +" not in app_source
    assert "<textarea style=\"display:none\">" not in app_source
    assert "setSanitizedMarkdown(el, html, { paperId })" in viewer_source
    assert "document.getElementById('md').innerHTML = html" not in viewer_source


def test_browser_harness_covers_markdown_compatibility_and_image_policy():
    harness = (ROOT / "tests" / "frontend_xss_harness.html").read_text(encoding="utf-8")

    for selector in ("h2", "blockquote", "table", "pre code", "strong"):
        assert selector in harness
    assert "markdown-external-image" in harness
    assert "/api/paper/paper-1/analysis/image" in harness
