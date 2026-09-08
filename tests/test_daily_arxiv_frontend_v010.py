from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_daily_arxiv_topic_editor_and_24_paper_default_are_visible():
    template = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    script = (ROOT / "static" / "js" / "app.js").read_text(encoding="utf-8")
    assert 'id="daily-arxiv-topic-list"' in template
    assert 'id="daily-arxiv-max-daily-papers"' in template
    assert 'value="24"' in template
    assert "collectDailyArxivResearchTopics" in script
    assert "topicFilteringEnabled = true" in script


def test_missing_pdf_uses_a_topic_cover_and_exposes_retry():
    script = (ROOT / "static" / "js" / "app.js").read_text(encoding="utf-8")
    css = (ROOT / "static" / "css" / "style.css").read_text(encoding="utf-8")
    assert "daily-arxiv-theme-cover" in script
    assert "retryDailyArxivAsset" in script
    assert "theme-robotics-vla" in css
    assert "status-ready" in css
