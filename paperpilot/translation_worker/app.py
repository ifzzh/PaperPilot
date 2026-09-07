from __future__ import annotations

import hmac
import os
from pathlib import Path

from flask import Flask, jsonify, request

from .service import TranslationWorkerService, WorkerRequestError


def read_worker_token(path: str | os.PathLike[str]) -> str:
    token_path = Path(path)
    token = token_path.read_text(encoding="utf-8").strip()
    if len(token) < 32:
        raise RuntimeError("worker token must contain at least 32 characters")
    return token


def create_worker_app(
    *,
    jobs_root: str | os.PathLike[str] | None = None,
    token: str | None = None,
    service: TranslationWorkerService | None = None,
) -> Flask:
    jobs_root = jobs_root or os.getenv("PAPERPILOT_WORKER_JOBS_ROOT", "/work/jobs")
    token = token or read_worker_token(
        os.getenv("PAPERPILOT_WORKER_TOKEN_FILE", "/run/secrets/paperpilot_worker_token")
    )
    if len(token) < 32:
        raise RuntimeError("worker token must contain at least 32 characters")
    service = service or TranslationWorkerService(jobs_root)
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 64 * 1024

    @app.before_request
    def authenticate():
        if request.path == "/healthz":
            return None
        expected = f"Bearer {token}"
        supplied = request.headers.get("Authorization", "")
        if not hmac.compare_digest(supplied, expected):
            return jsonify({"error": "unauthorized"}), 401
        return None

    @app.errorhandler(WorkerRequestError)
    def handle_worker_error(exc: WorkerRequestError):
        return jsonify({"error": exc.reason}), exc.status_code

    @app.get("/healthz")
    def healthz():
        return jsonify({"status": "ok"})

    @app.post("/v1/jobs")
    def create_job():
        state = service.submit(request.get_json(silent=True))
        return jsonify(state), 202

    @app.get("/v1/jobs/<job_id>")
    def get_job(job_id: str):
        return jsonify(service.public_state(job_id))

    @app.delete("/v1/jobs/<job_id>")
    def delete_job(job_id: str):
        return jsonify(service.cancel(job_id))

    return app
