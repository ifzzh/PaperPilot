"""Application-facing encrypted credential store."""

from __future__ import annotations

from paperpilot.database.dao.agentic_secret_dao import AgenticSecretDAO
from paperpilot.security.credentials import (
    ALLOWED_SECRET_NAMES,
    SettingsCredentialCipher,
)
from paperpilot.security.identity import current_user_id


class AgenticCredentialStore:
    def __init__(self, cipher: SettingsCredentialCipher):
        self._cipher = cipher

    @classmethod
    def from_key_file(cls, path: str) -> "AgenticCredentialStore":
        return cls(SettingsCredentialCipher.from_file(path))

    def configured(self, name: str) -> bool:
        self._validate_name(name)
        return AgenticSecretDAO.get_envelope(name) is not None

    def get(self, name: str) -> str:
        self._validate_name(name)
        envelope = AgenticSecretDAO.get_envelope(name)
        if envelope is None:
            return ""
        return self._cipher.decrypt(name, envelope, owner_id=current_user_id())

    def set(self, name: str, plaintext: str) -> None:
        self._validate_name(name)
        owner_id = current_user_id()
        AgenticSecretDAO.save_envelope(
            name, self._cipher.encrypt(name, plaintext, owner_id=owner_id), owner_id
        )

    def clear(self, name: str) -> None:
        self._validate_name(name)
        AgenticSecretDAO.delete(name)

    def validate_all(self) -> None:
        for owner_id, name, envelope in AgenticSecretDAO.list_envelopes():
            self._validate_name(name)
            self._cipher.decrypt(name, envelope, owner_id=owner_id)

    @staticmethod
    def _validate_name(name: str) -> None:
        if name not in ALLOWED_SECRET_NAMES:
            raise ValueError("unsupported_agentic_secret")
