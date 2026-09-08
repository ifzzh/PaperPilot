import io
import unittest
from contextlib import redirect_stdout

import app as app_module
from flask import g, jsonify

from paperpilot.auth import AuthConfig
from paperpilot.local_auth import LocalAuthError
from paperpilot.security.identity import Identity


if "test_auth_protected" not in app_module.app.view_functions:
    @app_module.app.route(
        "/api/test-auth-protected", methods=["GET", "POST"], endpoint="test_auth_protected"
    )
    def auth_protected_probe():
        return jsonify({"username": getattr(g, "username", None)})


class FakeAuthService:
    def authenticate(self, token):
        if token == "valid":
            return Identity("user-1", "ifzzh", "admin")
        if token == "change":
            return Identity("user-1", "ifzzh", "admin", True)
        return None

    def verify_csrf(self, token, csrf):
        return token in {"valid", "change"} and csrf == "csrf-valid"

    def login(self, username, password):
        if username != "ifzzh" or password != "temporary12":
            raise LocalAuthError("invalid_credentials")
        return ({"id": "user-1", "username": "ifzzh", "role": "admin", "must_change_password": True}, "valid", "csrf-valid")

    def logout(self, token):
        return None

    def change_password(self, *_args):
        return None


class TestAuthMiddleware(unittest.TestCase):
    def setUp(self):
        app_module.app.config.update(TESTING=True)
        app_module.AUTH_CONFIG = AuthConfig.from_environ(
            {"PAPERPILOT_ENV": "production", "PAPERPILOT_AUTH_MODE": "local"}
        )
        app_module.AUTH_SERVICE = FakeAuthService()
        app_module._rate_limiter.clear()
        self.client = app_module.app.test_client()

    def tearDown(self):
        app_module.AUTH_CONFIG = None
        app_module.AUTH_SERVICE = None
        app_module._rate_limiter.clear()

    def _authenticate(self, token="valid"):
        self.client.set_cookie(app_module.AUTH_COOKIE_NAME, token)

    def test_health_is_public(self):
        self.assertEqual(self.client.get("/healthz").status_code, 200)

    def test_sensitive_api_requires_session(self):
        for method, path in [
            ("GET", "/api/paper/example"), ("GET", "/api/categories"),
            ("POST", "/api/upload"), ("POST", "/api/settings/agentic"),
        ]:
            with self.subTest(method=method, path=path):
                self.assertEqual(self.client.open(path, method=method).status_code, 401)

    def test_cookie_authenticates_reads_and_csrf_protects_writes(self):
        self._authenticate()
        self.assertEqual(self.client.get("/api/test-auth-protected").status_code, 200)
        self.assertEqual(self.client.post("/api/test-auth-protected").status_code, 403)
        response = self.client.post(
            "/api/test-auth-protected", headers={"X-CSRF-Token": "csrf-valid"}
        )
        self.assertEqual(response.status_code, 200)

    def test_first_login_only_allows_password_change(self):
        self._authenticate("change")
        response = self.client.get("/api/test-auth-protected")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()["error"], "password_change_required")
        response = self.client.post(
            "/api/auth/change-password",
            json={"current_password": "old", "new_password": "a much safer password"},
            headers={"X-CSRF-Token": "csrf-valid"},
        )
        self.assertEqual(response.status_code, 200)

    def test_login_sets_session_and_csrf_cookies(self):
        response = self.client.post(
            "/api/auth/login", json={"username": "ifzzh", "password": "temporary12"}
        )
        self.assertEqual(response.status_code, 200)
        cookies = response.headers.getlist("Set-Cookie")
        self.assertTrue(any("paperpilot_session=valid" in value and "HttpOnly" in value for value in cookies))
        self.assertTrue(any("paperpilot_csrf=csrf-valid" in value and "HttpOnly" not in value for value in cookies))
        self.assertNotIn('"valid"', response.get_data(as_text=True))

    def test_viewer_without_session_redirects(self):
        response = self.client.get("/viewer/example")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/")

    def test_audit_log_does_not_include_cookie(self):
        captured = io.StringIO()
        with redirect_stdout(captured):
            response = self.client.post(
                "/api/test-auth-protected", headers={"Cookie": "paperpilot_session=secret"}
            )
        self.assertEqual(response.status_code, 401)
        self.assertNotIn("secret", captured.getvalue())

    def test_explicit_development_mode_sets_synthetic_admin(self):
        app_module.AUTH_CONFIG = AuthConfig.from_environ(
            {"PAPERPILOT_ENV": "development", "PAPERPILOT_AUTH_MODE": "disabled"}
        )
        response = self.client.get("/api/test-auth-protected")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"username": "development"})


if __name__ == "__main__":
    unittest.main()
