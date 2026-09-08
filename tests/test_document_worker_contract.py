import json
import tempfile
import threading
import time
import unittest
import uuid
from pathlib import Path

from paperpilot.document_worker.app import create_worker_app
from paperpilot.document_worker.service import DocumentWorkerService


TOKEN = "d" * 48


class DocumentWorkerContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def _stage(self, kind="pdf_inspect", *, symlink=False):
        job_id = str(uuid.uuid4())
        work = self.root / job_id / "work"
        work.mkdir(parents=True)
        name = "input.pdf" if kind == "pdf_inspect" else ("input.rdf" if kind == "zotero_rdf" else "input.zip")
        if symlink:
            outside = self.root / "outside"
            outside.write_bytes(b"data")
            (work / name).symlink_to(outside)
        else:
            (work / name).write_bytes(b"data")
        return job_id, work

    @staticmethod
    def _headers():
        return {"Authorization": f"Bearer {TOKEN}"}

    def _client(self, executor=None, max_queue=32):
        service = DocumentWorkerService(self.root, executor=executor, max_queue=max_queue)
        return create_worker_app(token=TOKEN, service=service).test_client()

    def test_health_is_public_and_jobs_require_separate_token(self):
        client = self._client()
        self.assertEqual(client.get("/healthz").status_code, 200)
        self.assertEqual(client.get(f"/v1/jobs/{uuid.uuid4()}").status_code, 401)

    def test_create_accepts_only_uuid_and_kind(self):
        job_id, _ = self._stage()
        client = self._client()
        response = client.post(
            "/v1/jobs",
            json={"job_id": job_id, "kind": "pdf_inspect", "path": "/etc/passwd"},
            headers=self._headers(),
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("path", response.get_json()["error"])
        response = client.post(
            "/v1/jobs",
            json={"job_id": job_id.replace("-", ""), "kind": "pdf_inspect"},
            headers=self._headers(),
        )
        self.assertEqual(response.get_json()["error"], "invalid_job_id")

    def test_symlink_input_is_rejected(self):
        job_id, _ = self._stage(symlink=True)
        response = self._client().post(
            "/v1/jobs", json={"job_id": job_id, "kind": "pdf_inspect"}, headers=self._headers()
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()["error"], "unsafe_input")

    def test_jobs_are_processed_one_at_a_time_and_queue_is_bounded(self):
        first_id, first_work = self._stage()
        second_id, second_work = self._stage()
        release = threading.Event()
        running = []

        def executor(job_id, _kind, _state):
            running.append(job_id)
            if job_id == first_id:
                release.wait(2)
            output = (first_work if job_id == first_id else second_work) / "output"
            output.mkdir()
            (output / "result.json").write_text("{}")

        client = self._client(executor, max_queue=2)
        first = client.post("/v1/jobs", json={"job_id": first_id, "kind": "pdf_inspect"}, headers=self._headers())
        second = client.post("/v1/jobs", json={"job_id": second_id, "kind": "pdf_inspect"}, headers=self._headers())
        third_id, _ = self._stage()
        third = client.post("/v1/jobs", json={"job_id": third_id, "kind": "pdf_inspect"}, headers=self._headers())
        self.assertEqual(first.status_code, 202)
        self.assertEqual(second.status_code, 202)
        self.assertEqual(third.status_code, 429)
        self.assertEqual(running, [first_id])
        release.set()
        for _ in range(100):
            state = client.get(f"/v1/jobs/{second_id}", headers=self._headers()).get_json()
            if state["status"] == "completed":
                break
            time.sleep(0.01)
        self.assertEqual(running, [first_id, second_id])

    def test_restart_marks_queued_and_running_jobs_interrupted(self):
        for status in ("queued", "running"):
            job_id, _ = self._stage()
            state = {
                "job_id": job_id,
                "kind": "pdf_inspect",
                "status": status,
                "progress": 10,
                "created_at": time.time(),
                "updated_at": time.time(),
                "error": None,
                "output": None,
            }
            (self.root / job_id / "status.json").write_text(json.dumps(state))
            restored = DocumentWorkerService(self.root).public_state(job_id)
            self.assertEqual(restored["status"], "failed")
            self.assertEqual(restored["error"], "interrupted")


if __name__ == "__main__":
    unittest.main()
