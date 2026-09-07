import ipaddress
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from paperpilot.security.credentials import (
    CredentialDecryptionError,
    CredentialKeyError,
    SettingsCredentialCipher,
    generate_settings_key,
)
from paperpilot.security.outbound import (
    OutboundPolicy,
    OutboundPolicyError,
)


class SettingsCredentialCipherTests(unittest.TestCase):
    def test_round_trip_is_bound_to_secret_name_and_hides_plaintext(self):
        with tempfile.TemporaryDirectory() as directory:
            key_path = Path(directory) / "settings.key"
            generate_settings_key(key_path)
            cipher = SettingsCredentialCipher.from_file(key_path)

            envelope = cipher.encrypt("translate", "sk-super-secret")

            self.assertNotIn("sk-super-secret", envelope)
            self.assertTrue(envelope.startswith("v1:"))
            self.assertEqual(cipher.decrypt("translate", envelope), "sk-super-secret")
            with self.assertRaises(CredentialDecryptionError):
                cipher.decrypt("interpret", envelope)

    def test_tampered_ciphertext_and_wrong_key_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "first.key"
            second = Path(directory) / "second.key"
            generate_settings_key(first)
            generate_settings_key(second)
            envelope = SettingsCredentialCipher.from_file(first).encrypt("mineru", "token")

            with self.assertRaises(CredentialDecryptionError):
                SettingsCredentialCipher.from_file(first).decrypt("mineru", envelope[:-2] + "AA")
            with self.assertRaises(CredentialDecryptionError):
                SettingsCredentialCipher.from_file(second).decrypt("mineru", envelope)

    def test_missing_or_invalid_key_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "missing.key"
            with self.assertRaises(CredentialKeyError):
                SettingsCredentialCipher.from_file(missing)
            missing.write_text("not-a-key", encoding="utf-8")
            with self.assertRaises(CredentialKeyError):
                SettingsCredentialCipher.from_file(missing)


class OutboundPolicyTests(unittest.TestCase):
    def _resolve(self, mapping):
        def resolver(host, _port, type=0):
            return [
                (2, 1, 6, "", (address, 0))
                for address in mapping[host]
            ]
        return resolver

    def test_public_https_origin_must_be_exactly_allowed(self):
        policy = OutboundPolicy(
            public_origins={"https://api.example.test"},
            private_origins=set(),
            transfer_origins=set(),
        )
        resolver = self._resolve({"api.example.test": ["8.8.8.8"]})
        with patch("paperpilot.security.outbound.socket.getaddrinfo", resolver):
            target = policy.validate("https://api.example.test/v1/chat?x=1", purpose="ai")
            self.assertEqual(target.origin, "https://api.example.test")
        with self.assertRaisesRegex(OutboundPolicyError, "origin_not_allowed"):
            policy.validate("https://other.example.test/v1", purpose="ai")

    def test_private_origin_requires_private_allowlist(self):
        resolver = self._resolve({"mineru": ["172.20.0.4"]})
        denied = OutboundPolicy(
            public_origins={"https://mineru:8000"},
            private_origins=set(),
            transfer_origins=set(),
        )
        allowed = OutboundPolicy(
            public_origins=set(),
            private_origins={"http://mineru:8000"},
            transfer_origins=set(),
        )
        with patch("paperpilot.security.outbound.socket.getaddrinfo", resolver):
            with self.assertRaisesRegex(OutboundPolicyError, "private_address_forbidden"):
                denied.validate("https://mineru:8000/health", purpose="ai")
            self.assertEqual(
                allowed.validate("http://mineru:8000/health", purpose="ai").origin,
                "http://mineru:8000",
            )

    def test_dangerous_address_classes_are_always_rejected(self):
        policy = OutboundPolicy(
            public_origins=set(),
            private_origins={
                "http://localhost:8000",
                "http://metadata.test",
                "http://multicast.test",
            },
            transfer_origins=set(),
        )
        resolver = self._resolve(
            {
                "localhost": ["127.0.0.1"],
                "metadata.test": ["169.254.169.254"],
                "multicast.test": ["224.0.0.1"],
            }
        )
        with patch("paperpilot.security.outbound.socket.getaddrinfo", resolver):
            for url in (
                "http://localhost:8000",
                "http://metadata.test/latest/meta-data",
                "http://multicast.test",
            ):
                with self.subTest(url=url), self.assertRaises(OutboundPolicyError):
                    policy.validate(url, purpose="ai")

    def test_credentials_fragments_controls_and_mixed_dns_are_rejected(self):
        policy = OutboundPolicy(
            public_origins={"https://api.example.test"},
            private_origins=set(),
            transfer_origins=set(),
        )
        resolver = self._resolve(
            {"api.example.test": ["8.8.8.8", "10.0.0.8"]}
        )
        with patch("paperpilot.security.outbound.socket.getaddrinfo", resolver):
            cases = (
                "https://user:pass@api.example.test/v1",
                "https://api.example.test/v1#fragment",
                "https://api.example.test/\ninternal",
                "https://api.example.test/v1",
            )
            for url in cases:
                with self.subTest(url=url), self.assertRaises(OutboundPolicyError):
                    policy.validate(url, purpose="ai")

    def test_transfer_urls_use_separate_allowlist(self):
        policy = OutboundPolicy(
            public_origins={"https://api.example.test"},
            private_origins=set(),
            transfer_origins={"https://objects.example.test"},
        )
        resolver = self._resolve({"objects.example.test": ["1.1.1.1"]})
        with patch("paperpilot.security.outbound.socket.getaddrinfo", resolver):
            self.assertEqual(
                policy.validate("https://objects.example.test/result.zip", purpose="transfer").origin,
                "https://objects.example.test",
            )
            with self.assertRaisesRegex(OutboundPolicyError, "origin_not_allowed"):
                policy.validate("https://objects.example.test/result.zip", purpose="ai")

    def test_ip_classification_matches_contract(self):
        self.assertTrue(ipaddress.ip_address("8.8.8.8").is_global)
        self.assertTrue(ipaddress.ip_address("10.0.0.1").is_private)


if __name__ == "__main__":
    unittest.main()
