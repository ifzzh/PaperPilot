import tempfile
import unittest
from pathlib import Path

from flask import Flask

from paperpilot.database import connection
from paperpilot.database.db_manager import init_db_schema
from paperpilot.local_auth import (
    LocalAuthError,
    LocalAuthService,
    normalize_username,
    validate_password,
)


class TestLocalAuth(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.original_path = connection.DB_PATH
        connection.DB_PATH = str(Path(self.temp.name) / "paperpilot.db")
        init_db_schema(connection.DB_PATH)
        self.app = Flask(__name__)
        self.context = self.app.app_context()
        self.context.push()
        self.service = LocalAuthService(now=lambda: 1_700_000_000)

    def tearDown(self):
        connection.close_db()
        self.context.pop()
        connection.DB_PATH = self.original_path
        self.temp.cleanup()

    def test_bootstrap_login_and_session(self):
        admin = self.service.create_bootstrap_admin("IFZZH", "temporary12")
        self.assertEqual(admin["username"], "ifzzh")
        self.assertTrue(admin["must_change_password"])
        user, token, csrf = self.service.login("ifzzh", "temporary12")
        identity = self.service.authenticate(token)
        self.assertEqual(identity.user_id, user["id"])
        self.assertEqual(identity.role, "admin")
        self.assertTrue(self.service.verify_csrf(token, csrf))
        self.assertFalse(self.service.verify_csrf(token, "wrong"))

    def test_invite_is_single_use(self):
        admin = self.service.create_bootstrap_admin("ifzzh", "temporary12")
        _metadata, code = self.service.create_invite(admin["id"])
        created = self.service.register("reader_1", "correct horse battery", code)
        self.assertEqual(created["role"], "user")
        with self.assertRaisesRegex(LocalAuthError, "invalid_invite"):
            self.service.register("reader_2", "correct horse battery", code)

    def test_password_change_revokes_session(self):
        admin = self.service.create_bootstrap_admin("ifzzh", "temporary12")
        _user, token, _csrf = self.service.login("ifzzh", "temporary12")
        self.service.change_password(admin["id"], "temporary12", "a much safer password")
        self.assertIsNone(self.service.authenticate(token))
        user, _new_token, _csrf = self.service.login("ifzzh", "a much safer password")
        self.assertFalse(user["must_change_password"])

    def test_username_contract(self):
        self.assertEqual(normalize_username(" User_Name "), "user_name")
        for value in ("ab", "name@example.com", "空白", "has space"):
            with self.subTest(value=value), self.assertRaises(LocalAuthError):
                normalize_username(value)

    def test_password_contract_accepts_eight_characters(self):
        self.assertEqual(validate_password("12345678"), "12345678")
        self.assertEqual(validate_password("abcdefgh", temporary=True), "abcdefgh")
        for value in ("1234567", "a" * 129):
            with self.subTest(length=len(value)), self.assertRaisesRegex(
                LocalAuthError, "invalid_password"
            ):
                validate_password(value)

    def test_last_active_administrator_is_protected(self):
        admin = self.service.create_bootstrap_admin("ifzzh", "temporary12")
        with self.assertRaisesRegex(LocalAuthError, "last_administrator_required"):
            self.service.update_user(
                admin["id"], admin["id"], role="user", status="active"
            )

    def test_password_reset_is_single_use(self):
        admin = self.service.create_bootstrap_admin("ifzzh", "temporary12")
        _metadata, code = self.service.create_password_reset(admin["id"], admin["id"])
        self.service.reset_password(code, "replacement password")
        with self.assertRaisesRegex(LocalAuthError, "invalid_reset_code"):
            self.service.reset_password(code, "another replacement")


if __name__ == "__main__":
    unittest.main()
