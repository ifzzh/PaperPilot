"""Fail-closed URL policy for configurable outbound services."""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from typing import Iterable, Mapping
from urllib.parse import SplitResult, urlsplit, urlunsplit


class OutboundPolicyError(ValueError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class ValidatedTarget:
    url: str
    origin: str
    addresses: tuple[str, ...]


def _contains_control(value: str) -> bool:
    return any(ord(character) < 32 or ord(character) == 127 for character in value)


def _format_origin(parts: SplitResult) -> str:
    hostname = parts.hostname
    if not hostname:
        raise OutboundPolicyError("invalid_outbound_url")
    try:
        hostname = hostname.encode("idna").decode("ascii").lower()
        port = parts.port
    except (UnicodeError, ValueError) as exc:
        raise OutboundPolicyError("invalid_outbound_url") from exc
    default_port = 443 if parts.scheme == "https" else 80
    effective_port = port or default_port
    host_display = f"[{hostname}]" if ":" in hostname else hostname
    return f"{parts.scheme}://{host_display}" + (
        f":{effective_port}" if effective_port != default_port else ""
    )


def normalize_origin(value: str, *, private: bool = False) -> str:
    if not isinstance(value, str) or not value or _contains_control(value):
        raise OutboundPolicyError("invalid_outbound_origin")
    parts = urlsplit(value.strip())
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise OutboundPolicyError("invalid_outbound_origin")
    if not private and parts.scheme != "https":
        raise OutboundPolicyError("public_origin_requires_https")
    if parts.username is not None or parts.password is not None:
        raise OutboundPolicyError("outbound_credentials_forbidden")
    if parts.path not in {"", "/"} or parts.query or parts.fragment:
        raise OutboundPolicyError("origin_must_not_contain_path")
    return _format_origin(parts)


def parse_origin_list(value: str | None, *, private: bool = False) -> frozenset[str]:
    origins = set()
    for item in (value or "").split(","):
        if item.strip():
            origins.add(normalize_origin(item, private=private))
    return frozenset(origins)


class OutboundPolicy:
    def __init__(
        self,
        *,
        public_origins: Iterable[str],
        private_origins: Iterable[str],
        transfer_origins: Iterable[str],
    ):
        self.public_origins = frozenset(
            normalize_origin(origin) for origin in public_origins
        )
        self.private_origins = frozenset(
            normalize_origin(origin, private=True) for origin in private_origins
        )
        self.transfer_origins = frozenset(
            normalize_origin(origin) for origin in transfer_origins
        )

    @classmethod
    def from_environ(cls, environ: Mapping[str, str]) -> "OutboundPolicy":
        return cls(
            public_origins=parse_origin_list(environ.get("PAPERPILOT_AI_ALLOWED_ORIGINS")),
            private_origins=parse_origin_list(
                environ.get("PAPERPILOT_AI_PRIVATE_ALLOWED_ORIGINS"), private=True
            ),
            transfer_origins=parse_origin_list(
                environ.get("PAPERPILOT_MINERU_TRANSFER_ALLOWED_ORIGINS")
            ),
        )

    def validate(self, url: str, *, purpose: str = "ai") -> ValidatedTarget:
        if not isinstance(url, str) or not url or _contains_control(url):
            raise OutboundPolicyError("invalid_outbound_url")
        parts = urlsplit(url.strip())
        if parts.scheme not in {"http", "https"} or not parts.netloc:
            raise OutboundPolicyError("invalid_outbound_url")
        if parts.username is not None or parts.password is not None:
            raise OutboundPolicyError("outbound_credentials_forbidden")
        if parts.fragment:
            raise OutboundPolicyError("outbound_fragment_forbidden")
        origin = _format_origin(parts)
        private_allowed = purpose == "ai" and origin in self.private_origins
        allowed = self.transfer_origins if purpose == "transfer" else self.public_origins | self.private_origins
        if origin not in allowed:
            raise OutboundPolicyError("origin_not_allowed")
        if not private_allowed and parts.scheme != "https":
            raise OutboundPolicyError("public_origin_requires_https")

        try:
            records = socket.getaddrinfo(parts.hostname, parts.port, type=socket.SOCK_STREAM)
            addresses = tuple(sorted({record[4][0] for record in records}))
        except (OSError, UnicodeError, ValueError) as exc:
            raise OutboundPolicyError("outbound_dns_failed") from exc
        if not addresses:
            raise OutboundPolicyError("outbound_dns_failed")

        for address_text in addresses:
            try:
                address = ipaddress.ip_address(address_text)
            except ValueError as exc:
                raise OutboundPolicyError("invalid_resolved_address") from exc
            if (
                address.is_loopback
                or address.is_link_local
                or address.is_multicast
                or address.is_unspecified
                or address.is_reserved
            ):
                raise OutboundPolicyError("dangerous_address_forbidden")
            if private_allowed:
                if not address.is_private:
                    raise OutboundPolicyError("private_origin_resolved_public")
            elif not address.is_global:
                raise OutboundPolicyError("private_address_forbidden")

        clean_url = urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ""))
        return ValidatedTarget(clean_url, origin, addresses)

    @staticmethod
    def reject_redirect(status_code: int) -> None:
        if 300 <= status_code < 400:
            raise OutboundPolicyError("outbound_redirect_blocked")
