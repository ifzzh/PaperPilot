from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List

from paperpilot.core.base_paper import Paper
from paperpilot.core.paper_store import paper_store
from paperpilot.database.dao.translation_job_dao import TranslationJobDAO
from paperpilot.security.identity import current_identity, run_as_identity
from paperpilot.security.paths import PathSecurityError, paper_asset_paths, verified_paper_path
from paperpilot.tools.agent_tools.translation_worker_client import (
    TranslationWorkerClient,
    TranslationWorkerRejected,
    TranslationWorkerUnavailable,
)

PaperList = List[Paper]
CategoryPath = List[str]


@dataclass
class TranslationDependencies:
    translation_tasks: Dict[str, Dict[str, Any]]
    translation_tasks_lock: threading.Lock
    get_categories: Callable[[], dict]
    get_category_path: Callable[[dict, str], CategoryPath | None]
    get_papers_in_category: Callable[[str, CategoryPath], PaperList]
    save_paper_metadata: Callable[[str, Paper], None]
    upload_folder: str
    worker_client: TranslationWorkerClient
    on_terminal: Callable[[], None] | None = None


def _task_payload(job: dict) -> dict:
    return {
        "paper_id": job["paper_id"],
        "status": job["status"],
        "progress": int(job.get("progress") or 0),
        "logs": [],
        "log_lock": threading.Lock(),
        "start_time": job.get("created_at") or datetime.now(timezone.utc).isoformat(),
        "result": None,
    }


def _find_paper(paper_id: str, deps: TranslationDependencies) -> Paper | None:
    entry = paper_store.get_entry(paper_id)
    if entry:
        return entry.paper
    categories = deps.get_categories()

    def search(node: dict) -> Paper | None:
        category_path = deps.get_category_path(categories, node["id"])
        if category_path:
            for paper in deps.get_papers_in_category(node["id"], category_path):
                if paper.id == paper_id:
                    return paper
        for child in node.get("children", []):
            found = search(child)
            if found:
                return found
        return None

    for child in categories.get("children", []):
        found = search(child)
        if found:
            return found
    return None


def _verified_pdf(paper: Paper, deps: TranslationDependencies) -> str:
    entry = paper_store.get_entry(paper.id)
    if not entry:
        raise PathSecurityError("paper_category_missing")
    return str(
        verified_paper_path(
            deps.upload_folder,
            entry.category_id,
            paper.filename,
            paper.file_path,
        )
    )


def _update_memory_task(
    task_id: str,
    deps: TranslationDependencies,
    *,
    status: str,
    progress: int,
    logs: list[str],
    result: dict | None,
) -> None:
    with deps.translation_tasks_lock:
        task = deps.translation_tasks.setdefault(
            task_id,
            {
                "paper_id": "",
                "status": status,
                "progress": 0,
                "logs": [],
                "log_lock": threading.Lock(),
                "start_time": datetime.now(timezone.utc).isoformat(),
                "result": None,
            },
        )
        with task["log_lock"]:
            task["status"] = status
            task["progress"] = max(0, min(100, int(progress)))
            task["logs"] = list(logs)
            task["result"] = result


