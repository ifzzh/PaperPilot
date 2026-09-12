from __future__ import annotations

import json
import io
import os
import signal
import subprocess
import tempfile
import threading
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import Mock, call, patch

from ipaper.translation_worker.app import create_worker_app
from ipaper.translation_worker.service import (
    TranslationWorkerService,
    WorkerLimits,
    redact_text,
)


TOKEN = "t" * 48


class WorkerContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def _job(self, *, symlink: bool = False):
        job_id = str(uuid.uuid4())
        work = self.root / job_id / "work"
        work.mkdir(parents=True)
        if symlink:
            outside = self.root / "outside.pdf"
            outside.write_bytes(b"%PDF-outside")
            (work / "input.pdf").symlink_to(outside)
        else:
            (work / "input.pdf").write_bytes(b"%PDF-test")
        return job_id, work

    def _client(self, executor=None):
        service = TranslationWorkerService(self.root, executor=executor)
        return create_worker_app(token=TOKEN, service=service).test_client()

    @staticmethod
    def _payload(job_id: str):
        return {
            "job_id": job_id,
            "model": "fake-model",
            "base_url": "http://fake.invalid/v1",
            "api_key": "secret-key",
        }

    @staticmethod
    def _headers():
        return {"Authorization": f"Bearer {TOKEN}"}

    def test_health_is_public_but_job_api_requires_token(self):
        client = self._client()
        self.assertEqual(client.get("/healthz").status_code, 200)
        self.assertEqual(client.get(f"/v1/jobs/{uuid.uuid4()}").status_code, 401)

    def test_create_rejects_paths_and_unknown_fields(self):
        job_id, _ = self._job()
        payload = self._payload(job_id)
        payload["input_path"] = "/etc/passwd"
        response = self._client().post("/v1/jobs", json=payload, headers=self._headers())
        self.assertEqual(response.status_code, 400)
        self.assertIn("input_path", response.get_json()["error"])

    def test_create_rejects_noncanonical_uuid(self):
        job_id, _ = self._job()
        payload = self._payload(job_id.replace("-", ""))
        response = self._client().post("/v1/jobs", json=payload, headers=self._headers())
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"], "invalid_job_id")

    def test_create_rejects_symlink_input(self):
        job_id, _ = self._job(symlink=True)
        response = self._client().post(
            "/v1/jobs", json=self._payload(job_id), headers=self._headers()
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()["error"], "unsafe_input")

    def test_completed_job_exposes_fixed_output_name_without_secret(self):
        job_id, work = self._job()

        def executor(_job_id, _model, _base_url, _api_key, _state):
            (work / "input.zh.dual.pdf").write_bytes(b"%PDF-translated")

        client = self._client(executor)
        response = client.post(
            "/v1/jobs", json=self._payload(job_id), headers=self._headers()
        )
        self.assertEqual(response.status_code, 202)
        for _ in range(100):
            state = client.get(f"/v1/jobs/{job_id}", headers=self._headers()).get_json()
            if state["status"] == "completed":
                break
            time.sleep(0.01)
        self.assertEqual(state["output"], "input.zh.dual.pdf")
        self.assertNotIn("secret-key", str(state))
        self.assertNotIn("base_url", str(state))

    def test_only_one_job_can_run(self):
        first_id, first_work = self._job()
        second_id, _ = self._job()
        release = threading.Event()

        def executor(job_id, _model, _base_url, _api_key, _state):
            release.wait(2)
            if job_id == first_id:
                (first_work / "input.zh.dual.pdf").write_bytes(b"%PDF-result")

        client = self._client(executor)
        first = client.post(
            "/v1/jobs", json=self._payload(first_id), headers=self._headers()
        )
        second = client.post(
            "/v1/jobs", json=self._payload(second_id), headers=self._headers()
        )
        release.set()
        self.assertEqual(first.status_code, 202)
        self.assertEqual(second.status_code, 409)
        self.assertEqual(second.get_json()["error"], "worker_busy")
        for _ in range(100):
            state = client.get(
                f"/v1/jobs/{first_id}", headers=self._headers()
            ).get_json()
            if state["status"] == "completed":
                break
            time.sleep(0.01)
        self.assertEqual(state["status"], "completed")

    def test_restart_marks_incomplete_job_paused_and_recoverable(self):
        job_id, _ = self._job()
        status = {
            "job_id": job_id,
            "status": "running",
            "progress": 42,
            "created_at": time.time(),
            "updated_at": time.time(),
            "error": None,
            "output": None,
        }
        (self.root / job_id / "status.json").write_text(json.dumps(status))

        recovered = TranslationWorkerService(self.root).public_state(job_id)

        self.assertEqual(recovered["status"], "paused")
        self.assertEqual(recovered["error"], "interrupted")

    def test_structured_progress_is_exposed_without_terminal_formatting(self):
        job_id, _ = self._job()
        service = TranslationWorkerService(self.root)
        state = {
            "job_id": job_id, "logs": [], "progress": 0, "stage": None,
            "event_sequence": 0, "created_at": time.time(), "updated_at": time.time(),
            "status": "running", "error": None, "output": None,
        }
        service._consume_output_line(
            state,
            'IPAPER_EVENT\t{"type":"progress_update","stage":"translate","overall_progress":37.5,"stage_progress":50,"stage_current":2,"stage_total":4}\n',
            (),
        )
        self.assertEqual(state["progress"], 37)
        self.assertEqual(state["stage"], "translate")
        self.assertEqual(state["stage_current"], 2)
        self.assertEqual(service._read_events(job_id)[0]["kind"], "progress")

    def test_output_limit_fails_job(self):
        job_id, work = self._job()

        def executor(_job_id, _model, _base_url, _api_key, _state):
            (work / "input.zh.dual.pdf").write_bytes(b"too-large")

        service = TranslationWorkerService(
            self.root,
            limits=WorkerLimits(max_output_bytes=4),
            executor=executor,
        )
        client = create_worker_app(token=TOKEN, service=service).test_client()
        client.post("/v1/jobs", json=self._payload(job_id), headers=self._headers())
        for _ in range(100):
            state = client.get(f"/v1/jobs/{job_id}", headers=self._headers()).get_json()
            if state["status"] == "failed":
                break
            time.sleep(0.01)
        self.assertEqual(state["error"], "output_too_large")

    def test_log_redaction_covers_headers_cookies_and_keys(self):
        secret = "super-secret"
        redacted = redact_text(
            "Authorization: Bearer super-secret Cookie=session API_KEY=super-secret",
            (secret,),
        )
        self.assertNotIn(secret, redacted)
        self.assertNotIn("session", redacted)

    def test_worker_log_redacts_job_paths_and_command_arguments(self):
        job_id, _ = self._job()
        service = TranslationWorkerService(self.root)
        state = {"job_id": job_id, "logs": [], "progress": 0}
        service._append_log(
            state,
            f"output={self.root / job_id}/work/input.pdf model=fake-model \x1b[31m",
            ("fake-model",),
        )
        self.assertNotIn(str(self.root), state["logs"][0])
        self.assertNotIn("fake-model", state["logs"][0])
        self.assertNotIn("\x1b", state["logs"][0])

    def test_process_group_cancel_escalates_after_grace_period(self):
        service = TranslationWorkerService(self.root)
        process = Mock(pid=1234)
        process.poll.return_value = None
        process.wait.side_effect = [subprocess.TimeoutExpired("babeldoc", 10), None]
        with patch("os.killpg") as killpg:
            service._terminate_process_group(process)
        self.assertEqual(
            killpg.call_args_list,
            [call(1234, signal.SIGTERM), call(1234, signal.SIGKILL)],
        )

    def test_babeldoc_runner_is_importable_from_job_working_directory(self):
        job_id, work = self._job()
        service = TranslationWorkerService(self.root)
        process = Mock()
        process.stdin = io.StringIO()
        process.stdout = io.StringIO("")
        process.poll.return_value = 0
        process.returncode = 0
        state = {"job_id": job_id, "logs": [], "cancel": threading.Event()}

        with patch("ipaper.translation_worker.service.subprocess.Popen", return_value=process) as popen:
            service._execute_babeldoc(job_id, "fake-model", "https://fake.invalid/v1", "secret", state)

        kwargs = popen.call_args.kwargs
        self.assertEqual(Path(kwargs["cwd"]), work)
        application_root = str(Path(__file__).resolve().parents[1])
        self.assertIn(application_root, kwargs["env"]["PYTHONPATH"].split(os.pathsep))

    def test_babeldoc_nonzero_exit_uses_stable_error_code(self):
        job_id, _ = self._job()
        service = TranslationWorkerService(self.root)
        process = Mock()
        process.stdin = io.StringIO()
        process.stdout = io.StringIO("")
        process.poll.return_value = 1
        process.returncode = 23
        state = {"job_id": job_id, "logs": [], "cancel": threading.Event()}

        with patch("ipaper.translation_worker.service.subprocess.Popen", return_value=process):
            with self.assertRaisesRegex(RuntimeError, "^babeldoc_failed$"):
                service._execute_babeldoc(
                    job_id, "fake-model", "https://fake.invalid/v1", "secret", state
                )


if __name__ == "__main__":
    unittest.main()
