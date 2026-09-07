import unittest
from unittest.mock import Mock, patch

from flask import Flask

from paperpilot.routes.basic_routes.settings_route import register_settings_routes


class FakeCredentialStore:
    def __init__(self):
        self.values = {"translate": "existing-secret"}

    def configured(self, name):
        return bool(self.values.get(name))

    def get(self, name):
        return self.values.get(name, "")

    def set(self, name, value):
        self.values[name] = value

    def clear(self, name):
        self.values.pop(name, None)


class AgenticSettingsSecurityTests(unittest.TestCase):
    def setUp(self):
        self.settings = {
            "llmConfigs": {
                "translate": {"llmModel": "model", "llmBaseUrl": "https://api.example.test/v1"},
                "interpret": {"llmModel": "", "llmBaseUrl": ""},
                "dailyArxiv": {"llmModel": "", "llmBaseUrl": ""},
            },
            "mineruServerUrl": "",
            "mineruUseApi": False,
        }
        self.store = FakeCredentialStore()
        self.policy = Mock()
        app = Flask(__name__)
        app.config["TESTING"] = True
        self.dao_get = patch(
            "paperpilot.routes.basic_routes.settings_route.SettingsDAO.get_setting",
            side_effect=lambda _key, _default=None: self.settings,
        )
        self.dao_save = patch(
            "paperpilot.routes.basic_routes.settings_route.SettingsDAO.save_setting",
            side_effect=self._save,
        )
        self.dao_get.start()
        self.dao_save.start()
        register_settings_routes(
            app,
            user_settings_file="unused",
            default_user_settings={},
            reading_history_file="unused",
            agentic_settings_file="unused",
            default_agentic_settings=self.settings,
            avatars_dir="unused",
            credential_store=self.store,
            outbound_policy=self.policy,
        )
        self.client = app.test_client()

    def tearDown(self):
        self.dao_get.stop()
        self.dao_save.stop()

    def _save(self, key, value):
        if key == "agentic_settings":
            self.settings = value

    def test_get_returns_only_configured_flag(self):
        response = self.client.get("/api/settings/agentic")
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertTrue(body["llmConfigs"]["translate"]["llmApiKeyConfigured"])
        self.assertNotIn("llmApiKey", body["llmConfigs"]["translate"])
        self.assertNotIn("existing-secret", response.get_data(as_text=True))

    def test_empty_secret_preserves_and_new_secret_replaces(self):
        response = self.client.post(
            "/api/settings/agentic",
            json={
                "llmConfigs": {
                    "translate": {
                        "llmModel": "new-model",
                        "llmBaseUrl": "https://api.example.test/v1",
                        "llmApiKey": "",
                    }
                }
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.store.get("translate"), "existing-secret")
        self.assertEqual(self.settings["llmConfigs"]["translate"]["llmModel"], "new-model")

        response = self.client.post(
            "/api/settings/agentic",
            json={"llmConfigs": {"translate": {"llmApiKey": "replacement"}}},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.store.get("translate"), "replacement")

    def test_configured_input_and_unknown_fields_are_rejected(self):
        response = self.client.post(
            "/api/settings/agentic",
            json={"llmConfigs": {"translate": {"llmApiKeyConfigured": False}}},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"], "unknown_llm_fields")
        self.assertEqual(self.store.get("translate"), "existing-secret")

    def test_clear_is_explicit_and_idempotent(self):
        first = self.client.delete("/api/settings/agentic/secrets/translate")
        second = self.client.delete("/api/settings/agentic/secrets/translate")
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertFalse(self.store.configured("translate"))

    def test_connection_tests_reject_non_string_credentials(self):
        llm = self.client.post("/api/settings/test/llm", json={"llmApiKey": 123})
        mineru = self.client.post("/api/settings/test/mineru-api", json={"apiToken": {}})
        self.assertEqual(llm.status_code, 400)
        self.assertEqual(llm.get_json()["error"], "invalid_llm_test_payload")
        self.assertEqual(mineru.status_code, 400)
        self.assertEqual(mineru.get_json()["error"], "invalid_api_key")


if __name__ == "__main__":
    unittest.main()
