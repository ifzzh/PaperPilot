"""Request and background-task identity propagation."""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from typing import Callable, TypeVar

from flask import g, has_request_context


DEVELOPMENT_USER_ID = "00000000-0000-0000-0000-000000000001"


@dataclass(frozen=True)
class Identity:
    user_id: str
    username: str
    role: str
    must_change_password: bool = False


_background_identity: ContextVar[Identity | None] = ContextVar(
    "paperpilot_identity", default=None
)
T = TypeVar("T")


def current_identity(*, required: bool = True) -> Identity | None:
    if has_request_context():
        identity = getattr(g, "identity", None)
        if identity is not None:
            return identity
    identity = _background_identity.get()
    if identity is None and required:
        raise RuntimeError("authenticated_identity_required")
    return identity


def current_user_id(*, required: bool = True) -> str | None:
    identity = current_identity(required=required)
    return identity.user_id if identity else None


def set_background_identity(identity: Identity):
    return _background_identity.set(identity)


def reset_background_identity(token) -> None:
    _background_identity.reset(token)


def run_as_identity(identity: Identity, callback: Callable[..., T], *args, **kwargs) -> T:
    """Run background work as one user without copying Flask request state."""
    token = set_background_identity(identity)
    try:
        return callback(*args, **kwargs)
    finally:
        reset_background_identity(token)
