import json
from pathlib import Path


FIXTURE_PATH = Path(__file__).with_name("frontend_xss_cases.json")


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
