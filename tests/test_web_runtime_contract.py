import threading
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch


class WebTaskQueueContractTests(unittest.TestCase):
    def test_executor_rejects_work_beyond_running_and_queued_capacity(self):
        from paperpilot.runtime.task_queue import BoundedExecutor, QueueFull

        release = threading.Event()
        started = threading.Event()

        def blocked():
            started.set()
            release.wait(2)

        executor = BoundedExecutor(max_workers=1, max_queue=1, thread_name_prefix="test")
        first = executor.submit(blocked)
        self.assertTrue(started.wait(1))
        second = executor.submit(lambda: "queued")

        with self.assertRaises(QueueFull):
            executor.submit(lambda: "overflow")

        release.set()
        first.result(timeout=2)
        self.assertEqual(second.result(timeout=2), "queued")
        executor.shutdown(wait=True, cancel_futures=True)

    def test_shutdown_rejects_new_work_and_cancels_queued_work(self):
        from paperpilot.runtime.task_queue import BoundedExecutor, ExecutorShuttingDown

        release = threading.Event()
        executor = BoundedExecutor(max_workers=1, max_queue=1, thread_name_prefix="test")
        running = executor.submit(lambda: release.wait(2))
        queued = executor.submit(lambda: "must-not-run")

        executor.shutdown(wait=False, cancel_futures=True)
        with self.assertRaises(ExecutorShuttingDown):
            executor.submit(lambda: None)

        release.set()
        running.result(timeout=2)
        for _ in range(100):
            if queued.cancelled():
                break
            time.sleep(0.01)
        self.assertTrue(queued.cancelled())


class ApplicationFactoryContractTests(unittest.TestCase):
    def test_factory_initializes_once_for_one_paper_root(self):
        import app as app_module

        original = (
            app_module._application_initialized,
            app_module._application_papers_dir,
            app_module._shutdown_registered,
        )
        with tempfile.TemporaryDirectory() as temporary:
            paper_root = str(Path(temporary) / "papers")
            try:
                app_module._application_initialized = False
                app_module._application_papers_dir = None
                with patch.object(app_module, "_initialize_application") as initialize:
                    first = app_module.create_app(paper_root)
                    second = app_module.create_app(paper_root)
                    self.assertIs(first, second)
                    initialize.assert_called_once_with(str(Path(paper_root).resolve()))
                    with self.assertRaisesRegex(RuntimeError, "another paper root"):
                        app_module.create_app(str(Path(temporary) / "other"))
            finally:
                (
                    app_module._application_initialized,
                    app_module._application_papers_dir,
                    app_module._shutdown_registered,
                ) = original

    def test_database_initialization_failure_is_not_ignored(self):
        import app as app_module

        with tempfile.TemporaryDirectory() as temporary, patch.object(
            app_module, "init_db_schema", side_effect=OSError("read only")
        ):
            with self.assertRaisesRegex(OSError, "read only"):
                app_module.init_app(str(Path(temporary) / "papers"))


if __name__ == "__main__":
    unittest.main()
