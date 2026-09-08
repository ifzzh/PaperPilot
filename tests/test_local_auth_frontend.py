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
