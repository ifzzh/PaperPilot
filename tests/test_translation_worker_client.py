from __future__ import annotations

import stat
import tempfile
import unittest
import uuid
from pathlib import Path

from ipaper.security.paths import PathSecurityError
from ipaper.tools.agent_tools.translation_worker_client import TranslationWorkerClient


class TranslationWorkerClientStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.jobs = root / "jobs"
        self.papers = root / "papers"
        self.jobs.mkdir()
        self.papers.mkdir()
        self.client = TranslationWorkerClient(
            jobs_root=self.jobs,
            token_file=root / "unused-token",
            base_url="http://worker.invalid",
        )

    def tearDown(self):
        self.temp.cleanup()

    def test_stage_uses_fixed_filename_and_copies_bytes(self):
        source = self.papers / "source.pdf"
        source.write_bytes(b"%PDF-source")
        job_id = str(uuid.uuid4())

        staged = self.client.stage_input(job_id, source)

        self.assertEqual(staged, self.jobs / job_id / "work" / "input.pdf")
        self.assertEqual(staged.read_bytes(), b"%PDF-source")
        self.assertEqual(stat.S_IMODE(staged.parent.stat().st_mode), 0o2770)
        self.assertEqual(stat.S_IMODE(staged.stat().st_mode), 0o640)

    def test_stage_rejects_symlink_source(self):
        outside = Path(self.temp.name) / "outside.pdf"
        outside.write_bytes(b"sentinel")
        source = self.papers / "source.pdf"
        source.symlink_to(outside)

        with self.assertRaisesRegex(PathSecurityError, "unsafe_translation_source"):
            self.client.stage_input(str(uuid.uuid4()), source)
        self.assertEqual(outside.read_bytes(), b"sentinel")

    def test_promote_rejects_symlink_output_and_preserves_destination(self):
        job_id = str(uuid.uuid4())
        work = self.jobs / job_id / "work"
        work.mkdir(parents=True)
        (work / "input.pdf").write_bytes(b"%PDF-input")
        outside = Path(self.temp.name) / "outside.pdf"
        outside.write_bytes(b"sentinel")
        (work / "input.zh.dual.pdf").symlink_to(outside)
        destination = self.papers / "paper.zh.dual.pdf"
        destination.write_bytes(b"old")

        with self.assertRaisesRegex(PathSecurityError, "unsafe_worker_output"):
            self.client.promote_result(
                job_id,
                papers_root=self.papers,
                destination=destination,
                logs=[],
                log_destination=self.papers / "paper.translate.log",
            )

        self.assertEqual(destination.read_bytes(), b"old")
        self.assertEqual(outside.read_bytes(), b"sentinel")

    def test_promote_atomically_writes_exact_assets_then_cleanup(self):
        job_id = str(uuid.uuid4())
        work = self.jobs / job_id / "work"
        work.mkdir(parents=True)
        (work / "input.pdf").write_bytes(b"%PDF-input")
        (work / "input.zh.dual.pdf").write_bytes(b"%PDF-output")
        destination = self.papers / "paper.zh.dual.pdf"
        log = self.papers / "paper.translate.log"

        self.client.promote_result(
            job_id,
            papers_root=self.papers,
            destination=destination,
            logs=["safe log"],
            log_destination=log,
        )
        self.client.cleanup(job_id)

        self.assertEqual(destination.read_bytes(), b"%PDF-output")
        self.assertEqual(log.read_text(), "safe log")
        self.assertFalse((self.jobs / job_id).exists())


if __name__ == "__main__":
    unittest.main()
