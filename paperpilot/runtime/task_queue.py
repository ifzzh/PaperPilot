from __future__ import annotations

import threading
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Callable, TypeVar


T = TypeVar("T")


class QueueFull(RuntimeError):
    """Raised when an executor has no running or queued capacity left."""


class ExecutorShuttingDown(RuntimeError):
    """Raised after an executor stops accepting new work."""


class BoundedExecutor:
    """ThreadPoolExecutor with an explicit bound on submitted work."""

    def __init__(self, *, max_workers: int, max_queue: int, thread_name_prefix: str):
        if max_workers < 1 or max_queue < 0:
            raise ValueError("max_workers must be positive and max_queue non-negative")
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix=thread_name_prefix,
        )
        self._capacity = threading.BoundedSemaphore(max_workers + max_queue)
        self._state_lock = threading.Lock()
        self._accepting = True

    def submit(self, function: Callable[..., T], /, *args, **kwargs) -> Future[T]:
        with self._state_lock:
            if not self._accepting:
                raise ExecutorShuttingDown("executor is shutting down")
            if not self._capacity.acquire(blocking=False):
                raise QueueFull("executor queue is full")
            try:
                future = self._executor.submit(function, *args, **kwargs)
            except BaseException:
                self._capacity.release()
                raise
        future.add_done_callback(lambda _future: self._capacity.release())
        return future

    def shutdown(self, *, wait: bool = True, cancel_futures: bool = True) -> None:
        with self._state_lock:
            if not self._accepting:
                return
            self._accepting = False
        self._executor.shutdown(wait=wait, cancel_futures=cancel_futures)
