import hashlib
import io
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from paperpilot.document_worker.safety import DocumentLimits, bounded_copy
from paperpilot.tools.basic_tools.mineru_api_client import MinerUAPIClient


class _Raw(io.BytesIO):
    decode_content = False


class _Response:
    status_code = 200

    def __init__(self):
        self.raw = _Raw(b"bounded zip bytes")


class _DocumentClient:
    def __init__(self, root):
        self.root = Path(root)
        self.limits = DocumentLimits(max_archive_bytes=1024)

    def stage(self, job_id, kind, stream):
        self.job_id = job_id
        self.kind = kind
        work = self.root / job_id / "work"
        work.mkdir(parents=True)
        bounded_copy(stream, work / "input.zip", 1024)
        output = work / "output"
        output.mkdir()
        self.payload = b"# validated"
        (output / "full.md").write_bytes(self.payload)
        (output / "unlisted.bin").write_bytes(b"must not be promoted")

    def create(self, job_id, kind):
        return {"job_id": job_id, "kind": kind, "status": "queued"}

    def wait(self, _job_id, timeout):
        return {"status": "completed", "progress": 100, "error": None}

    def verified_manifest(self, _job_id, kind):
        return {"kind": kind, "entries": [{
            "path": "full.md", "size": len(self.payload),
            "sha256": hashlib.sha256(self.payload).hexdigest(),
        }]}

    def output(self, job_id):
        return self.root / job_id / "work" / "output"

    def cleanup(self, _job_id):
        return None


class MinerUDocumentWorkerTests(unittest.TestCase):
    def test_only_worker_manifest_entries_are_promoted(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "analysis"
            document_client = _DocumentClient(root / "jobs")
            client = MinerUAPIClient(
                "secret", outbound_policy=object(), document_client=document_client
            )
            with patch(
                "paperpilot.tools.basic_tools.mineru_api_client.guarded_request",
                return_value=_Response(),
            ), patch(
                "paperpilot.tools.basic_tools.mineru_api_client.DocumentJobDAO.create"
            ), patch(
                "paperpilot.tools.basic_tools.mineru_api_client.DocumentJobDAO.update"
            ):
                result = client.download_and_extract_result("https://example.test/result", str(output))
            self.assertEqual(result, str(output))
            self.assertEqual((output / "full.md").read_bytes(), b"# validated")
            self.assertFalse((output / "unlisted.bin").exists())
            self.assertEqual(document_client.kind, "mineru_zip")
            uuid.UUID(document_client.job_id)


if __name__ == "__main__":
    unittest.main()
