import unittest
from unittest.mock import patch

import app as app_module
from flask import g, jsonify

from paperpilot.auth import AuthConfig


if "test_auth_protected" not in app_module.app.view_functions:
    @app_module.app.route("/api/test-auth-protected", methods=["GET", "POST"])
    def test_auth_protected():
        return jsonify({"email": getattr(g, "user_email", None)})


class TestAuthMiddleware(unittest.TestCase):
    def setUp(self):
        app_module.app.config.update(TESTING=True)
        app_module.AUTH_CONFIG = AuthConfig.from_environ(
            {
                "PAPERPILOT_ENV": "production",
                "PAPERPILOT_AUTH_MODE": "supabase",
                "SUPABASE_URL": "https://example.supabase.co",
                "SUPABASE_ANON_KEY": "public-key",
                "PAPERPILOT_ALLOWED_EMAILS": "admin@example.com",
            }
        )
        app_module._auth_cache.clear()
        self.client = app_module.app.test_client()

    def tearDown(self):
        app_module.AUTH_CONFIG = None
        app_module._auth_cache.clear()

    def test_health_endpoint_is_public(self):
        response = self.client.get("/healthz")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"status": "ok"})

    def test_former_paper_prefix_whitelist_requires_auth(self):
        response = self.client.get("/api/paper/example/file")
        self.assertEqual(response.status_code, 401)

    def test_former_category_prefix_whitelist_requires_auth(self):
        response = self.client.delete("/api/categories/example")
        self.assertEqual(response.status_code, 401)

    def test_missing_runtime_configuration_does_not_fail_open(self):
        app_module.AUTH_CONFIG = None
        response = self.client.get("/api/test-auth-protected")
        self.assertEqual(response.status_code, 503)

    def test_invalid_token_is_rejected(self):
        with patch.object(app_module, "_verify_supabase_access_token", return_value=None):
            response = self.client.get(
                "/api/test-auth-protected",
                headers={"Authorization": "Bearer invalid"},
            )
        self.assertEqual(response.status_code, 401)

    def test_authenticated_but_unlisted_user_is_forbidden(self):
        with patch.object(
            app_module,
            "_verify_supabase_access_token",
            return_value="outsider@example.com",
        ):
            response = self.client.get(
                "/api/test-auth-protected",
                headers={"Authorization": "Bearer valid"},
            )
        self.assertEqual(response.status_code, 403)

    def test_allowed_administrator_reaches_endpoint(self):
        with patch.object(
            app_module,
            "_verify_supabase_access_token",
            return_value="admin@example.com",
        ):
            response = self.client.get(
                "/api/test-auth-protected",
                headers={"Authorization": "Bearer valid"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"email": "admin@example.com"})

    def test_session_post_sets_http_only_cookie(self):
        with patch.object(
            app_module,
            "_verify_supabase_access_token",
            return_value="admin@example.com",
        ):
            response = self.client.post(
                "/api/auth/session",
                headers={"Authorization": "Bearer valid"},
            )
        self.assertEqual(response.status_code, 200)
        cookie = response.headers["Set-Cookie"]
        self.assertIn(f"{app_module.AUTH_COOKIE_NAME}=valid", cookie)
        self.assertIn("HttpOnly", cookie)
        self.assertIn("Secure", cookie)
        self.assertIn("SameSite=Lax", cookie)
        self.assertNotIn("valid", response.get_data(as_text=True))

    def test_cookie_can_authenticate_safe_request(self):
        self.client.set_cookie(app_module.AUTH_COOKIE_NAME, "valid")
        with patch.object(
            app_module,
            "_verify_supabase_access_token",
            return_value="admin@example.com",
        ):
            response = self.client.get("/api/test-auth-protected")
        self.assertEqual(response.status_code, 200)

    def test_cookie_cannot_authenticate_unsafe_request(self):
        self.client.set_cookie(app_module.AUTH_COOKIE_NAME, "valid")
        response = self.client.post("/api/test-auth-protected")
        self.assertEqual(response.status_code, 401)

    def test_viewer_without_session_redirects_to_login(self):
        response = self.client.get("/viewer/example")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/")

    def test_session_delete_clears_cookie(self):
        response = self.client.delete("/api/auth/session")
        self.assertEqual(response.status_code, 200)
        self.assertIn(f"{app_module.AUTH_COOKIE_NAME}=", response.headers["Set-Cookie"])
        self.assertIn("Max-Age=0", response.headers["Set-Cookie"])

    def test_explicit_development_mode_can_bypass_auth(self):
        app_module.AUTH_CONFIG = AuthConfig.from_environ(
            {
                "PAPERPILOT_ENV": "development",
                "PAPERPILOT_AUTH_MODE": "disabled",
            }
        )
        response = self.client.get("/api/test-auth-protected")
        self.assertEqual(response.status_code, 200)


if __name__ == "__main__":
    unittest.main()
