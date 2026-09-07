from __future__ import annotations

import json
import os
import shutil
import stat
import tempfile
import time
import uuid
from pathlib import Path

import requests

from paperpilot.security.paths import PathSecurityError, ensure_confined
from paperpilot.translation_worker.service import (
    MAX_INPUT_BYTES,
    MAX_JOB_BYTES,
    MAX_LOG_BYTES,
    MAX_OUTPUT_BYTES,
    canonical_job_id,
)


class TranslationWorkerUnavailable(RuntimeError):
    pass


class TranslationWorkerRejected(RuntimeError):
    def __init__(self, reason: str, status_code: int) -> None:
        super().__init__(reason)
        self.reason = reason
        self.status_code = status_code


class TranslationWorkerClient:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        token_file: str | os.PathLike[str] | None = None,
        jobs_root: str | os.PathLike[str] | None = None,
    ) -> None:
        self.base_url = (
            base_url
            or os.getenv(
                "PAPERPILOT_TRANSLATION_WORKER_URL",
                "http://paperpilot-translation-worker:7192",
            )
        ).rstrip("/")
        self.token_file = Path(
            token_file
            or os.getenv(
                "PAPERPILOT_WORKER_TOKEN_FILE",
                "/run/secrets/paperpilot_worker_token",
            )
        )
        self.jobs_root = Path(
            jobs_root
            or os.getenv("PAPERPILOT_TRANSLATION_JOBS_ROOT", "/work/jobs")
        )

    def _token(self) -> str:
        try:
            token = self.token_file.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise TranslationWorkerUnavailable("worker_token_unavailable") from exc
        if len(token) < 32:
            raise TranslationWorkerUnavailable("worker_token_invalid")
        return token

    def _request(self, method: str, path: str, *, json_body: dict | None = None) -> dict:
        try:
            response = requests.request(
                method,
                self.base_url + path,
                json=json_body,
                headers={"Authorization": f"Bearer {self._token()}"},
                timeout=(3, 15),
            )
        except (requests.RequestException, TranslationWorkerUnavailable) as exc:
            raise TranslationWorkerUnavailable("translation_worker_unavailable") from exc
        try:
            payload = response.json()
        except ValueError:
            payload = {"error": "invalid_worker_response"}
        if response.status_code >= 400:
            raise TranslationWorkerRejected(
                str(payload.get("error") or "worker_rejected"), response.status_code
            )
        return payload

    def health(self) -> bool:
        try:
            response = requests.get(self.base_url + "/healthz", timeout=(2, 3))
            return response.status_code == 200
        except requests.RequestException:
            return False

    def create(self, job_id: str, model: str, base_url: str, api_key: str) -> dict:
        return self._request(
            "POST",
            "/v1/jobs",
            json_body={
                "job_id": canonical_job_id(job_id),
                "model": model,
                "base_url": base_url,
                "api_key": api_key,
            },
        )

    def get(self, job_id: str) -> dict:
        return self._request("GET", f"/v1/jobs/{canonical_job_id(job_id)}")

    def cancel(self, job_id: str) -> dict:
        return self._request("DELETE", f"/v1/jobs/{canonical_job_id(job_id)}")

    def _root(self) -> Path:
        root = self.jobs_root.resolve(strict=True)
        if root.is_symlink() or not root.is_dir():
            raise PathSecurityError("unsafe_jobs_root")
        return root

    def job_directory(self, job_id: str) -> Path:
        root = self._root()
        job_id = canonical_job_id(job_id)
        candidate = root / job_id
        resolved = candidate.resolve(strict=False)
        if candidate.is_symlink() or resolved.parent != root:
            raise PathSecurityError("unsafe_job_path")
        return candidate

    def stage_input(self, job_id: str, source: str | os.PathLike[str]) -> Path:
        source_path = Path(source)
        if source_path.is_symlink() or not source_path.is_file():
            raise PathSecurityError("unsafe_translation_source")
        if source_path.stat().st_size > MAX_INPUT_BYTES:
            raise ValueError("translation_input_too_large")
        job = self.job_directory(job_id)
        work = job / "work"
        job.mkdir(mode=0o770, parents=False, exist_ok=False)
        work.mkdir(mode=0o770)
        os.chmod(job, 0o2770)
        os.chmod(work, 0o2770)
        temporary = work / ".input.pdf.tmp"
        target = work / "input.pdf"
        with source_path.open("rb") as reader, temporary.open("xb") as writer:
            shutil.copyfileobj(reader, writer, length=1024 * 1024)
            writer.flush()
            os.fsync(writer.fileno())
        os.chmod(temporary, 0o640)
        os.replace(temporary, target)
        return target

    def validated_result(self, job_id: str) -> tuple[Path, list[str]]:
        job = self.job_directory(job_id)
        work = job / "work"
        output = work / "input.zh.dual.pdf"
        if work.is_symlink() or output.is_symlink() or not output.is_file():
            raise PathSecurityError("unsafe_worker_output")
        if output.stat().st_size > MAX_OUTPUT_BYTES:
            raise ValueError("translation_output_too_large")
        total = 0
        for root, directories, files in os.walk(job, followlinks=False):
            for name in [*directories, *files]:
                candidate = Path(root) / name
                mode = os.lstat(candidate).st_mode
                if stat.S_ISLNK(mode):
                    raise PathSecurityError("symlink_in_translation_job")
                if stat.S_ISREG(mode):
                    total += candidate.stat().st_size
                    if total > MAX_JOB_BYTES:
                        raise ValueError("translation_job_too_large")
        logs: list[str] = []
        status_path = job / "status.json"
        if status_path.is_file() and not status_path.is_symlink():
            try:
                status = json.loads(status_path.read_text(encoding="utf-8"))
                raw_logs = status.get("logs", [])
                if isinstance(raw_logs, list):
                    logs = [str(item) for item in raw_logs]
            except (OSError, ValueError):
                pass
        return output, logs

    def promote_result(
        self,
        job_id: str,
        *,
        papers_root: str | os.PathLike[str],
        destination: str | os.PathLike[str],
        logs: list[str],
        log_destination: str | os.PathLike[str],
    ) -> None:
        output, _ = self.validated_result(job_id)
        destination_path = ensure_confined(papers_root, destination)
        log_path = ensure_confined(papers_root, log_destination)
        for source, target in ((output, destination_path),):
            fd, temporary_name = tempfile.mkstemp(
                prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
            )
            try:
                with os.fdopen(fd, "wb") as writer, source.open("rb") as reader:
                    shutil.copyfileobj(reader, writer, length=1024 * 1024)
                    writer.flush()
                    os.fsync(writer.fileno())
                os.chmod(temporary_name, 0o660)
                os.replace(temporary_name, target)
            finally:
                if os.path.exists(temporary_name):
                    os.unlink(temporary_name)
        encoded = "\n".join(logs).encode("utf-8")[:MAX_LOG_BYTES]
        fd, temporary_name = tempfile.mkstemp(
            prefix=f".{log_path.name}.", suffix=".tmp", dir=log_path.parent
        )
        try:
            with os.fdopen(fd, "wb") as writer:
                writer.write(encoded)
                writer.flush()
                os.fsync(writer.fileno())
            os.chmod(temporary_name, 0o660)
            os.replace(temporary_name, log_path)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)

    def cleanup(self, job_id: str) -> None:
        job = self.job_directory(job_id)
        if not job.exists():
            return
        for root, directories, files in os.walk(job, topdown=False, followlinks=False):
            for name in files:
                candidate = Path(root) / name
                if candidate.is_symlink():
                    candidate.unlink()
                else:
                    candidate.unlink()
            for name in directories:
                candidate = Path(root) / name
                if candidate.is_symlink():
                    candidate.unlink()
                else:
                    candidate.rmdir()
        job.rmdir()

    def cleanup_failed_older_than(self, seconds: int = 86400) -> None:
        cutoff = time.time() - seconds
        root = self._root()
        for child in root.iterdir():
            if child.is_dir() and not child.is_symlink() and child.stat().st_mtime < cutoff:
                try:
                    job_id = canonical_job_id(child.name)
                    status = self.get(job_id)
                    if status.get("status") in {"failed", "cancelled"}:
                        self.cleanup(job_id)
                except Exception:
                    continue
