from __future__ import annotations

import hmac
import os
from pathlib import Path

from flask import Flask, jsonify, request

from .service import DocumentWorkerError, DocumentWorkerService


def read_token(path: str | os.PathLike[str]) -> str:
    token = Path(path).read_text(encoding="utf-8").strip()
    if len(token) < 32:
        raise RuntimeError("document worker token must contain at least 32 characters")
    return token


def create_worker_app(*, jobs_root=None, token=None, service=None) -> Flask:
    jobs_root = jobs_root or os.getenv("PAPERPILOT_DOCUMENT_WORKER_JOBS_ROOT", "/work/document-jobs")
    token = token or read_token(os.getenv(
        "PAPERPILOT_DOCUMENT_WORKER_TOKEN_FILE",
        "/run/secrets/paperpilot_document_worker_token",
    ))
    service = service or DocumentWorkerService(jobs_root)
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 64 * 1024

    @app.before_request
    def authenticate():
        if request.path == "/healthz":
            return None
        supplied = request.headers.get("Authorization", "")
        if not hmac.compare_digest(supplied, f"Bearer {token}"):
            return jsonify({"error": "unauthorized"}), 401
        return None

    @app.errorhandler(DocumentWorkerError)
    def handle_error(exc):
        return jsonify({"error": exc.reason}), exc.status_code

    @app.get("/healthz")
    def healthz():
        return jsonify({"status": "ok"})

    @app.post("/v1/jobs")
    def create_job():
        return jsonify(service.submit(request.get_json(silent=True))), 202

    @app.get("/v1/jobs/<job_id>")
    def get_job(job_id):
        return jsonify(service.public_state(job_id))

    @app.delete("/v1/jobs/<job_id>")
    def cancel_job(job_id):
        return jsonify(service.cancel(job_id))

    return app
