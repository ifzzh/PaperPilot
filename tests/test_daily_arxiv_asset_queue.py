import sqlite3
import tempfile
import unittest
from pathlib import Path

from ipaper.database.db_manager import init_db_schema
from ipaper.tools.basic_tools.daily_arxiv_assets import AssetResult, DailyAssetCoordinator


class DailyAssetCoordinatorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "ipaper.db"
        init_db_schema(str(self.db))

    def tearDown(self):
        self.temp.cleanup()

    def add(self, owner, arxiv_id, status="queued", retry_count=0, error=None):
        with sqlite3.connect(self.db) as connection:
            connection.execute(
                """INSERT INTO daily_arxiv_candidates
                   (owner_id,arxiv_id,release_date,artifact_status,retry_count,
                    artifact_error_code,updated_at)
                   VALUES (?,?,? ,?,?,?,?)""",
                (owner, arxiv_id, "2026-09-09", status, retry_count, error,
                 "2026-09-09T00:00:00+00:00"),
            )

    def row(self, arxiv_id):
        with sqlite3.connect(self.db) as connection:
            connection.row_factory = sqlite3.Row
            return dict(connection.execute(
                "SELECT * FROM daily_arxiv_candidates WHERE arxiv_id=?", (arxiv_id,)
            ).fetchone())

    def test_fifty_candidates_are_processed_single_flight(self):
        owner = "00000000-0000-0000-0000-000000000001"
        active = 0
        maximum = 0

        def process(_owner, _arxiv, stage):
            nonlocal active, maximum
            active += 1
            maximum = max(maximum, active)
            stage("validating", "remote")
            active -= 1
            return AssetResult(True)

        for index in range(50):
            self.add(owner, f"2609.{index:05d}")
        coordinator = DailyAssetCoordinator(str(self.db), process, autostart=False)
        while coordinator.run_once():
            pass
        self.assertEqual(maximum, 1)
        with sqlite3.connect(self.db) as connection:
            self.assertEqual(connection.execute(
                "SELECT COUNT(*) FROM daily_arxiv_candidates WHERE artifact_status='ready'"
            ).fetchone()[0], 50)

    def test_infrastructure_failure_does_not_consume_attempt(self):
        owner = "00000000-0000-0000-0000-000000000001"
        self.add(owner, "2609.00001", retry_count=2)
        coordinator = DailyAssetCoordinator(
            str(self.db), lambda *_: AssetResult(False, "document_queue_full"), autostart=False
        )
        self.assertTrue(coordinator.run_once())
        row = self.row("2609.00001")
        self.assertEqual(row["artifact_status"], "retry_wait")
        self.assertEqual(row["retry_count"], 2)
        self.assertEqual(row["artifact_error_code"], "document_queue_full")

    def test_real_failures_stop_after_five_attempts(self):
        owner = "00000000-0000-0000-0000-000000000001"
        self.add(owner, "2609.00002", retry_count=4)
        coordinator = DailyAssetCoordinator(
            str(self.db), lambda *_: AssetResult(False, "pdf_invalid"), autostart=False
        )
        coordinator.run_once()
        row = self.row("2609.00002")
        self.assertEqual(row["artifact_status"], "failed")
        self.assertEqual(row["retry_count"], 5)
        self.assertIsNone(row["next_retry_at"])

    def test_restart_recovers_claimed_jobs_and_round_robins_users(self):
        first = "00000000-0000-0000-0000-000000000001"
        second = "00000000-0000-0000-0000-000000000002"
        self.add(first, "2609.00003", status="validating")
        self.add(first, "2609.00004")
        self.add(second, "2609.00005")
        order = []
        coordinator = DailyAssetCoordinator(
            str(self.db),
            lambda owner, arxiv, _stage: order.append((owner, arxiv)) or AssetResult(True),
            autostart=False,
        )
        coordinator.run_once()
        coordinator.run_once()
        self.assertNotEqual(order[0][0], order[1][0])
        self.assertEqual(self.row("2609.00003")["artifact_error_code"], "interrupted")


if __name__ == "__main__":
    unittest.main()
