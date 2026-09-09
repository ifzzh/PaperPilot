from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_all_entry_pages_default_to_simplified_chinese():
    for name in ("index.html", "analysis_viewer.html", "pdf_viewer.html"):
        source = (ROOT / "templates" / name).read_text(encoding="utf-8")
        assert '<html lang="zh-CN">' in source
        assert "i18n_zh_cn.js" in source


def test_frontend_does_not_use_locale_dependent_date_order():
    sources = "\n".join(
        path.read_text(encoding="utf-8") for path in (ROOT / "static" / "js").glob("*.js")
    )
    assert "toLocaleDateString" not in sources
    assert "toLocaleTimeString" not in sources
    assert "toLocaleString" not in sources


def test_chinese_catalog_preserves_product_terms_and_uses_ymd():
    source = (ROOT / "static" / "js" / "i18n_zh_cn.js").read_text(encoding="utf-8")
    assert "'Reading list': 'Reading List'" in source
    assert "'Daily arXiv Settings': 'Daily arXiv 设置'" in source
    assert "${date.getFullYear()}-${String(date.getMonth() + 1)" in source


def test_login_and_onboarding_ship_with_chinese_copy():
    source = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    assert "Welcome to PaperPilot Paper Reading" not in source
    assert "Select AI Output Language" not in source
    assert "Configure AI features" not in source
    assert "欢迎使用 PaperPilot 智能论文阅读" in source
    assert "选择 AI 输出语言" in source


def test_task_actions_and_viewers_do_not_ship_legacy_english_copy():
    sources = "\n".join(
        (ROOT / path).read_text(encoding="utf-8")
        for path in (
            "static/js/app.js",
            "static/js/pdf_viewer.js",
            "templates/analysis_viewer.html",
            "templates/pdf_viewer.html",
        )
    )
    for legacy in (
        'title="View logs"',
        'title="Cancel translation"',
        "> Chinese version</button>",
        ">Reload<",
        "showMessage('Translation task not found'",
        "Loading AI analysis",
        "Loading PDF viewer",
    ):
        assert legacy not in sources
    for expected in ("查看日志", "取消翻译", "翻译任务不存在", "PDF 阅读器"):
        assert expected in sources
