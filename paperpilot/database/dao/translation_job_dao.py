from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

from ..connection import get_db
from paperpilot.security.identity import current_user_id


ACTIVE_STATES = ("queued", "dispatching", "running", "recovering", "paused")
TERMINAL_STATES = ("completed", "failed", "cancelled")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class TranslationJobDAO:
    @staticmethod
    def create(job_id: str, paper_id: str, *, config_fingerprint: str | None = None) -> None:
        now = _now()
        db = get_db()
        db.execute(
            """INSERT INTO translation_jobs
               (job_id,owner_id,paper_id,status,progress,created_at,updated_at,
                heartbeat_at,queue_order,config_fingerprint,recoverable_until)
               VALUES (?,? ,?,'queued',0,?,?,?,?,?,?)""",
            (
                job_id, current_user_id(), paper_id, now, now, now, time.time_ns(),
                config_fingerprint,
                (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
            ),
        )
        db.commit()
        TranslationJobDAO.append_event(job_id, kind="status", message="queued")

    @staticmethod
    def update(
        job_id: str,
        status: str,
        *,
        progress: int | None = None,
        error: str | None = None,
        error_code: str | None = None,
        stage: str | None = None,
        stage_progress: int | None = None,
        stage_current: int | None = None,
        stage_total: int | None = None,
        heartbeat: bool = False,
        increment_attempt: bool = False,
        worker_event_sequence: int | None = None,
    ) -> None:
        db = get_db()
        completed_at = _now() if status in TERMINAL_STATES else None
        now = _now()
        db.execute(
            """UPDATE translation_jobs
               SET status=?,progress=COALESCE(?,progress),error=?,error_code=?,
                   stage=COALESCE(?,stage),
                   stage_progress=COALESCE(?,stage_progress),
                   stage_current=COALESCE(?,stage_current),
                   stage_total=COALESCE(?,stage_total),
                   heartbeat_at=CASE WHEN ? THEN ? ELSE heartbeat_at END,
                   attempt_count=attempt_count+?,updated_at=?,
                   worker_event_sequence=COALESCE(?,worker_event_sequence),
                   completed_at=CASE WHEN ? IS NULL THEN completed_at ELSE ? END
               WHERE job_id=? AND owner_id=?""",
            (
                status, progress, error, error_code, stage, stage_progress,
                stage_current, stage_total, int(heartbeat), now,
                int(increment_attempt), now, worker_event_sequence,
                completed_at, completed_at,
                job_id, current_user_id(),
            ),
        )
        db.commit()

    @staticmethod
    def append_event(
        job_id: str,
        *,
        kind: str,
        level: str = "info",
        stage: str | None = None,
        message: str | None = None,
        progress: int | None = None,
        stage_progress: int | None = None,
        stage_current: int | None = None,
        stage_total: int | None = None,
    ) -> int:
        owner_id = current_user_id()
        db = get_db()
        cursor = db.execute(
            """INSERT INTO translation_job_events
               (job_id,owner_id,created_at,kind,level,stage,message,progress,
                stage_progress,stage_current,stage_total)
               SELECT job_id,owner_id,?,?,?,?,?,?,?,?,?
               FROM translation_jobs WHERE job_id=? AND owner_id=?""",
            (
                _now(), kind, level, stage, message, progress, stage_progress,
                stage_current, stage_total, job_id, owner_id,
            ),
        )
        db.commit()
        return int(cursor.lastrowid or 0)

    @staticmethod
    def get(job_id: str) -> dict | None:
        row = get_db().execute(
            "SELECT * FROM translation_jobs WHERE job_id=? AND owner_id=?",
            (job_id, current_user_id()),
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def list_jobs(*, status: str | None = None, limit: int = 100) -> list[dict]:
        params: list[object] = [current_user_id()]
        condition = "owner_id=?"
        if status:
            condition += " AND status=?"
            params.append(status)
        params.append(max(1, min(int(limit), 200)))
        rows = get_db().execute(
            f"""SELECT * FROM translation_jobs WHERE {condition}
                ORDER BY CASE WHEN status IN ('queued','dispatching','running','recovering')
                              THEN 0 ELSE 1 END,
                         queue_order, created_at DESC LIMIT ?""",
            params,
        ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def list_events(
        *, after_id: int = 0, job_id: str | None = None, limit: int = 500
    ) -> list[dict]:
        params: list[object] = [current_user_id(), max(0, int(after_id))]
        condition = "owner_id=? AND id>?"
        if job_id:
            condition += " AND job_id=?"
            params.append(job_id)
        params.append(max(1, min(int(limit), 1000)))
        rows = get_db().execute(
            f"SELECT * FROM translation_job_events WHERE {condition} ORDER BY id LIMIT ?",
            params,
        ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def list_active() -> list[dict]:
        placeholders = ",".join("?" for _ in ACTIVE_STATES)
        rows = get_db().execute(
            f"""SELECT * FROM translation_jobs
                WHERE owner_id=? AND status IN ({placeholders})
                ORDER BY queue_order,created_at""",
            (current_user_id(), *ACTIVE_STATES),
        ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def has_active_for_paper(paper_id: str) -> bool:
        placeholders = ",".join("?" for _ in ACTIVE_STATES)
        row = get_db().execute(
            f"""SELECT 1 FROM translation_jobs
                WHERE paper_id=? AND owner_id=? AND status IN ({placeholders}) LIMIT 1""",
            (paper_id, current_user_id(), *ACTIVE_STATES),
        ).fetchone()
        return row is not None

    @staticmethod
    def set_queue_order(job_id: str, queue_order: int) -> bool:
        db = get_db()
        cursor = db.execute(
            """UPDATE translation_jobs SET queue_order=?,updated_at=?
               WHERE job_id=? AND owner_id=? AND status='queued'""",
            (int(queue_order), _now(), job_id, current_user_id()),
        )
        db.commit()
        return cursor.rowcount == 1

    @staticmethod
    def enqueue(job_id: str) -> bool:
        db = get_db()
        now = _now()
        cursor = db.execute(
            """UPDATE translation_jobs
               SET status='queued',error=NULL,error_code=NULL,completed_at=NULL,
                   updated_at=?,queue_order=?
               WHERE job_id=? AND owner_id=?
                 AND status IN ('paused','failed','recovering','queued')""",
            (now, time.time_ns(), job_id, current_user_id()),
        )
        db.commit()
        if cursor.rowcount:
            TranslationJobDAO.append_event(job_id, kind="status", message="queued")
        return cursor.rowcount == 1

    @staticmethod
    def queue_position(job_id: str) -> int | None:
        row = TranslationJobDAO.get(job_id)
        if not row or row["status"] != "queued":
            return None
        result = get_db().execute(
            """SELECT COUNT(*) FROM translation_jobs
               WHERE status='queued' AND
                     (queue_order<? OR (queue_order=? AND created_at<?))""",
            (row["queue_order"], row["queue_order"], row["created_at"]),
        ).fetchone()
        return int(result[0]) + 1

    @staticmethod
    def next_queued(last_owner_id: str | None = None) -> dict | None:
        """Return one globally queued job for the trusted in-process dispatcher."""
        db = get_db()
        row = None
        if last_owner_id:
            row = db.execute(
                """SELECT j.*,u.username,u.role FROM translation_jobs j
                   JOIN users u ON u.id=j.owner_id
                   WHERE j.status='queued' AND j.owner_id<>? AND u.status='active'
                   ORDER BY j.queue_order,j.created_at LIMIT 1""",
                (last_owner_id,),
            ).fetchone()
        if row is None:
            row = db.execute(
                """SELECT j.*,u.username,u.role FROM translation_jobs j
                   JOIN users u ON u.id=j.owner_id
                   WHERE j.status='queued' AND u.status='active'
                   ORDER BY j.queue_order,j.created_at LIMIT 1"""
            ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def has_global_running() -> bool:
        row = get_db().execute(
            """SELECT 1 FROM translation_jobs
               WHERE status IN ('dispatching','running','recovering') LIMIT 1"""
        ).fetchone()
        return row is not None

    @staticmethod
    def recover_incomplete() -> None:
        db = get_db()
        now = _now()
        db.execute(
            """UPDATE translation_jobs SET status='queued',error_code='interrupted',
               error='interrupted',updated_at=?,queue_order=?
               WHERE status IN ('dispatching','running','recovering')""",
            (now, time.time_ns()),
        )
        db.commit()
