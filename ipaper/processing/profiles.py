"""Separate credential purpose/table so 1.1.4 can still boot after rollback."""
from __future__ import annotations

import base64
import os

from cryptography.exceptions import InvalidTag
from ipaper.security.credentials import SettingsCredentialCipher, CredentialDecryptionError
from .common import ProcessingError, identifier, now


class StructuredCredentialCipher(SettingsCredentialCipher):
    @staticmethod
    def _aad(owner):
        return ("ipaper:structured-translation-secret:v1:" + identifier(owner)).encode("ascii")

    def validate_all(self, database):
        """Check the separate purpose before binding, without changing old tables."""
        import sqlite3
        from pathlib import Path
        with sqlite3.connect(Path(database).resolve().as_uri()+"?mode=ro",uri=True) as db:
            for owner,envelope in db.execute("SELECT owner_id,secret_envelope FROM processing_profiles WHERE secret_envelope IS NOT NULL"):
                self.open(owner,envelope)

    def seal(self, owner, plaintext):
        if not isinstance(plaintext, str) or not 0 < len(plaintext) <= 16384:
            raise ProcessingError("invalid_model_key")
        nonce = os.urandom(12)
        data = nonce + self._cipher.encrypt(nonce, plaintext.encode(), self._aad(owner))
        return "v1:" + base64.urlsafe_b64encode(data).decode()

    def open(self, owner, envelope):
        try:
            version, data = envelope.split(":", 1)
            if version != "v1":
                raise ValueError()
            data = base64.b64decode(data, altchars=b"-_", validate=True)
            return self._cipher.decrypt(data[:12], data[12:], self._aad(owner)).decode()
        except (InvalidTag, ValueError, TypeError, UnicodeError) as exc:
            raise CredentialDecryptionError("structured_credential_decryption_failed") from exc


class StructuredProfiles:
    def __init__(self, store, cipher):
        self.store, self.cipher = store, cipher

    def get(self, *, secret=False):
        with self.store.connection() as db:
            row = db.execute("SELECT * FROM processing_profiles WHERE owner_id=?", (self.store.owner,)).fetchone()
        if not row:
            return {"model": "", "baseUrl": "", "keyConfigured": False, "revision": None}
        value = {"model": row["model"], "baseUrl": row["base_url"], "revision": row["revision"],
                 "keyConfigured": bool(row["secret_envelope"])}
        if secret:
            value["key"] = self.cipher.open(self.store.owner, row["secret_envelope"]) if row["secret_envelope"] else ""
        return value

    def save(self, model, base_url, *, key=None, clear_key=False, only_if_absent=False):
        if (not isinstance(model, str) or not 0 < len(model.strip()) <= 200
                or not isinstance(base_url, str) or not 0 < len(base_url.strip()) <= 2048):
            raise ProcessingError("invalid_model_config")
        # URL resolution/outbound policy validation belongs to the route before
        # saving and the transport on every request. No URL is fetched here.
        with self.store.connection(write=True) as db:
            previous = db.execute("SELECT * FROM processing_profiles WHERE owner_id=?", (self.store.owner,)).fetchone()
            if previous and only_if_absent:
                return False
            if previous and key is None and not clear_key and previous["model"]==model.strip() and previous["base_url"]==base_url.strip():
                return False
            envelope = previous["secret_envelope"] if previous else None
            if clear_key:
                envelope = None
            elif key is not None:
                envelope = self.cipher.seal(self.store.owner, key)
            stamp = now()
            db.execute("""INSERT INTO processing_profiles VALUES (?,?,?,?,?,?,?)
                ON CONFLICT(owner_id) DO UPDATE SET model=excluded.model,base_url=excluded.base_url,
                secret_envelope=excluded.secret_envelope,revision=excluded.revision,updated_at=excluded.updated_at""",
                (self.store.owner, model.strip(), base_url.strip(), envelope, identifier(), stamp, stamp))
            return True

    def initialize_from_babeldoc(self, settings, credential_store):
        if self.get()["revision"]:
            return False
        config = settings.get("llmConfigs", {}).get("translate", {})
        model = config.get("llmModel") or settings.get("llmModel") or ""
        base = config.get("llmBaseUrl") or settings.get("llmBaseUrl") or ""
        # Plaintext exists solely in server process memory for this operation.
        return self.save(model, base, key=credential_store.get("translate") or None, only_if_absent=True)
