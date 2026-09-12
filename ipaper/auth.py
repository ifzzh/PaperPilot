"""Authentication configuration and request protection for iPaper."""

from __future__ import annotations

from ipaper.environment import getenv as brand_getenv

import os
import math
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Mapping


class AuthConfigurationError(ValueError):
    """Raised when iPaper cannot start with a safe auth configuration."""


def _parse_bool(value: str, *, name: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise AuthConfigurationError(f"{name} must be true or false")


@dataclass(frozen=True)
class AuthConfig:
    environment: str
    mode: str
    cookie_secure: bool

    @property
    def enabled(self) -> bool:
        return self.mode == "local"

    @classmethod
    def from_environ(cls, environ: Mapping[str, str] | None = None) -> "AuthConfig":
        values = os.environ if environ is None else environ
        environment = brand_getenv("IPAPER_ENV", "production", environ=values).strip().lower()
        mode = brand_getenv("IPAPER_AUTH_MODE", "local", environ=values).strip().lower()

        if environment not in {"production", "development"}:
            raise AuthConfigurationError(
                "IPAPER_ENV must be production or development"
            )
        if mode not in {"local", "disabled"}:
            raise AuthConfigurationError(
                "IPAPER_AUTH_MODE must be local or disabled"
            )
        if environment == "production" and mode == "disabled":
            raise AuthConfigurationError(
                "authentication cannot be disabled in production"
            )

        cookie_value = brand_getenv("IPAPER_COOKIE_SECURE", environ=values)
        cookie_secure = (
            environment == "production"
            if cookie_value is None or not cookie_value.strip()
            else _parse_bool(cookie_value, name="IPAPER_COOKIE_SECURE")
        )

        return cls(
            environment=environment,
            mode=mode,
            cookie_secure=cookie_secure,
        )


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    retry_after: int = 0


class FixedWindowRateLimiter:
    """Small thread-safe limiter for iPaper's single-process deployment."""

    def __init__(self):
        self._events: dict[tuple[str, str], deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(
        self,
        bucket: str,
        identity: str,
        *,
        limit: int,
        window_seconds: int,
        now: float | None = None,
    ) -> RateLimitResult:
        current = time.monotonic() if now is None else now
        cutoff = current - window_seconds
        key = (bucket, identity)
        with self._lock:
            events = self._events[key]
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= limit:
                retry_after = max(1, math.ceil(events[0] + window_seconds - current))
                return RateLimitResult(False, retry_after)
            events.append(current)
        return RateLimitResult(True)

    def clear(self) -> None:
        with self._lock:
            self._events.clear()
