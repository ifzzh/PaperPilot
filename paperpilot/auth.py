"""Authentication configuration and request protection for PaperPilot."""

from __future__ import annotations

import os
import math
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Mapping
from urllib.parse import urlparse


class AuthConfigurationError(ValueError):
    """Raised when PaperPilot cannot start with a safe auth configuration."""


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
    supabase_url: str
    supabase_anon_key: str
    allowed_emails: frozenset[str]
    cookie_secure: bool

    @property
    def enabled(self) -> bool:
        return self.mode == "supabase"

    @classmethod
    def from_environ(cls, environ: Mapping[str, str] | None = None) -> "AuthConfig":
        values = os.environ if environ is None else environ
        environment = values.get("PAPERPILOT_ENV", "production").strip().lower()
        mode = values.get("PAPERPILOT_AUTH_MODE", "supabase").strip().lower()

        if environment not in {"production", "development"}:
            raise AuthConfigurationError(
                "PAPERPILOT_ENV must be production or development"
            )
        if mode not in {"supabase", "disabled"}:
            raise AuthConfigurationError(
                "PAPERPILOT_AUTH_MODE must be supabase or disabled"
            )
        if environment == "production" and mode == "disabled":
            raise AuthConfigurationError(
                "authentication cannot be disabled in production"
            )

        supabase_url = values.get("SUPABASE_URL", "").strip().rstrip("/")
        supabase_anon_key = values.get("SUPABASE_ANON_KEY", "").strip()
        allowed_emails = frozenset(
            email.strip().lower()
            for email in values.get("PAPERPILOT_ALLOWED_EMAILS", "").split(",")
            if email.strip()
        )

        if mode == "supabase":
            missing = []
            if not supabase_url:
                missing.append("SUPABASE_URL")
            if not supabase_anon_key:
                missing.append("SUPABASE_ANON_KEY")
            if not allowed_emails:
                missing.append("PAPERPILOT_ALLOWED_EMAILS")
            if missing:
                raise AuthConfigurationError(
                    "missing required authentication configuration: "
                    + ", ".join(missing)
                )

            parsed_url = urlparse(supabase_url)
            if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
                raise AuthConfigurationError("SUPABASE_URL must be an http(s) URL")
            invalid_emails = [email for email in allowed_emails if "@" not in email]
            if invalid_emails:
                raise AuthConfigurationError(
                    "PAPERPILOT_ALLOWED_EMAILS contains an invalid email address"
                )

        cookie_value = values.get("PAPERPILOT_COOKIE_SECURE")
        cookie_secure = (
            environment == "production"
            if cookie_value is None or not cookie_value.strip()
            else _parse_bool(cookie_value, name="PAPERPILOT_COOKIE_SECURE")
        )

        return cls(
            environment=environment,
            mode=mode,
            supabase_url=supabase_url,
            supabase_anon_key=supabase_anon_key,
            allowed_emails=allowed_emails,
            cookie_secure=cookie_secure,
        )


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    retry_after: int = 0


class FixedWindowRateLimiter:
    """Small thread-safe limiter for PaperPilot's single-process deployment."""

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
