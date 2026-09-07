from __future__ import annotations

from datetime import datetime, timezone

from ..connection import get_db


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class TranslationJobDAO:
    @staticmethod
    def create(job_id: str, paper_id: str) -> None:
        now = _now()
        db = get_db()
        db.execute(
            """
            INSERT INTO translation_jobs
                (job_id, paper_id, status, progress, created_at, updated_at)
            VALUES (?, ?, 'queued', 0, ?, ?)
            """,
            (job_id, paper_id, now, now),
        )
        db.commit()

    @staticmethod
    def update(
        job_id: str,
        status: str,
        *,
        progress: int | None = None,
        error: str | None = None,
    ) -> None:
        db = get_db()
        completed_at = _now() if status in {"completed", "failed", "cancelled"} else None
        db.execute(
            """
            UPDATE translation_jobs
               SET status = ?,
                   progress = COALESCE(?, progress),
                   error = ?,
                   updated_at = ?,
                   completed_at = COALESCE(?, completed_at)
             WHERE job_id = ?
            """,
            (status, progress, error, _now(), completed_at, job_id),
        )
        db.commit()

    @staticmethod
    def get(job_id: str) -> dict | None:
        row = get_db().execute(
            "SELECT * FROM translation_jobs WHERE job_id = ?", (job_id,)
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def list_active() -> list[dict]:
        rows = get_db().execute(
            """
            SELECT * FROM translation_jobs
             WHERE status IN ('queued', 'running')
             ORDER BY created_at
            """
        ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def has_active_for_paper(paper_id: str) -> bool:
        row = get_db().execute(
            """
            SELECT 1 FROM translation_jobs
             WHERE paper_id = ? AND status IN ('queued', 'running')
             LIMIT 1
            """,
            (paper_id,),
        ).fetchone()
        return row is not None
