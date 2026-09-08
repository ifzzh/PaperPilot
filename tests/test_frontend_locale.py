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
