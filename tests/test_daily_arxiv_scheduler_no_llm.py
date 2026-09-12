import json
import os
import tempfile
import threading
import unittest
from unittest.mock import patch


from ipaper.tools.basic_tools.daily_arxiv import DailyArxivManager
from ipaper.security.identity import (
    Identity,
    current_user_id,
    reset_background_identity,
    set_background_identity,
)


class TestDailyArxivSchedulerNoLLM(unittest.TestCase):
    def test_scheduler_thread_inherits_its_owner_identity(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = DailyArxivManager(
                base_dir=tmpdir,
                settings_file=os.path.join(tmpdir, "settings.json"),
            )
            observed = []
            finished = threading.Event()

            def scheduler_loop():
                observed.append(current_user_id())
                finished.set()

            manager._scheduler_loop = scheduler_loop
            identity = Identity("owner-id", "owner", "user")
            token = set_background_identity(identity)
            try:
                manager.start_scheduler()
                self.assertTrue(finished.wait(2))
                self.assertEqual(manager._scheduler_owner_id, identity.user_id)
            finally:
                manager.stop_scheduler()
                reset_background_identity(token)
            self.assertEqual(observed, [identity.user_id])

    def test_scheduler_dispatches_through_configured_executor(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = DailyArxivManager(
                base_dir=tmpdir,
                settings_file=os.path.join(tmpdir, "settings.json"),
            )
            submitted = []
            manager.set_scheduler_dispatch_callback(
                lambda function, *args, **kwargs: submitted.append(
                    (function, args, kwargs)
                )
            )
            manager._dispatch_scheduled_fetch()
            self.assertEqual(len(submitted), 1)
            self.assertEqual(submitted[0][0], manager._do_scheduled_fetch)

    def test_scheduled_fetch_runs_without_llm(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            settings_file = os.path.join(tmpdir, "daily_arxiv_settings.json")
            with open(settings_file, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "enabled": True,
                        "categories": ["cs.CV"],
                        "retentionDays": 1,
                        "checkIntervalMinutes": 30,
                    },
                    f,
                )

            manager = DailyArxivManager(base_dir=tmpdir, settings_file=settings_file)
            manager.set_llm_config_callback(lambda: {})

            called = []
            manager.get_available_dates = lambda: []
            manager.cleanup_old_papers = lambda retention_days=7: None

            def fake_fetch_papers(category, date_str=None, force=False, **_kwargs):
                called.append((category, date_str, force))
                return []

            manager.fetch_papers = fake_fetch_papers

            with patch("ipaper.tools.basic_tools.daily_arxiv.time.sleep", lambda _: None):
                manager._do_scheduled_fetch()

            self.assertTrue(called)


if __name__ == "__main__":
    unittest.main()
