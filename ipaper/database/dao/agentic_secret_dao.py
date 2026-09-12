from __future__ import annotations

from datetime import datetime, timezone

from ipaper.database.connection import get_db
from ipaper.security.identity import current_user_id


class AgenticSecretDAO:
    @staticmethod
    def get_envelope(name: str, owner_id: str | None = None) -> str | None:
        owner_id = owner_id or current_user_id()
        row = get_db().execute(
            "SELECT ciphertext FROM agentic_secrets_v2 WHERE owner_id=? AND name=?",
            (owner_id, name),
        ).fetchone()
        return str(row["ciphertext"]) if row else None

    @staticmethod
    def list_envelopes() -> list[tuple[str, str, str]]:
        rows = get_db().execute(
            "SELECT owner_id,name,ciphertext FROM agentic_secrets_v2 ORDER BY owner_id,name"
        ).fetchall()
        return [(str(row["owner_id"]), str(row["name"]), str(row["ciphertext"])) for row in rows]

    @staticmethod
    def save_envelope(name: str, ciphertext: str, owner_id: str | None = None) -> None:
        owner_id = owner_id or current_user_id()
        now = datetime.now(timezone.utc).isoformat()
        database = get_db()
        database.execute(
            """
            INSERT INTO agentic_secrets_v2(owner_id,name,ciphertext,created_at,updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(owner_id,name) DO UPDATE SET
                ciphertext = excluded.ciphertext,
                updated_at = excluded.updated_at
            """,
            (owner_id, name, ciphertext, now, now),
        )
        database.commit()

    @staticmethod
    def delete(name: str, owner_id: str | None = None) -> None:
        owner_id = owner_id or current_user_id()
        database = get_db()
        database.execute(
            "DELETE FROM agentic_secrets_v2 WHERE owner_id=? AND name=?", (owner_id, name)
        )
        database.commit()
