import threading
import unittest
from unittest.mock import Mock

from flask import Flask

from paperpilot.routes.agent_routes.agent_chat_route import register_agent_chat_routes
from paperpilot.routes.agent_routes.agent_summary_route import register_agent_summary_routes


class AgentServerCredentialTests(unittest.TestCase):
    def test_analysis_rejects_client_connection_overrides(self):
        app = Flask(__name__)
        register_agent_summary_routes(
            app,
            analysis_tasks={},
            analysis_tasks_lock=threading.Lock(),
            get_categories=lambda: {"children": []},
            get_category_path=lambda *_: None,
            get_papers_in_category=lambda *_: [],
            save_paper_metadata=Mock(),
            agentic_settings_file="unused",
            upload_folder="unused",
            credential_store=Mock(),
            outbound_policy=Mock(),
        )
        response = app.test_client().post(
            "/api/paper/analyze",
            json={"paper_id": "paper", "openai_api_key": "browser-secret"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"], "forbidden_agent_overrides")
        self.assertNotIn("browser-secret", response.get_data(as_text=True))

    def test_chat_rejects_client_connection_overrides(self):
        app = Flask(__name__)
        register_agent_chat_routes(
            app,
            get_categories=lambda: {"children": []},
            get_category_path=lambda *_: None,
            get_papers_in_category=lambda *_: [],
            agentic_settings_file="unused",
            credential_store=Mock(),
            outbound_policy=Mock(),
        )
        response = app.test_client().post(
            "/api/paper/chat",
            json={
                "paper_id": "paper",
                "messages": [{"role": "user", "content": "hello"}],
                "openai_base_url": "http://127.0.0.1",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"], "forbidden_agent_overrides")


if __name__ == "__main__":
    unittest.main()
