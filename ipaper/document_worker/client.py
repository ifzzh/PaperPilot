from __future__ import annotations

from ipaper.environment import getenv as brand_getenv

import json
import re
import hashlib
import os
import shutil
import stat
import time
from pathlib import Path
from pathlib import PurePosixPath

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
        self.base_url = (base_url or brand_getenv(
            "IPAPER_DOCUMENT_WORKER_URL", "http://ipaper-document-worker:7193"
        )).rstrip("/")
        self.token_file = Path(token_file or brand_getenv(
            "IPAPER_DOCUMENT_WORKER_TOKEN_FILE",
            "/run/secrets/ipaper_document_worker_token",
        ))
        self.jobs_root = Path(jobs_root or brand_getenv(
            "IPAPER_DOCUMENT_JOBS_ROOT", "/work/document-jobs"
        ))
        self.limits = limits or DocumentLimits.from_env()

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
            "pdf_split": self.limits.max_pdf_bytes,
            "pdf_page_text": self.limits.max_pdf_bytes,
            "mineru_structure": self.limits.max_archive_bytes,
            "metadata_zip": self.limits.max_archive_bytes,
            "mineru_zip": self.limits.max_archive_bytes,
            "zotero_rdf": self.limits.max_rdf_bytes,
        }[kind]
        return_path = work / INPUT_NAMES[kind]
        # Gunicorn defaults to a restrictive umask. Apply the shared-group
        # contract explicitly so the distinct Document Worker UID can create
        # status and output files inside this Web-owned job directory.
        os.chmod(job, 0o2770)
        os.chmod(work, 0o2770)
        bounded_copy(stream, return_path, maximum)
        os.chmod(return_path, 0o640)
        return return_path

    def stage_page_text(self, job_id, pdf_stream, page):
        if type(page) is not int or not 1 <= page <= self.limits.max_pdf_pages:
            raise ValueError("invalid_page_request")
        target = self.stage(job_id, "pdf_page_text", pdf_stream)
        selection = target.parent / "page.json"
        selection.write_text(json.dumps({"page": page}), encoding="utf-8")
        os.chmod(selection, 0o640)
        return target

    def stage_structure(self, job_id: str, archive_stream, pdf_stream) -> Path:
        target = self.stage(job_id, "mineru_structure", archive_stream)
        source = target.parent / "source.pdf"
        bounded_copy(pdf_stream, source, self.limits.max_pdf_bytes)
        os.chmod(source, 0o640)
        return target

    def create(self, job_id: str, kind: str) -> dict:
        return self._request("POST", "/v1/jobs", {"job_id": canonical_job_id(job_id), "kind": kind})

    def get(self, job_id: str) -> dict:
        return self._request("GET", f"/v1/jobs/{canonical_job_id(job_id)}")

    def wait(self, job_id: str, *, timeout: float = 120.0) -> dict:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            state = self.get(job_id)
            if state.get("status") in {"completed", "failed", "cancelled"}:
                return state
            time.sleep(0.5)
        try:
            self.cancel(job_id)
        except (DocumentWorkerRejected, DocumentWorkerUnavailable):
            pass
        raise DocumentWorkerRejected("document_job_timeout", 408)

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

    def verified_manifest(self, job_id: str, expected_kind: str) -> dict:
        output = self.output(job_id)
        target = output / "manifest.json"
        if target.is_symlink() or not target.is_file() or target.stat().st_size > 4 * 1024 * 1024:
            raise DocumentWorkerRejected("unsafe_worker_output", 409)
        try:
            manifest = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise DocumentWorkerRejected("unsafe_worker_output", 409) from exc
        if not isinstance(manifest, dict):
            raise DocumentWorkerRejected("unsafe_worker_output", 409)
        entries = manifest.get("entries")
        if manifest.get("kind") != expected_kind or not isinstance(entries, list):
            raise DocumentWorkerRejected("unsafe_worker_output", 409)
        if len(entries) > self.limits.max_entries:
            raise DocumentWorkerRejected("unsafe_worker_output", 409)
        expected: set[str] = set()
        for entry in entries:
            if not isinstance(entry, dict):
                raise DocumentWorkerRejected("unsafe_worker_output", 409)
            relative = entry.get("path")
            if not isinstance(relative, str) or "\\" in relative:
                raise DocumentWorkerRejected("unsafe_worker_output", 409)
            path = PurePosixPath(relative)
            if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
                raise DocumentWorkerRejected("unsafe_worker_output", 409)
            if expected_kind == "pdf_split" and relative != "result.json" and not re.fullmatch(r"part-[0-9]{6}-[0-9]{6}\.pdf", relative):
                raise DocumentWorkerRejected("unsafe_worker_output", 409)
            if expected_kind == "mineru_structure" and relative not in {"blocks.jsonl", "result.json"}:
                if not relative.startswith("raw/") or path.suffix.lower() not in {".json", ".md", ".png", ".jpg", ".jpeg"}:
                    raise DocumentWorkerRejected("unsafe_worker_output", 409)
            candidate = output.joinpath(*path.parts)
            if candidate.is_symlink() or not candidate.is_file():
                raise DocumentWorkerRejected("unsafe_worker_output", 409)
            try:
                candidate.resolve(strict=True).relative_to(output.resolve(strict=True))
                size = int(entry.get("size"))
            except (OSError, TypeError, ValueError) as exc:
                raise DocumentWorkerRejected("unsafe_worker_output", 409) from exc
            digest = hashlib.sha256()
            actual = 0
            with candidate.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    actual += len(chunk)
                    digest.update(chunk)
            if actual != size or digest.hexdigest() != entry.get("sha256"):
                raise DocumentWorkerRejected("unsafe_worker_output", 409)
            if relative in expected:
                raise DocumentWorkerRejected("unsafe_worker_output", 409)
            expected.add(relative)
        actual_files = {
            path.relative_to(output).as_posix()
            for path in output.rglob("*")
            if path.is_file() and path != output / "manifest.json"
        }
        if actual_files != expected:
            raise DocumentWorkerRejected("unsafe_worker_output", 409)
        return manifest

    def cleanup(self, job_id: str) -> None:
        try:
            self.cancel(job_id)
        except DocumentWorkerRejected as exc:
            if exc.status_code != 404:
                raise
        job = self.job_directory(job_id)
        if job.exists():
            shutil.rmtree(job)
