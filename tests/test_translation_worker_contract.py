from __future__ import annotations

import tempfile
import threading
import time
import unittest
import uuid
from pathlib import Path

from paperpilot.translation_worker.app import create_worker_app
from paperpilot.translation_worker.service import TranslationWorkerService


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


if __name__ == "__main__":
    unittest.main()
