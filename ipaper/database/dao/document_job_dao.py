from __future__ import annotations

from datetime import datetime, timezone

from ..connection import get_db
from ipaper.security.identity import current_user_id


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class DocumentJobDAO:
    @staticmethod
    def create(job_id: str, kind: str, paper_id: str | None = None) -> None:
        now = _now()
        db = get_db()
        db.execute(
            "INSERT INTO document_jobs (job_id,owner_id,kind,paper_id,status,progress,created_at,updated_at) VALUES (?,?,?,?,'queued',0,?,?)",
            (job_id, current_user_id(), kind, paper_id, now, now),
        )
        db.commit()

    @staticmethod
    def update(job_id: str, status: str, *, progress=None, error=None, paper_id=None) -> None:
        completed = _now() if status in {"completed", "failed", "cancelled"} else None
        db = get_db()
        db.execute(
            """UPDATE document_jobs SET status=?, progress=COALESCE(?,progress),
               error=?, paper_id=COALESCE(?,paper_id), updated_at=?,
               completed_at=COALESCE(?,completed_at) WHERE job_id=? AND owner_id=?""",
            (status, progress, error, paper_id, _now(), completed, job_id, current_user_id()),
        )
        db.commit()

    @staticmethod
    def get(job_id: str) -> dict | None:
        row = get_db().execute("SELECT * FROM document_jobs WHERE job_id=? AND owner_id=?", (job_id, current_user_id())).fetchone()
        return dict(row) if row else None

    @staticmethod
    def list_active() -> list[dict]:
        rows = get_db().execute(
            "SELECT * FROM document_jobs WHERE owner_id=? AND status IN ('queued','running') ORDER BY created_at",
            (current_user_id(),),
        ).fetchall()
        return [dict(row) for row in rows]
