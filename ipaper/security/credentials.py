"""Encryption primitives for write-only iPaper credentials."""

from __future__ import annotations

import base64
import os
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


KEY_SIZE = 32
NONCE_SIZE = 12
ENVELOPE_VERSION = "v1"
ALLOWED_SECRET_NAMES = frozenset({"translate", "interpret", "dailyArxiv", "mineru"})


class CredentialError(RuntimeError):
    """Base error for encrypted settings credentials."""


class CredentialKeyError(CredentialError):
    """The configured settings key is absent or malformed."""


class CredentialDecryptionError(CredentialError):
    """A credential cannot be authenticated and decrypted."""


def _secret_aad(name: str, owner_id: str | None = None) -> bytes:
    if name not in ALLOWED_SECRET_NAMES:
        raise ValueError("unsupported_agentic_secret")
    suffix = f":{owner_id}" if owner_id else ""
    return f"paperpilot:agentic-secret:{ENVELOPE_VERSION}:{name}{suffix}".encode("ascii")


def generate_settings_key(path: str | os.PathLike[str]) -> Path:
    """Create a new key file without ever replacing an existing key."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o640)
    except FileExistsError as exc:
        raise CredentialKeyError("settings_key_already_exists") from exc
    try:
        os.write(descriptor, os.urandom(KEY_SIZE))
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return target


class SettingsCredentialCipher:
    def __init__(self, key: bytes):
        if len(key) != KEY_SIZE:
            raise CredentialKeyError("settings_key_must_be_32_bytes")
        self._cipher = AESGCM(key)

    @classmethod
    def from_file(cls, path: str | os.PathLike[str]) -> "SettingsCredentialCipher":
        try:
            key = Path(path).read_bytes()
        except OSError as exc:
            raise CredentialKeyError("settings_key_unreadable") from exc
        return cls(key)

    def encrypt(self, name: str, plaintext: str, *, owner_id: str | None = None) -> str:
        if not isinstance(plaintext, str) or not plaintext:
            raise ValueError("credential_must_not_be_empty")
        nonce = os.urandom(NONCE_SIZE)
        encrypted = self._cipher.encrypt(
            nonce, plaintext.encode("utf-8"), _secret_aad(name, owner_id)
        )
        payload = base64.urlsafe_b64encode(nonce + encrypted).decode("ascii").rstrip("=")
        return f"{ENVELOPE_VERSION}:{payload}"

    def decrypt(self, name: str, envelope: str, *, owner_id: str | None = None) -> str:
        try:
            version, encoded = envelope.split(":", 1)
            if version != ENVELOPE_VERSION:
                raise ValueError
            encoded += "=" * (-len(encoded) % 4)
            payload = base64.urlsafe_b64decode(encoded.encode("ascii"))
            if len(payload) <= NONCE_SIZE:
                raise ValueError
            value = self._cipher.decrypt(
                payload[:NONCE_SIZE], payload[NONCE_SIZE:], _secret_aad(name, owner_id)
            )
            return value.decode("utf-8")
        except (InvalidTag, UnicodeError, ValueError, TypeError) as exc:
            raise CredentialDecryptionError("credential_decryption_failed") from exc
