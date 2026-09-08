from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List

from flask import jsonify, request, send_file

from paperpilot.core.base_paper import Paper
from paperpilot.core.paper_store import paper_store
from paperpilot.database.dao.translation_job_dao import TranslationJobDAO
from paperpilot.database.dao.settings_dao import SettingsDAO
from paperpilot.security.agentic_credentials import AgenticCredentialStore
from paperpilot.security.outbound import OutboundPolicy, OutboundPolicyError
from paperpilot.security.paths import PathSecurityError, paper_asset_paths, verified_paper_path
from paperpilot.tools.agent_tools.translate_pdf import (
    TranslationDependencies,
    recover_translation_tasks,
    start_monitor,
)
from paperpilot.tools.agent_tools.translation_worker_client import (
    TranslationWorkerClient,
    TranslationWorkerRejected,
    TranslationWorkerUnavailable,
)
from paperpilot.tools.api_test_utils import test_llm_api

CategoryPath = List[str]


def register_agent_translate_routes(
    app,
    *,
    translation_tasks: Dict[str, Dict[str, Any]],
    translation_tasks_lock: threading.Lock,
    get_categories: Callable[[], dict],
    get_category_path: Callable[[dict, str], CategoryPath | None],
    get_papers_in_category: Callable[[str, CategoryPath], List[Paper]],
    save_paper_metadata: Callable[[str, Any], None],
    agentic_settings_file: str,
    upload_folder: str,
    credential_store: AgenticCredentialStore | None = None,
    outbound_policy: OutboundPolicy | None = None,
) -> None:
    del agentic_settings_file
    worker_client = TranslationWorkerClient()
    deps = TranslationDependencies(
        translation_tasks=translation_tasks,
        translation_tasks_lock=translation_tasks_lock,
        get_categories=get_categories,
        get_category_path=get_category_path,
        get_papers_in_category=get_papers_in_category,
        save_paper_metadata=save_paper_metadata,
        upload_folder=upload_folder,
        worker_client=worker_client,
    )

    def find_paper(paper_id: str) -> Paper | None:
        entry = paper_store.get_entry(paper_id)
        if entry:
            return entry.paper
        categories = get_categories()

        def search(node: dict) -> Paper | None:
            category_path = get_category_path(categories, node["id"])
            if category_path:
                for paper in get_papers_in_category(node["id"], category_path):
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

    def resolve_paper_file(paper: Paper) -> str:
        entry = paper_store.get_entry(paper.id)
        if not entry:
            raise PathSecurityError("paper_category_missing")
        return str(
            verified_paper_path(
                upload_folder,
                entry.category_id,
                paper.filename,
                paper.file_path,
            )
        )

    @app.post("/api/paper/translate")
    def api_translate_paper():
        data = request.get_json(silent=True) or {}
        if not isinstance(data, dict):
            return jsonify({"success": False, "error": "invalid_request"}), 400
        forbidden = sorted(set(data) - {"paper_id"})
        if forbidden:
            return jsonify({"success": False, "error": "forbidden_agent_overrides", "fields": forbidden}), 400
        paper_id = data.get("paper_id")
        if not isinstance(paper_id, str) or not paper_id.strip():
            return jsonify({"success": False, "error": "Missing required parameters"}), 400
        if credential_store is None or outbound_policy is None:
            return jsonify({"success": False, "error": "agentic_security_unavailable"}), 503
        settings = SettingsDAO.get_setting("agentic_settings", {}) or {}
        config = ((settings.get("llmConfigs") or {}).get("translate") or {})
        model = (config.get("llmModel") or "").strip()
        base_url = (config.get("llmBaseUrl") or "").strip()
        try:
            api_key = credential_store.get("translate")
            outbound_policy.validate(base_url, purpose="ai")
        except OutboundPolicyError as exc:
            return jsonify({"success": False, "error": exc.reason}), 400
        except Exception:
            return jsonify({"success": False, "error": "credential_decryption_failed"}), 503
        if not model or not base_url or not api_key:
            return jsonify({"success": False, "error": "translation_settings_not_configured"}), 400
        if TranslationJobDAO.has_active_for_paper(paper_id):
            return jsonify({"success": False, "error": "There is already a translation task running for this paper"}), 400
        if not worker_client.health():
            return jsonify({"success": False, "error": "translation_worker_unavailable"}), 503

        llm_success, llm_error = test_llm_api(model, base_url, api_key, outbound_policy)
        if not llm_success:
            return jsonify({"success": False, "error": f"LLM API test failed: {llm_error}"}), 400
        paper = find_paper(paper_id)
        if paper is None:
            return jsonify({"success": False, "error": "Paper not found"}), 404
        try:
            pdf_path = resolve_paper_file(paper)
        except PathSecurityError:
            return jsonify({"success": False, "error": "unsafe_stored_path"}), 409

        task_id = str(uuid.uuid4())
        try:
            worker_client.stage_input(task_id, pdf_path)
            TranslationJobDAO.create(task_id, paper_id)
            with translation_tasks_lock:
                translation_tasks[task_id] = {
                    "paper_id": paper_id,
                    "status": "queued",
                    "progress": 0,
                    "logs": [],
                    "log_lock": threading.Lock(),
                    "start_time": datetime.now(timezone.utc).isoformat(),
                    "result": None,
                }
            worker_client.create(task_id, model, base_url, api_key)
        except TranslationWorkerUnavailable:
            try:
                worker_client.cleanup(task_id)
            except Exception:
                pass
            return jsonify({"success": False, "error": "translation_worker_unavailable"}), 503
        except TranslationWorkerRejected as exc:
            TranslationJobDAO.update(task_id, "failed", error=exc.reason)
            return jsonify({"success": False, "error": exc.reason}), exc.status_code
        except ValueError as exc:
            return jsonify({"success": False, "error": str(exc)}), 413
        except Exception:  # noqa: BLE001
            try:
                worker_client.cleanup(task_id)
            except Exception:
                pass
            return jsonify({"success": False, "error": "translation_worker_unavailable"}), 503
        finally:
            api_key = ""

        start_monitor(task_id, paper_id, deps)
        return jsonify({"success": True, "message": "Translation task started", "task_id": task_id})

    @app.get("/api/paper/translate/active")
    def api_get_active_translations():
        jobs = TranslationJobDAO.list_active()
        return jsonify(
            {
                "success": True,
                "tasks": [
                    {
                        "task_id": item["job_id"],
                        "paper_id": item["paper_id"],
                        "status": item["status"],
                        "start_time": item["created_at"],
                    }
                    for item in jobs
                ],
            }
        )

    @app.get("/api/paper/translate/<task_id>/logs")
    def api_get_translation_logs(task_id: str):
        persisted = TranslationJobDAO.get(task_id)
        if not persisted:
            return jsonify({"success": False, "error": "Task does not exist"}), 404
        with translation_tasks_lock:
            task = translation_tasks.get(task_id)
            if task:
                with task["log_lock"]:
                    return jsonify(
                        {
                            "success": True,
                            "status": task["status"],
                            "progress": max(0, min(100, int(task.get("progress") or 0))),
                            "logs": list(task.get("logs") or []),
                            "start_time": task["start_time"],
                            "result": task.get("result"),
                        }
                    )
        return jsonify(
            {
                "success": True,
                "status": persisted["status"],
                "progress": persisted["progress"],
                "logs": [],
                "start_time": persisted["created_at"],
                "result": (
                    {"success": False, "error": persisted["error"]}
                    if persisted["status"] == "failed"
                    else None
                ),
            }
        )

    @app.post("/api/paper/translate/<task_id>/cancel")
    def api_cancel_translation(task_id: str):
        persisted = TranslationJobDAO.get(task_id)
        if not persisted:
            return jsonify({"success": False, "error": "Task does not exist"}), 404
        if persisted["status"] in {"completed", "failed", "cancelled"}:
            return jsonify({"success": False, "error": "The task has ended and cannot be canceled"}), 400
        try:
            state = worker_client.cancel(task_id)
        except TranslationWorkerUnavailable:
            return jsonify({"success": False, "error": "translation_worker_unavailable"}), 503
        except TranslationWorkerRejected as exc:
            return jsonify({"success": False, "error": exc.reason}), exc.status_code
        TranslationJobDAO.update(task_id, "cancelled", progress=state.get("progress", 0), error="cancelled")
        with translation_tasks_lock:
            task = translation_tasks.get(task_id)
            if task:
                task["status"] = "cancelled"
                task["result"] = {"success": False, "error": "Translation canceled"}
        return jsonify({"success": True, "message": "Translation task canceled"})

    @app.get("/api/paper/<paper_id>/chinese/file")
    def api_get_chinese_paper_file(paper_id: str):
        paper = find_paper(paper_id)
        if paper is None:
            return jsonify({"error": "Paper not found"}), 404
        try:
            pdf_path = resolve_paper_file(paper)
            chinese_path = paper_asset_paths(upload_folder, pdf_path).chinese_dual
        except PathSecurityError:
            return jsonify({"error": "unsafe_stored_path"}), 409
        if not chinese_path.exists():
            return jsonify({"error": "Chinese version file does not exist"}), 404
        return send_file(str(chinese_path), as_attachment=False, mimetype="application/pdf")

    recover_translation_tasks(deps)
    threading.Thread(target=worker_client.run_cleanup_loop, daemon=True).start()
