import io
import json
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from flask import Flask

from paperpilot.core.paper_store import PaperStore
from paperpilot.database import connection
from paperpilot.database.models import SCHEMA_SCRIPT
from paperpilot.document_worker.safety import DocumentLimits, bounded_copy
from paperpilot.routes.basic_routes.upload_from_pdf_route import register_upload_from_pdf_routes


class ImmediateDocumentClient:
    def __init__(self, root):
        self.jobs_root = Path(root)
        self.limits = DocumentLimits(max_pdf_bytes=1024)

    def health(self):
        return True

    def job_directory(self, job_id):
        return self.jobs_root / job_id

    def stage(self, job_id, _kind, stream):
        work = self.job_directory(job_id) / "work"
        work.mkdir(parents=True)
        bounded_copy(stream, work / "input.pdf", self.limits.max_pdf_bytes)
        output = work / "output"
        output.mkdir()
        (output / "result.json").write_text(json.dumps({
            "page_count": 1,
            "metadata": {"title": "Safe title", "author": "Author"},
        }))

    def create(self, job_id, kind):
        return {"job_id": job_id, "kind": kind, "status": "queued"}

    def get(self, job_id):
        return {"job_id": job_id, "kind": "pdf_inspect", "status": "completed", "progress": 100, "error": None}

    def result_json(self, job_id):
        return json.loads((self.job_directory(job_id) / "work/output/result.json").read_text())

    def cleanup(self, _job_id):
        return None


class DocumentUploadFlowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = self.root / "paperpilot.db"
        sqlite3.connect(self.db).executescript(SCHEMA_SCRIPT).close()
        connection.close_db()
        self.path_patch = patch.object(connection, "DB_PATH", str(self.db))
        self.path_patch.start()
        self.papers = self.root / "papers"
        self.papers.mkdir()
        self.jobs = self.root / "jobs"
        self.jobs.mkdir()
        self.store = PaperStore()
        self.saved = []
        app = Flask(__name__)
        app.config["TESTING"] = True
        register_upload_from_pdf_routes(
            app,
            get_categories=lambda: {"id": "root", "children": []},
            get_category_path=lambda _categories, category_id: ["Root", category_id],
            create_category_folder=lambda _category_id: str(self.papers),
            save_paper_metadata=lambda path, paper: self.saved.append((path, paper.id)),
            reading_list_file=str(self.root / "reading.json"),
            paper_store=self.store,
            document_client=ImmediateDocumentClient(self.jobs),
        )
        self.client = app.test_client()

    def tearDown(self):
        connection.close_db()
        self.path_patch.stop()
        self.temp.cleanup()

    def test_upload_is_queued_then_promoted_after_worker_completion(self):
        response = self.client.post(
            "/api/upload",
            data={"category_id": "cat", "file": (io.BytesIO(b"%PDF-safe"), "input.pdf")},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 202)
        task_id = response.get_json()["task_id"]
        for _ in range(100):
            status = self.client.get(f"/api/upload/{task_id}").get_json()
            if status["status"] == "completed":
                break
            time.sleep(0.01)
        self.assertEqual(status["paper"]["title"], "Safe title")
        self.assertEqual(len(list(self.papers.glob("*.pdf"))), 1)
        self.assertEqual(len(self.store.iter_all()), 1)


if __name__ == "__main__":
    unittest.main()
