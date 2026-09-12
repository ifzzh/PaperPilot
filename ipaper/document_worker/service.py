from __future__ import annotations

import json
import os
import resource
import signal
import subprocess
import sys
import threading
import time
import uuid
from collections import deque
from pathlib import Path

from .safety import DocumentLimitError, DocumentLimits


TERMINAL_STATES = frozenset({"completed", "failed", "cancelled"})
JOB_KINDS = frozenset({"pdf_inspect", "metadata_zip", "mineru_zip", "zotero_rdf", "pdf_split", "mineru_structure", "pdf_page_text"})
INPUT_NAMES = {
    "pdf_page_text": "input.pdf",
    "pdf_split": "input.pdf",
    "mineru_structure": "input.zip",
    "pdf_inspect": "input.pdf",
    "metadata_zip": "input.zip",
    "mineru_zip": "input.zip",
    "zotero_rdf": "input.rdf",
}
TIMEOUTS = {
    "pdf_page_text": 90,
    "pdf_split": 300,
    "mineru_structure": 300,
    "pdf_inspect": 90,
    "metadata_zip": 300,
    "mineru_zip": 300,
    "zotero_rdf": 120,
}


class DocumentWorkerError(ValueError):
    def __init__(self, reason: str, status_code: int = 400) -> None:
        super().__init__(reason)
        self.reason = reason
        self.status_code = status_code


def canonical_job_id(value: object) -> str:
    if not isinstance(value, str):
        raise DocumentWorkerError("invalid_job_id")
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError) as exc:
        raise DocumentWorkerError("invalid_job_id") from exc
    if str(parsed) != value.lower():
        raise DocumentWorkerError("invalid_job_id")
    return str(parsed)


