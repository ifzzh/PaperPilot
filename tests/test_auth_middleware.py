import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import app as app_module
from flask import g, jsonify

from paperpilot.auth import AuthConfig


if "test_auth_protected" not in app_module.app.view_functions:
    @app_module.app.route(
        "/api/test-auth-protected",
        methods=["GET", "POST"],
        endpoint="test_auth_protected",
    )
    def auth_protected_probe():
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
        app_module._rate_limiter.clear()
        self.client = app_module.app.test_client()

    def tearDown(self):
        app_module.AUTH_CONFIG = None
        app_module._auth_cache.clear()
        app_module._rate_limiter.clear()

    def test_health_endpoint_is_public(self):
        response = self.client.get("/healthz")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"status": "ok"})

    def test_readiness_endpoint_is_public(self):
        with patch.object(app_module.TranslationWorkerClient, "health", return_value=False), patch.object(
            app_module.DocumentWorkerClient, "health", return_value=False
        ):
            response = self.client.get("/readyz")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json()["status"], "not_ready")

    def test_former_paper_prefix_whitelist_requires_auth(self):
        response = self.client.get("/api/paper/example/file")
        self.assertEqual(response.status_code, 401)

    def test_former_category_prefix_whitelist_requires_auth(self):
        response = self.client.delete("/api/categories/example")
        self.assertEqual(response.status_code, 401)

    def test_sensitive_api_matrix_requires_auth(self):
        requests = [
            ("GET", "/api/paper/example"),
            ("PUT", "/api/paper/example"),
            ("DELETE", "/api/paper/example"),
            ("PUT", "/api/paper/example/move"),
            ("GET", "/api/paper/example/file"),
            ("GET", "/api/paper/example/chinese/file"),
            ("GET", "/api/paper/example/analysis/result"),
            ("POST", "/api/paper/analyze"),
            ("GET", "/api/paper/analyze/task/logs"),
            ("POST", "/api/paper/translate"),
            ("POST", "/api/paper/chat"),
            ("DELETE", "/api/paper/chat/session"),
            ("GET", "/api/categories"),
            ("POST", "/api/categories"),
            ("DELETE", "/api/categories/example"),
            ("PUT", "/api/categories/example/move"),
            ("GET", "/api/settings/agentic"),
            ("POST", "/api/settings/agentic"),
            ("POST", "/api/upload"),
            ("POST", "/api/upload/arxiv"),
            ("POST", "/api/import/from-export"),
            ("POST", "/api/export/start"),
            ("GET", "/api/export/download/task"),
            ("GET", "/api/papers-dir"),
        ]
        for method, path in requests:
            with self.subTest(method=method, path=path):
                response = self.client.open(path, method=method)
                self.assertEqual(response.status_code, 401)

    def test_papers_directory_endpoint_does_not_disclose_a_path(self):
        with patch.object(
            app_module,
            "_verify_supabase_access_token",
            return_value="admin@example.com",
        ):
            response = self.client.get(
                "/api/papers-dir",
                headers={"Authorization": "Bearer valid"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"success": True, "storage": "managed"})

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

    def test_supabase_outage_is_fail_closed(self):
        with patch.object(app_module.requests, "get", side_effect=TimeoutError):
            response = self.client.get(
                "/api/test-auth-protected",
                headers={"Authorization": "Bearer valid"},
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

    def test_auth_session_is_rate_limited_by_ip(self):
        with patch.object(
            app_module,
            "_verify_supabase_access_token",
            return_value="admin@example.com",
        ):
            responses = [
                self.client.post(
                    "/api/auth/session",
                    headers={"Authorization": "Bearer valid"},
                )
                for _ in range(11)
            ]
        self.assertTrue(all(response.status_code == 200 for response in responses[:10]))
        self.assertEqual(responses[10].status_code, 429)
        self.assertGreaterEqual(int(responses[10].headers["Retry-After"]), 1)

    def test_audit_log_does_not_include_bearer_token(self):
        captured = io.StringIO()
        with redirect_stdout(captured):
            response = self.client.post(
                "/api/test-auth-protected",
                headers={"Authorization": "Bearer super-secret-token"},
            )
        self.assertEqual(response.status_code, 401)
        combined = captured.getvalue()
        self.assertIn('"event": "api_audit"', combined)
        self.assertIn('"reason": "invalid_token"', combined)
        self.assertNotIn("super-secret-token", combined)

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
