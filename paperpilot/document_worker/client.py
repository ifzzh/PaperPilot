from __future__ import annotations

import json
import os
import shutil
import stat
from pathlib import Path

import requests

from .safety import DocumentLimits, bounded_copy
from .service import INPUT_NAMES, canonical_job_id


class DocumentWorkerUnavailable(RuntimeError):
    pass


class DocumentWorkerRejected(RuntimeError):
    def __init__(self, reason: str, status_code: int) -> None:
        super().__init__(reason)
        self.reason = reason
        self.status_code = status_code


class DocumentWorkerClient:
    def __init__(self, *, base_url=None, token_file=None, jobs_root=None, limits=None):
        self.base_url = (base_url or os.getenv(
            "PAPERPILOT_DOCUMENT_WORKER_URL", "http://paperpilot-document-worker:7193"
        )).rstrip("/")
        self.token_file = Path(token_file or os.getenv(
            "PAPERPILOT_DOCUMENT_WORKER_TOKEN_FILE",
            "/run/secrets/paperpilot_document_worker_token",
        ))
        self.jobs_root = Path(jobs_root or os.getenv(
            "PAPERPILOT_DOCUMENT_JOBS_ROOT", "/work/document-jobs"
        ))
        self.limits = limits or DocumentLimits()

    def _token(self) -> str:
        try:
            token = self.token_file.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise DocumentWorkerUnavailable("document_worker_unavailable") from exc
        if len(token) < 32:
            raise DocumentWorkerUnavailable("document_worker_unavailable")
        return token

    def _request(self, method, path, body=None):
        try:
            response = requests.request(
                method,
                self.base_url + path,
                json=body,
                headers={"Authorization": f"Bearer {self._token()}"},
                timeout=(3, 15),
                allow_redirects=False,
            )
        except (requests.RequestException, DocumentWorkerUnavailable) as exc:
            raise DocumentWorkerUnavailable("document_worker_unavailable") from exc
        try:
            payload = response.json()
        except ValueError:
            payload = {"error": "invalid_worker_response"}
        if response.status_code >= 400:
            raise DocumentWorkerRejected(str(payload.get("error") or "worker_rejected"), response.status_code)
        return payload

    def health(self) -> bool:
        try:
            response = requests.get(
                self.base_url + "/healthz", timeout=(2, 3), allow_redirects=False
            )
            return response.status_code == 200
        except requests.RequestException:
            return False

    def job_directory(self, job_id: str) -> Path:
        root = self.jobs_root.resolve(strict=True)
        if root.is_symlink() or not root.is_dir():
            raise DocumentWorkerUnavailable("document_staging_unavailable")
        candidate = root / canonical_job_id(job_id)
        if candidate.is_symlink() or candidate.resolve(strict=False).parent != root:
            raise DocumentWorkerRejected("unsafe_job_path", 409)
        return candidate

    def stage(self, job_id: str, kind: str, stream) -> Path:
        if kind not in INPUT_NAMES:
            raise ValueError("unsupported_document_kind")
        job = self.job_directory(job_id)
        work = job / "work"
        job.mkdir(mode=0o2770, parents=False, exist_ok=False)
        work.mkdir(mode=0o2770)
        maximum = {
            "pdf_inspect": self.limits.max_pdf_bytes,
            "metadata_zip": self.limits.max_archive_bytes,
            "mineru_zip": self.limits.max_archive_bytes,
            "zotero_rdf": self.limits.max_rdf_bytes,
        }[kind]
        return_path = work / INPUT_NAMES[kind]
        bounded_copy(stream, return_path, maximum)
        os.chmod(return_path, 0o640)
        return return_path

    def create(self, job_id: str, kind: str) -> dict:
        return self._request("POST", "/v1/jobs", {"job_id": canonical_job_id(job_id), "kind": kind})

    def get(self, job_id: str) -> dict:
        return self._request("GET", f"/v1/jobs/{canonical_job_id(job_id)}")

    def cancel(self, job_id: str) -> dict:
        return self._request("DELETE", f"/v1/jobs/{canonical_job_id(job_id)}")

    def output(self, job_id: str) -> Path:
        output = self.job_directory(job_id) / "work" / "output"
        if output.is_symlink() or not output.is_dir():
            raise DocumentWorkerRejected("unsafe_worker_output", 409)
        for root, directories, files in os.walk(output, followlinks=False):
            for name in [*directories, *files]:
                mode = os.lstat(Path(root) / name).st_mode
                if stat.S_ISLNK(mode) or not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
                    raise DocumentWorkerRejected("unsafe_worker_output", 409)
        return output

    def result_json(self, job_id: str) -> dict:
        target = self.output(job_id) / "result.json"
        if target.is_symlink() or not target.is_file() or target.stat().st_size > 4 * 1024 * 1024:
            raise DocumentWorkerRejected("unsafe_worker_output", 409)
        return json.loads(target.read_text(encoding="utf-8"))

    def cleanup(self, job_id: str) -> None:
        job = self.job_directory(job_id)
        if job.exists():
            shutil.rmtree(job)
