import socket
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from flask import Flask

from ipaper.database import connection
from ipaper.database.db_manager import init_db_schema
from ipaper.security.identity import Identity, reset_background_identity, set_background_identity
from ipaper.security.outbound import DynamicOutboundPolicy, OutboundPolicyError


PUBLIC_DNS = [
    (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443)),
]
PRIVATE_DNS = [
    (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443)),
]


class TestDynamicAiProviders(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.original_path = connection.DB_PATH
        connection.DB_PATH = str(Path(self.temp.name) / "ipaper.db")
        init_db_schema(connection.DB_PATH)
        self.app = Flask(__name__)
        self.context = self.app.app_context()
        self.context.push()
        self.admin_id = str(uuid.uuid4())
        self.policy = DynamicOutboundPolicy(
            public_origins=(), private_origins=(), transfer_origins=()
        )

    def tearDown(self):
        connection.close_db()
        self.context.pop()
        connection.DB_PATH = self.original_path
        self.temp.cleanup()

    def _as(self, role):
        return set_background_identity(Identity(self.admin_id, role, role))

    @patch("ipaper.security.outbound.socket.getaddrinfo", return_value=PUBLIC_DNS)
    def test_admin_can_approve_path_url_and_it_is_immediately_allowed(self, _dns):
        token = self._as("admin")
        try:
            provider = self.policy.approve_public_url(
                "https://ws.example.com/compatible-mode/v1", name="Aliyun"
            )
            self.assertEqual(provider["origin"], "https://ws.example.com")
            target = self.policy.validate(
                "https://ws.example.com/compatible-mode/v1/chat/completions"
            )
            self.assertEqual(target.origin, "https://ws.example.com")
            self.assertEqual(self.policy.list_providers()[0]["name"], "Aliyun")
        finally:
            reset_background_identity(token)

    @patch("ipaper.security.outbound.socket.getaddrinfo", return_value=PUBLIC_DNS)
    def test_regular_user_cannot_approve_provider(self, _dns):
        token = self._as("user")
        try:
            with self.assertRaisesRegex(OutboundPolicyError, "administrator_required"):
                self.policy.approve_public_url("https://new.example.com/v1")
        finally:
            reset_background_identity(token)

    @patch("ipaper.security.outbound.socket.getaddrinfo", return_value=PRIVATE_DNS)
    def test_admin_cannot_approve_loopback_or_private_destination(self, _dns):
        token = self._as("admin")
        try:
            with self.assertRaisesRegex(OutboundPolicyError, "dangerous_address_forbidden"):
                self.policy.approve_public_url("https://localhost.example/v1")
        finally:
            reset_background_identity(token)


if __name__ == "__main__":
    unittest.main()
