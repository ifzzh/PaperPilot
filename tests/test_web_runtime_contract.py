import threading
import time
import unittest


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


if __name__ == "__main__":
    unittest.main()
