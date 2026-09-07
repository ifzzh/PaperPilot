from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


MAX_INPUT_BYTES = 512 * 1024 * 1024
MAX_OUTPUT_BYTES = 1024 * 1024 * 1024
MAX_JOB_BYTES = 2 * 1024 * 1024 * 1024
MAX_LOG_BYTES = 1024 * 1024
JOB_TIMEOUT_SECONDS = 3600
TERMINATE_GRACE_SECONDS = 10
TERMINAL_STATES = frozenset({"completed", "failed", "cancelled"})
_PROGRESS_RE = re.compile(r"(?<!\d)(\d{1,3})(?:\.\d+)?\s*%")


class WorkerRequestError(ValueError):
    def __init__(self, reason: str, status_code: int = 400) -> None:
        super().__init__(reason)
        self.reason = reason
        self.status_code = status_code


@dataclass(frozen=True)
class WorkerLimits:
    max_input_bytes: int = MAX_INPUT_BYTES
    max_output_bytes: int = MAX_OUTPUT_BYTES
    max_job_bytes: int = MAX_JOB_BYTES
    max_log_bytes: int = MAX_LOG_BYTES
    timeout_seconds: int = JOB_TIMEOUT_SECONDS
    terminate_grace_seconds: int = TERMINATE_GRACE_SECONDS


def canonical_job_id(value: object) -> str:
    if not isinstance(value, str):
        raise WorkerRequestError("invalid_job_id")
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError) as exc:
        raise WorkerRequestError("invalid_job_id") from exc
    if str(parsed) != value.lower():
        raise WorkerRequestError("invalid_job_id")
    return str(parsed)


def redact_text(value: object, secrets: tuple[str, ...] = ()) -> str:
    text = str(value)
    for secret in secrets:
        if secret:
            text = text.replace(secret, "***")
    text = re.sub(
        r"(?i)(authorization|cookie|api[-_ ]?key)(\s*[:=]\s*)([^\s,;]+)",
        r"\1\2***",
        text,
    )
    return text


