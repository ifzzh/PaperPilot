from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_frontend_uses_local_cookie_session_without_supabase_or_bearer_tokens():
    index = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    auth = (ROOT / "static" / "js" / "auth.js").read_text(encoding="utf-8")
    viewer_patch = (ROOT / "static" / "js" / "api_auth_patch.js").read_text(encoding="utf-8")

    combined = "\n".join((index, auth, viewer_patch)).lower()
    assert "supabase" not in combined
    assert "authorization" not in auth.lower()
    assert "paperpilot_csrf" in auth
    assert "x-csrf-token" in auth.lower()


def test_login_registration_password_change_and_admin_views_are_present():
    index = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    auth = (ROOT / "static" / "js" / "auth.js").read_text(encoding="utf-8")

    for element_id in (
        "auth-username", "auth-invite", "auth-new-password",
        "account-password-form", "account-current-password",
        "account-new-password", "account-confirm-password",
        "admin-users-body", "admin-invites-body", "admin-providers-body",
    ):
        assert f'id="{element_id}"' in index
    for endpoint in (
        "/api/auth/login", "/api/auth/register", "/api/auth/change-password",
        "/api/admin/invites", "/api/admin/users", "/api/admin/ai-providers",
    ):
        assert endpoint in auth


def test_dynamic_admin_tables_insert_server_values_as_text_only():
    auth = (ROOT / "static" / "js" / "auth.js").read_text(encoding="utf-8")
    assert "cell.textContent = String(value ?? '')" in auth
    assert ".innerHTML" not in auth


def test_translation_task_center_uses_durable_api_and_readable_logs():
    index = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    app = (ROOT / "static" / "js" / "app.js").read_text(encoding="utf-8")
    styles = (ROOT / "static" / "css" / "style.css").read_text(encoding="utf-8")

    for element_id in ("translation-center-view", "translation-task-list", "translation-task-count"):
        assert f'id="{element_id}"' in index
    for endpoint in (
        "/api/translations?limit=200",
        "/api/translations/${jobId}/${action}",
        "/queue-position",
    ):
        assert endpoint in app
    assert "new EventSource('/api/translations/events')" in app
    assert ".translation-raw-log" in styles
    assert "white-space: pre;" in styles


def test_paper_log_button_falls_back_to_latest_persisted_terminal_task():
    app = (ROOT / "static" / "js" / "app.js").read_text(encoding="utf-8")

    assert "latestTranslationTaskByPaper" in app
    assert "latestTranslationTaskForPaper(paperId)" in app
    assert "status?.taskId || latestTask?.job_id" in app
    assert "babeldoc_failed: 'BabelDOC 翻译失败，请查看日志后重试'" in app