def monitor_worker_task(
    task_id: str,
    paper_id: str,
    deps: TranslationDependencies,
    *,
    poll_seconds: float = 1.0,
) -> None:
    worker_sequence = int((TranslationJobDAO.get(task_id) or {}).get("worker_event_sequence") or 0)
    try:
        while True:
            state = deps.worker_client.get(task_id)
            status = str(state.get("status") or "failed")
            progress = int(state.get("progress") or 0)
            logs = [str(item) for item in state.get("logs") or []]
            for event in state.get("events") or []:
                sequence = int(event.get("sequence") or 0)
                if sequence <= worker_sequence:
                    continue
                TranslationJobDAO.append_event(
                    task_id,
                    kind=str(event.get("kind") or "log"),
                    level=str(event.get("level") or "info"),
                    stage=event.get("stage"),
                    message=event.get("message"),
                    progress=event.get("progress"),
                    stage_progress=event.get("stage_progress"),
                    stage_current=event.get("stage_current"),
                    stage_total=event.get("stage_total"),
                )
                worker_sequence = sequence
            stage = state.get("stage")
            stage_progress = int(state.get("stage_progress") or 0)
            stage_current = int(state.get("stage_current") or 0)
            stage_total = int(state.get("stage_total") or 0)
            if status == "completed":
                paper = _find_paper(paper_id, deps)
                if paper is None:
                    raise RuntimeError("paper_not_found")
                pdf_path = _verified_pdf(paper, deps)
                assets = paper_asset_paths(deps.upload_folder, pdf_path)
                deps.worker_client.promote_result(
                    task_id,
                    papers_root=deps.upload_folder,
                    destination=assets.chinese_dual,
                    logs=logs,
                    log_destination=assets.translation_log,
                )
                paper.mark_chinese_version(str(assets.chinese_dual))
                row = TranslationJobDAO.get(task_id) or {}
                try:
                    started = datetime.fromisoformat(row.get("created_at", ""))
                    duration = max(0, int((datetime.now(timezone.utc) - started).total_seconds()))
                except (TypeError, ValueError):
                    duration = 0
                paper.translation_time = max(paper.translation_time, duration)
                deps.save_paper_metadata(pdf_path, paper)
                result = {
                    "success": True,
                    "chinese_version_path": f"/api/paper/{paper_id}/chinese/file",
                }
                TranslationJobDAO.update(
                    task_id, "completed", progress=100, stage="completed",
                    stage_progress=100, heartbeat=True,
                    worker_event_sequence=worker_sequence,
                )
                TranslationJobDAO.append_event(
                    task_id, kind="status", stage="completed", message="completed", progress=100,
                )
                _update_memory_task(
                    task_id, deps, status="completed", progress=100, logs=logs, result=result
                )
                deps.worker_client.cleanup(task_id)
                return
            if status in {"failed", "cancelled", "paused"}:
                error = str(state.get("error") or status)
                result = {"success": False, "error": error}
                TranslationJobDAO.update(
                    task_id, status, progress=progress, error=error,
                    error_code=error, stage=stage, stage_progress=stage_progress,
                    stage_current=stage_current, stage_total=stage_total,
                    heartbeat=True, worker_event_sequence=worker_sequence,
                )
                TranslationJobDAO.append_event(
                    task_id, kind="status", stage=stage, message=status, progress=progress,
                )
                _update_memory_task(
                    task_id, deps, status=status, progress=progress, logs=logs, result=result
                )
                return
            TranslationJobDAO.update(
                task_id, status, progress=progress, stage=stage,
                stage_progress=stage_progress, stage_current=stage_current,
                stage_total=stage_total, heartbeat=True,
                worker_event_sequence=worker_sequence,
            )
            _update_memory_task(
                task_id, deps, status=status, progress=progress, logs=logs, result=None
            )
            time.sleep(poll_seconds)
    except (TranslationWorkerUnavailable, TranslationWorkerRejected) as exc:
        error = (
            "interrupted"
            if isinstance(exc, TranslationWorkerRejected)
            else "translation_worker_unavailable"
        )
        TranslationJobDAO.update(task_id, "queued", error=error, error_code=error)
        _update_memory_task(
            task_id,
            deps,
            status="queued",
            progress=0,
            logs=[],
            result=None,
        )
    except Exception as exc:  # noqa: BLE001
        error = str(exc)[:512]
        TranslationJobDAO.update(task_id, "failed", error=error)
        _update_memory_task(
            task_id,
            deps,
            status="failed",
            progress=0,
            logs=[],
            result={"success": False, "error": error},
        )
    finally:
        if deps.on_terminal:
            deps.on_terminal()


def start_monitor(task_id: str, paper_id: str, deps: TranslationDependencies) -> threading.Thread:
    identity = current_identity()
    thread = threading.Thread(
        target=run_as_identity,
        args=(identity, monitor_worker_task, task_id, paper_id, deps),
        daemon=True,
    )
    thread.start()
    return thread


def recover_translation_tasks(deps: TranslationDependencies) -> None:
    for job in TranslationJobDAO.list_active():
        task_id = job["job_id"]
        with deps.translation_tasks_lock:
            deps.translation_tasks[task_id] = _task_payload(job)
        start_monitor(task_id, job["paper_id"], deps)