class TranslationWorkerService:
    def __init__(
        self,
        jobs_root: str | os.PathLike[str],
        *,
        limits: WorkerLimits | None = None,
        executor: Callable[..., None] | None = None,
    ) -> None:
        self.root = Path(jobs_root).resolve(strict=True)
        if not self.root.is_dir() or self.root.is_symlink():
            raise RuntimeError("jobs_root must be a real directory")
        self.limits = limits or WorkerLimits()
        self._executor = executor or self._execute_babeldoc
        self._lock = threading.RLock()
        self._jobs: dict[str, dict] = {}
        self._recover_interrupted_jobs()

    def _paths(self, job_id: str) -> tuple[Path, Path, Path]:
        job_id = canonical_job_id(job_id)
        job = self.root / job_id
        work = job / "work"
        status = job / "status.json"
        for candidate in (job, work, status):
            if candidate.exists() and candidate.is_symlink():
                raise WorkerRequestError("unsafe_job_path", 409)
            try:
                candidate.resolve(strict=False).relative_to(self.root)
            except ValueError as exc:
                raise WorkerRequestError("unsafe_job_path", 409) from exc
        return job, work, status

    def _write_status(self, job_id: str, state: dict) -> None:
        job, _, status_path = self._paths(job_id)
        job.mkdir(mode=0o770, parents=False, exist_ok=True)
        payload = {
            "job_id": job_id,
            "status": state["status"],
            "progress": int(state.get("progress", 0)),
            "created_at": state["created_at"],
            "updated_at": state["updated_at"],
            "error": state.get("error"),
            "output": state.get("output"),
        }
        temporary = status_path.with_suffix(".tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o640)
        os.replace(temporary, status_path)

    def _recover_interrupted_jobs(self) -> None:
        for status_path in self.root.glob("*/status.json"):
            try:
                state = json.loads(status_path.read_text(encoding="utf-8"))
                job_id = canonical_job_id(state.get("job_id"))
                if state.get("status") in {"queued", "running"}:
                    state.update(
                        status="failed",
                        error="interrupted",
                        updated_at=time.time(),
                    )
                    self._write_status(job_id, state)
                self._jobs[job_id] = state
            except Exception:
                continue

    def submit(self, payload: object) -> dict:
        if not isinstance(payload, dict):
            raise WorkerRequestError("invalid_json")
        allowed = {"job_id", "model", "base_url", "api_key"}
        unknown = sorted(set(payload) - allowed)
        if unknown:
            raise WorkerRequestError("unknown_fields:" + ",".join(unknown))
        if set(payload) != allowed or not all(
            isinstance(payload.get(key), str) and payload[key].strip()
            for key in allowed
        ):
            raise WorkerRequestError("missing_required_fields")
        if (
            len(payload["model"]) > 256
            or len(payload["base_url"]) > 2048
            or len(payload["api_key"]) > 8192
        ):
            raise WorkerRequestError("field_too_large", 413)

        job_id = canonical_job_id(payload["job_id"])
        job, work, _ = self._paths(job_id)
        input_pdf = work / "input.pdf"
        if not work.is_dir() or work.is_symlink():
            raise WorkerRequestError("missing_input", 409)
        if input_pdf.is_symlink() or not input_pdf.is_file():
            raise WorkerRequestError("unsafe_input", 409)
        if input_pdf.stat().st_size > self.limits.max_input_bytes:
            raise WorkerRequestError("input_too_large", 413)

        with self._lock:
            if any(item["status"] in {"queued", "running"} for item in self._jobs.values()):
                raise WorkerRequestError("worker_busy", 409)
            if job_id in self._jobs:
                raise WorkerRequestError("job_exists", 409)
            now = time.time()
            state = {
                "job_id": job_id,
                "status": "queued",
                "progress": 0,
                "created_at": now,
                "updated_at": now,
                "error": None,
                "output": None,
                "process": None,
                "cancel": threading.Event(),
                "logs": [],
            }
            self._jobs[job_id] = state
            self._write_status(job_id, state)
            thread = threading.Thread(
                target=self._run,
                args=(job_id, payload["model"], payload["base_url"], payload["api_key"]),
                daemon=True,
            )
            thread.start()
        return self.public_state(job_id)

    def _append_log(self, state: dict, line: str, secrets: tuple[str, ...]) -> None:
        safe = line.rstrip().replace(str(self.root / state["job_id"]), "<job>")
        safe = safe.replace(str(self.root), "<jobs>")
        safe = redact_text(safe, secrets)
        safe = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", safe)
        safe = "".join(character for character in safe if character == "\t" or ord(character) >= 32)
        current = sum(len(item.encode("utf-8")) + 1 for item in state["logs"])
        remaining = self.limits.max_log_bytes - current
        if remaining <= 0:
            return
        encoded = safe.encode("utf-8")[:remaining]
        safe = encoded.decode("utf-8", errors="ignore")
        if safe:
            state["logs"].append(safe)
        match = _PROGRESS_RE.search(safe)
        if match:
            state["progress"] = max(state["progress"], min(100, int(match.group(1))))

    def _run(self, job_id: str, model: str, base_url: str, api_key: str) -> None:
        state = self._jobs[job_id]
        final: dict = {}
        with self._lock:
            state.update(status="running", updated_at=time.time())
            self._write_status(job_id, state)
        try:
            self._executor(job_id, model, base_url, api_key, state)
            if state["cancel"].is_set():
                final.update(status="cancelled", error="cancelled")
            else:
                output = self._validate_output(job_id)
                final.update(status="completed", progress=100, output=output.name)
        except TimeoutError:
            final.update(status="failed", error="timeout")
        except Exception as exc:  # noqa: BLE001
            final.update(status="failed", error=redact_text(exc, (api_key,))[:512])
        finally:
            with self._lock:
                state.update(final)
                state["process"] = None
                state["updated_at"] = time.time()
                self._write_status(job_id, state)
            api_key = ""  # minimize lifetime of the only local reference

    def _execute_babeldoc(self, job_id: str, model: str, base_url: str, api_key: str, state: dict) -> None:
        _, work, _ = self._paths(job_id)
        command = [
            "babeldoc", "--openai", "--openai-model", model,
            "--openai-base-url", base_url, "--openai-api-key", api_key,
            "--files", "input.pdf",
        ]
        process = subprocess.Popen(
            command,
            cwd=work,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,
        )
        state["process"] = process
        assert process.stdout is not None
        reader = threading.Thread(
            target=self._read_output,
            args=(process.stdout, state, (api_key, base_url, model)),
            daemon=True,
        )
        reader.start()
        started = time.monotonic()
        while process.poll() is None:
            if state["cancel"].is_set():
                self._terminate_process_group(process)
                break
            if time.monotonic() - started > self.limits.timeout_seconds:
                self._terminate_process_group(process)
                raise TimeoutError
            if self._job_size(job_id) > self.limits.max_job_bytes:
                self._terminate_process_group(process)
                raise RuntimeError("job_too_large")
            time.sleep(0.5)
        reader.join(timeout=2)
        if state["cancel"].is_set():
            return
        if process.returncode != 0:
            raise RuntimeError(f"babeldoc_failed:{process.returncode}")

    def _read_output(self, pipe, state: dict, secrets: tuple[str, ...]) -> None:
        try:
            for line in iter(pipe.readline, ""):
                self._append_log(state, line, secrets)
        finally:
            pipe.close()

    def _terminate_process_group(self, process: subprocess.Popen) -> None:
        if process.poll() is not None:
            return
        try:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=self.limits.terminate_grace_seconds)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
        except ProcessLookupError:
            pass

    def _validate_output(self, job_id: str) -> Path:
        job, work, _ = self._paths(job_id)
        output = work / "input.zh.dual.pdf"
        if output.is_symlink() or not output.is_file():
            raise RuntimeError("output_missing_or_unsafe")
        if output.stat().st_size > self.limits.max_output_bytes:
            raise RuntimeError("output_too_large")
        if self._job_size(job_id) > self.limits.max_job_bytes:
            raise RuntimeError("job_too_large")
        return output

    def _job_size(self, job_id: str) -> int:
        job, _, _ = self._paths(job_id)
        total = 0
        for root, directories, files in os.walk(job, followlinks=False):
            for name in [*directories, *files]:
                path = Path(root) / name
                if path.is_symlink():
                    raise RuntimeError("symlink_in_job")
                if path.is_file():
                    total += path.stat().st_size
        return total

    def public_state(self, job_id: str) -> dict:
        job_id = canonical_job_id(job_id)
        with self._lock:
            state = self._jobs.get(job_id)
            if state is None:
                _, _, status_path = self._paths(job_id)
                if not status_path.is_file() or status_path.is_symlink():
                    raise WorkerRequestError("job_not_found", 404)
                state = json.loads(status_path.read_text(encoding="utf-8"))
            return {
                "job_id": job_id,
                "status": state["status"],
                "progress": int(state.get("progress", 0)),
                "logs": list(state.get("logs", [])),
                "created_at": state.get("created_at"),
                "updated_at": state.get("updated_at"),
                "error": state.get("error"),
                "output": state.get("output"),
            }

    def cancel(self, job_id: str) -> dict:
        job_id = canonical_job_id(job_id)
        with self._lock:
            state = self._jobs.get(job_id)
            if state is None:
                raise WorkerRequestError("job_not_found", 404)
            if state["status"] in TERMINAL_STATES:
                return self.public_state(job_id)
            state["cancel"].set()
            process = state.get("process")
        if process is not None:
            self._terminate_process_group(process)
        return self.public_state(job_id)
