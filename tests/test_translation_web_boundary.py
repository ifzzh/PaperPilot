from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from flask import Flask

from paperpilot.core.base_paper import Paper
from paperpilot.core.paper_store import paper_store
from paperpilot.database.dao.translation_job_dao import TranslationJobDAO
from paperpilot.routes.agent_routes.agent_translate_route import register_agent_translate_routes
from paperpilot.security.paths import category_directory, paper_asset_paths


class TranslationWebBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.papers = Path(self.temp.name) / "papers"
        self.papers.mkdir()
        paper_store.reset()
        self.worker = Mock()
        self.worker.run_cleanup_loop.return_value = None
        self.credentials = Mock()
        self.credentials.get.return_value = "server-secret"
        self.outbound = Mock()
        app = Flask(__name__)
        with (
            patch(
                "paperpilot.routes.agent_routes.agent_translate_route.TranslationWorkerClient",
                return_value=self.worker,
            ),
            patch.object(TranslationJobDAO, "list_active", return_value=[]),
        ):
            register_agent_translate_routes(
                app,
                translation_tasks={},
                translation_tasks_lock=threading.Lock(),
                get_categories=lambda: {"children": []},
                get_category_path=lambda *_args: None,
                get_papers_in_category=lambda *_args: [],
                save_paper_metadata=Mock(),
                agentic_settings_file="unused",
                upload_folder=str(self.papers),
                credential_store=self.credentials,
                outbound_policy=self.outbound,
            )
        self.client = app.test_client()

    def tearDown(self):
        paper_store.reset()
        self.temp.cleanup()

    def test_client_credential_overrides_are_rejected(self):
        self.worker.health.return_value = False
        response = self.client.post(
            "/api/paper/translate",
            json={
                "paper_id": "paper-1",
                "openai_model": "fake",
                "openai_base_url": "http://fake.invalid/v1",
                "openai_api_key": "secret",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"], "forbidden_agent_overrides")
        self.worker.health.assert_not_called()

    def test_worker_unavailable_returns_503_without_local_fallback(self):
        self.worker.health.return_value = False
        settings = {"llmConfigs": {"translate": {
            "llmModel": "fake", "llmBaseUrl": "https://api.example.test/v1"
        }}}
        with (
            patch.object(TranslationJobDAO, "has_active_for_paper", return_value=False),
            patch(
                "paperpilot.routes.agent_routes.agent_translate_route.SettingsDAO.get_setting",
                return_value=settings,
            ),
        ):
            response = self.client.post("/api/paper/translate", json={"paper_id": "paper-1"})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json()["error"], "translation_worker_unavailable")
        self.worker.stage_input.assert_not_called()

    def test_existing_translation_downloads_while_worker_is_offline(self):
        directory = category_directory(self.papers, "category-a", create=True)
        pdf = directory / "paper.pdf"
        pdf.write_bytes(b"%PDF-source")
        assets = paper_asset_paths(self.papers, pdf)
        assets.chinese_dual.write_bytes(b"%PDF-translated")
        paper_store.upsert(
            Paper(id="paper-1", filename="paper.pdf", file_path=str(pdf)),
            category_id="category-a",
            category_path=["Category A"],
        )
        self.worker.health.return_value = False

        response = self.client.get("/api/paper/paper-1/chinese/file")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, b"%PDF-translated")
        self.worker.get.assert_not_called()


if __name__ == "__main__":
    unittest.main()