class DocumentWorkerService:
    def __init__(
        self,
        jobs_root: str | os.PathLike[str],
        *,
        limits: DocumentLimits | None = None,
        executor=None,
        max_queue: int = 32,
    ) -> None:
        self.root = Path(jobs_root).resolve(strict=True)
        if self.root.is_symlink() or not self.root.is_dir():
            raise RuntimeError("unsafe_jobs_root")
        self.limits = limits or DocumentLimits()
        self.executor = executor or self._execute_subprocess
        self.max_queue = max_queue
        self._condition = threading.Condition(threading.RLock())
        self._jobs: dict[str, dict] = {}
        self._queue: deque[str] = deque()
        self._recover()
        self._dispatcher = threading.Thread(target=self._dispatch, daemon=True)
        self._dispatcher.start()

    def _paths(self, job_id: str) -> tuple[Path, Path, Path, Path]:
        job_id = canonical_job_id(job_id)
        job = self.root / job_id
        work = job / "work"
        output = work / "output"
        status_path = job / "status.json"
        for path in (job, work, output, status_path):
            if path.is_symlink():
                raise DocumentWorkerError("unsafe_job_path", 409)
            try:
                path.resolve(strict=False).relative_to(self.root)
            except ValueError as exc:
                raise DocumentWorkerError("unsafe_job_path", 409) from exc
        return job, work, output, status_path

    def _write_status(self, job_id: str, state: dict) -> None:
        job, _, _, status_path = self._paths(job_id)
        job.mkdir(mode=0o770, parents=False, exist_ok=True)
        payload = {
            "job_id": job_id,
            "kind": state["kind"],
            "status": state["status"],
            "progress": int(state.get("progress", 0)),
            "created_at": state["created_at"],
            "updated_at": state["updated_at"],
            "error": state.get("error"),
            "output": state.get("output"),
        }
        temporary = status_path.with_suffix(".tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o640)
        os.replace(temporary, status_path)

    def _recover(self) -> None:
        for status_path in self.root.glob("*/status.json"):
            try:
                state = json.loads(status_path.read_text(encoding="utf-8"))
                job_id = canonical_job_id(state.get("job_id"))
                if state.get("status") in {"queued", "running"}:
                    state.update(status="failed", error="interrupted", updated_at=time.time())
                    self._write_status(job_id, state)
                self._jobs[job_id] = state
            except Exception:
                continue

    def submit(self, payload: object) -> dict:
        if not isinstance(payload, dict):
            raise DocumentWorkerError("invalid_json")
        if set(payload) != {"job_id", "kind"}:
            unknown = sorted(set(payload) - {"job_id", "kind"})
            reason = "unknown_fields:" + ",".join(unknown) if unknown else "missing_required_fields"
            raise DocumentWorkerError(reason)
        job_id = canonical_job_id(payload.get("job_id"))
        kind = payload.get("kind")
        if kind not in JOB_KINDS:
            raise DocumentWorkerError("unsupported_document_kind")
        _, work, _, _ = self._paths(job_id)
        source = work / INPUT_NAMES[kind]
        if not work.is_dir() or work.is_symlink() or source.is_symlink() or not source.is_file():
            raise DocumentWorkerError("unsafe_input", 409)
        maximum = {
            "pdf_inspect": self.limits.max_pdf_bytes,
            "pdf_split": self.limits.max_pdf_bytes,
            "pdf_page_text": self.limits.max_pdf_bytes,
            "mineru_structure": self.limits.max_archive_bytes,
            "metadata_zip": self.limits.max_archive_bytes,
            "mineru_zip": self.limits.max_archive_bytes,
            "zotero_rdf": self.limits.max_rdf_bytes,
        }[kind]
        if source.stat().st_size > maximum:
            raise DocumentWorkerError("upload_too_large", 413)
        if kind == "pdf_page_text":
            selection = work / "page.json"
            if selection.is_symlink() or not selection.is_file() or selection.stat().st_size > 1024:
                raise DocumentWorkerError("unsafe_input", 409)
        if kind == "mineru_structure":
            pdf = work / "source.pdf"
            if pdf.is_symlink() or not pdf.is_file():
                raise DocumentWorkerError("unsafe_input", 409)
            if pdf.stat().st_size > self.limits.max_pdf_bytes:
                raise DocumentWorkerError("upload_too_large", 413)
        with self._condition:
            active_count = sum(
                state["status"] in {"queued", "running"} for state in self._jobs.values()
            )
            if active_count >= self.max_queue:
                raise DocumentWorkerError("document_queue_full", 429)
            if job_id in self._jobs:
                raise DocumentWorkerError("job_exists", 409)
            now = time.time()
            state = {
                "job_id": job_id,
                "kind": kind,
                "status": "queued",
                "progress": 0,
                "created_at": now,
                "updated_at": now,
                "error": None,
                "output": None,
                "process": None,
                "cancel": threading.Event(),
            }
            self._jobs[job_id] = state
            self._queue.append(job_id)
            self._write_status(job_id, state)
            self._condition.notify()
        return self.public_state(job_id)

    def _dispatch(self) -> None:
        while True:
            try:
                with self._condition:
                    while not self._queue:
                        self._condition.wait()
                    job_id = self._queue.popleft()
                    state = self._jobs.get(job_id)
                    if state is None or state["status"] != "queued":
                        continue
                    state.update(status="running", progress=10, updated_at=time.time())
                    self._write_status(job_id, state)
                self._run(job_id)
            except Exception:
                # A corrupt status file or one failed task must not permanently stop
                # the single worker dispatcher.
                with self._condition:
                    state = self._jobs.get(locals().get("job_id"))
                    if state and state.get("status") not in TERMINAL_STATES:
                        state.update(
                            status="failed", error="document_processing_failed",
                            process=None, updated_at=time.time(),
                        )
                        try:
                            self._write_status(state["job_id"], state)
                        except Exception:
                            pass
                    self._condition.notify_all()

    def _run(self, job_id: str) -> None:
        state = self._jobs[job_id]
        final = {}
        try:
            self.executor(job_id, state["kind"], state)
            if state["cancel"].is_set():
                final = {"status": "cancelled", "error": "cancelled"}
            else:
                self._validate_output(job_id, state["kind"])
                final = {"status": "completed", "progress": 100, "output": "output"}
        except DocumentLimitError as exc:
            final = {"status": "failed", "error": exc.reason}
        except TimeoutError:
            final = {"status": "failed", "error": "document_job_timeout"}
        except Exception:
            final = {"status": "failed", "error": "document_processing_failed"}
        with self._condition:
            state.update(final, process=None, updated_at=time.time())
            self._write_status(job_id, state)
            self._condition.notify_all()

    @staticmethod
    def _resource_limits() -> None:
        resource.setrlimit(resource.RLIMIT_CPU, (310, 310))
        resource.setrlimit(resource.RLIMIT_AS, (2 * 1024**3, 2 * 1024**3))
        resource.setrlimit(resource.RLIMIT_FSIZE, (2 * 1024**3, 2 * 1024**3))
        resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
        try:
            resource.setrlimit(resource.RLIMIT_NPROC, (64, 64))
        except (ValueError, OSError):
            pass

    def _execute_subprocess(self, job_id: str, kind: str, state: dict) -> None:
        job, _, _, _ = self._paths(job_id)
        process = subprocess.Popen(
            [sys.executable, "-m", "ipaper.document_worker.runner", str(job), kind],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            preexec_fn=self._resource_limits,
        )
        state["process"] = process
        started = time.monotonic()
        timeout = TIMEOUTS[kind]
        while process.poll() is None:
            if state["cancel"].is_set():
                self._terminate(process)
                return
            if time.monotonic() - started > timeout:
                self._terminate(process)
                raise TimeoutError
            time.sleep(0.2)
        if process.returncode != 0:
            raise RuntimeError("document_subprocess_failed")

    @staticmethod
    def _terminate(process: subprocess.Popen) -> None:
        if process.poll() is not None:
            return
        try:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
        except ProcessLookupError:
            return

    def _validate_output(self, job_id: str, kind: str) -> None:
        _, _, output, _ = self._paths(job_id)
        if output.is_symlink() or not output.is_dir():
            raise RuntimeError("unsafe_worker_output")
        required = "result.json" if kind in {"pdf_inspect", "zotero_rdf", "pdf_page_text"} else "manifest.json"
        result = output / required
        if result.is_symlink() or not result.is_file() or result.stat().st_size > 4 * 1024 * 1024:
            raise RuntimeError("unsafe_worker_output")
        for root, directories, files in os.walk(output, followlinks=False):
            for name in [*directories, *files]:
                if (Path(root) / name).is_symlink():
                    raise RuntimeError("unsafe_worker_output")

    def public_state(self, job_id: str) -> dict:
        job_id = canonical_job_id(job_id)
        with self._condition:
            state = self._jobs.get(job_id)
            if state is None:
                _, _, _, status_path = self._paths(job_id)
                if status_path.is_symlink() or not status_path.is_file():
                    raise DocumentWorkerError("job_not_found", 404)
                state = json.loads(status_path.read_text(encoding="utf-8"))
            return {
                name: state.get(name)
                for name in ("job_id", "kind", "status", "progress", "created_at", "updated_at", "error", "output")
            }

    def release(self, job_id: str) -> dict:
        job_id = canonical_job_id(job_id)
        with self._condition:
            state = self._jobs.get(job_id)
            if state is None:
                return {"job_id": job_id, "released": True}
            if state["status"] not in TERMINAL_STATES:
                state["cancel"].set()
                if state["status"] == "queued":
                    state.update(status="cancelled", error="cancelled", updated_at=time.time())
                    self._write_status(job_id, state)
                    self._condition.notify_all()
                process = state.get("process")
            else:
                process = None
        if process is not None:
            self._terminate(process)
        with self._condition:
            deadline = time.monotonic() + 10
            while state.get("status") not in TERMINAL_STATES and time.monotonic() < deadline:
                self._condition.wait(timeout=0.1)
            if state.get("status") not in TERMINAL_STATES:
                state.update(
                    status="cancelled", error="cancelled", process=None,
                    updated_at=time.time(),
                )
                try:
                    self._write_status(job_id, state)
                except Exception:
                    pass
            self._jobs.pop(job_id, None)
            self._condition.notify_all()
        return {"job_id": job_id, "released": True}

    def cancel(self, job_id: str) -> dict:
        """Backward-compatible alias: DELETE now cancels and releases the job."""
        return self.release(job_id)

    def queue_stats(self) -> dict:
        with self._condition:
            running = sum(
                state.get("status") == "running" for state in self._jobs.values()
            )
            queued = sum(
                state.get("status") == "queued" for state in self._jobs.values()
            )
        return {"busy": bool(running), "queued": queued}
