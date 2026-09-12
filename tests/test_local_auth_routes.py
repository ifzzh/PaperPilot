import tempfile
import unittest
from pathlib import Path

import app as app_module

from ipaper.auth import AuthConfig
from ipaper.database import connection
from ipaper.database.db_manager import init_db_schema
from ipaper.local_auth import LocalAuthService


class TestLocalAuthRoutes(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.original_db = connection.DB_PATH
        connection.DB_PATH = str(Path(self.temp.name) / "ipaper.db")
        init_db_schema(connection.DB_PATH)
        app_module.app.config.update(TESTING=True)
        app_module.AUTH_CONFIG = AuthConfig.from_environ({
            "IPAPER_ENV": "production", "IPAPER_AUTH_MODE": "local",
        })
        with app_module.app.app_context():
            service = LocalAuthService()
            self.admin = service.create_bootstrap_admin("first_admin", "temporary-pass")
            connection.get_db().execute(
                "UPDATE users SET must_change_password=0 WHERE id=?", (self.admin["id"],)
            )
            connection.get_db().commit()
        app_module.AUTH_SERVICE = LocalAuthService()
        self.client = app_module.app.test_client()

    def tearDown(self):
        connection.close_db()
        connection.DB_PATH = self.original_db
        app_module.AUTH_CONFIG = None
        app_module.AUTH_SERVICE = None
        self.temp.cleanup()

    def _login(self, username="first_admin", password="temporary-pass"):
        response = self.client.post(
            "/api/auth/login", json={"username": username, "password": password}
        )
        self.assertEqual(response.status_code, 200)
        return response.get_json()["csrf_token"]

    def test_cookie_session_requires_csrf_for_writes(self):
        csrf = self._login()
        self.assertEqual(self.client.get("/api/auth/session").status_code, 200)
        self.assertEqual(self.client.post("/api/admin/invites").status_code, 403)
        created = self.client.post(
            "/api/admin/invites", headers={"X-CSRF-Token": csrf}
        )
        self.assertEqual(created.status_code, 201)
        self.assertIn("invite_code", created.get_json())

    def test_invite_registers_regular_user_once(self):
        csrf = self._login()
        invite = self.client.post(
            "/api/admin/invites", headers={"X-CSRF-Token": csrf}
        ).get_json()["invite_code"]
        self.client.delete(
            "/api/auth/session", headers={"X-CSRF-Token": csrf}
        )
        registration = self.client.post("/api/auth/register", json={
            "username": "reader_one", "password": "long-reader-password",
            "invite_code": invite,
        })
        self.assertEqual(registration.status_code, 201)
        replay = self.client.post("/api/auth/register", json={
            "username": "reader_two", "password": "long-reader-password",
            "invite_code": invite,
        })
        self.assertEqual(replay.status_code, 400)
        self.assertEqual(replay.get_json()["error"], "registration_failed")
        login = self.client.post("/api/auth/login", json={
            "username": "reader_one", "password": "long-reader-password",
        })
        self.assertEqual(login.get_json()["user"]["role"], "user")

    def test_registration_failures_do_not_reveal_username_or_invite_state(self):
        csrf = self._login()
        invite = self.client.post(
            "/api/admin/invites", headers={"X-CSRF-Token": csrf}
        ).get_json()["invite_code"]
        self.client.delete("/api/auth/session", headers={"X-CSRF-Token": csrf})
        created = self.client.post("/api/auth/register", json={
            "username": "reader_one", "password": "long-reader-password",
            "invite_code": invite,
        })
        self.assertEqual(created.status_code, 201)

        for payload in (
            {"username": "reader_one", "password": "long-reader-password", "invite_code": "invalid"},
            {"username": "reader_two", "password": "long-reader-password", "invite_code": "invalid"},
        ):
            with self.subTest(username=payload["username"]):
                response = self.client.post("/api/auth/register", json=payload)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.get_json(), {"error": "registration_failed"})

    def test_bootstrap_user_is_restricted_until_password_change(self):
        with app_module.app.app_context():
            connection.get_db().execute(
                "UPDATE users SET must_change_password=1 WHERE id=?", (self.admin["id"],)
            )
            connection.get_db().commit()
        csrf = self._login()
        blocked = self.client.get("/api/admin/users")
        self.assertEqual(blocked.status_code, 403)
        self.assertEqual(blocked.get_json()["error"], "password_change_required")
        changed = self.client.post(
            "/api/auth/change-password",
            headers={"X-CSRF-Token": csrf},
            json={"current_password": "temporary-pass", "new_password": "replacement-password"},
        )
        self.assertEqual(changed.status_code, 200)
        payload = changed.get_json()
        self.assertFalse(payload["reauthenticate"])
        self.assertFalse(payload["user"]["must_change_password"])
        session = self.client.get("/api/auth/session").get_json()
        self.assertTrue(session["authenticated"])
        self.assertFalse(session["user"]["must_change_password"])


if __name__ == "__main__":
    unittest.main()
