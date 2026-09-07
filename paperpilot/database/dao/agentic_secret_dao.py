from __future__ import annotations

from datetime import datetime, timezone

from paperpilot.database.connection import get_db


class AgenticSecretDAO:
    @staticmethod
    def get_envelope(name: str) -> str | None:
        row = get_db().execute(
            "SELECT ciphertext FROM agentic_secrets WHERE name = ?", (name,)
        ).fetchone()
        return str(row["ciphertext"]) if row else None

    @staticmethod
    def list_envelopes() -> dict[str, str]:
        rows = get_db().execute(
            "SELECT name, ciphertext FROM agentic_secrets ORDER BY name"
        ).fetchall()
        return {str(row["name"]): str(row["ciphertext"]) for row in rows}

    @staticmethod
    def save_envelope(name: str, ciphertext: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        database = get_db()
        database.execute(
            """
            INSERT INTO agentic_secrets(name, ciphertext, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                ciphertext = excluded.ciphertext,
                updated_at = excluded.updated_at
            """,
            (name, ciphertext, now, now),
        )
        database.commit()

    @staticmethod
    def delete(name: str) -> None:
        database = get_db()
        database.execute("DELETE FROM agentic_secrets WHERE name = ?", (name,))
        database.commit()
