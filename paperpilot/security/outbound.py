"""Fail-closed URL policy for configurable outbound services."""

from __future__ import annotations

import ipaddress
import socket
import time
import uuid
from dataclasses import dataclass
from typing import Iterable, Mapping
from urllib.parse import SplitResult, urlsplit, urlunsplit
from paperpilot.database.connection import get_db
from paperpilot.security.identity import current_identity


class OutboundPolicyError(ValueError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


_PROXY_FAKE_IP_BENCHMARK = ipaddress.ip_network("198.18.0.0/15")


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


def parse_proxy_fake_ip_networks(
    value: str | None,
) -> frozenset[ipaddress.IPv4Network]:
    """Parse explicitly enabled RFC 2544 fake-IP ranges used by DNS proxies."""
    networks: set[ipaddress.IPv4Network] = set()
    for item in (value or "").split(","):
        if not item.strip():
            continue
        try:
            network = ipaddress.ip_network(item.strip(), strict=True)
        except ValueError as exc:
            raise OutboundPolicyError("invalid_proxy_fake_ip_range") from exc
        if not isinstance(network, ipaddress.IPv4Network) or not network.subnet_of(
            _PROXY_FAKE_IP_BENCHMARK
        ):
            raise OutboundPolicyError("invalid_proxy_fake_ip_range")
        networks.add(network)
    return frozenset(networks)


class OutboundPolicy:
    def __init__(
        self,
        *,
        public_origins: Iterable[str],
        private_origins: Iterable[str],
        transfer_origins: Iterable[str],
        proxy_fake_ip_networks: Iterable[str | ipaddress.IPv4Network] = (),
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
        self.proxy_fake_ip_networks = parse_proxy_fake_ip_networks(
            ",".join(str(network) for network in proxy_fake_ip_networks)
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
            proxy_fake_ip_networks=parse_proxy_fake_ip_networks(
                environ.get("PAPERPILOT_AI_PROXY_FAKE_IP_RANGES")
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
        if purpose == "ai" and parts.query:
            raise OutboundPolicyError("outbound_query_forbidden")
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

        try:
            hostname_is_ip_literal = ipaddress.ip_address(parts.hostname) is not None
        except ValueError:
            hostname_is_ip_literal = False

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
            elif not address.is_global and not (
                purpose == "ai"
                and parts.scheme == "https"
                and not hostname_is_ip_literal
                and any(address in network for network in self.proxy_fake_ip_networks)
            ):
                raise OutboundPolicyError("private_address_forbidden")

        clean_url = urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ""))
        return ValidatedTarget(clean_url, origin, addresses)

    @staticmethod
    def reject_redirect(status_code: int) -> None:
        if 300 <= status_code < 400:
            raise OutboundPolicyError("outbound_redirect_blocked")


class DynamicOutboundPolicy(OutboundPolicy):
    """Combine immutable deployment origins with administrator-managed public origins."""

    @staticmethod
    def _require_administrator():
        identity = current_identity()
        if identity.role != "admin":
            raise OutboundPolicyError("administrator_required")
        return identity

    def _enabled_provider_origins(self) -> frozenset[str]:
        rows = get_db().execute(
            "SELECT origin FROM ai_providers WHERE enabled=1 ORDER BY origin"
        ).fetchall()
        return frozenset(str(row["origin"]) for row in rows)

    def seed_deployment_origins(self, administrator_id: str) -> None:
        now = int(time.time())
        database = get_db()
        for origin in self.public_origins:
            host = urlsplit(origin).hostname or "AI Provider"
            database.execute(
                """INSERT OR IGNORE INTO ai_providers
                   (id,name,origin,enabled,created_by,created_at,updated_at)
                   VALUES (?,?,?,1,?,?,?)""",
                (str(uuid.uuid4()), host, origin, administrator_id, now, now),
            )
        database.commit()

    def validate(self, url: str, *, purpose: str = "ai") -> ValidatedTarget:
        if purpose != "ai":
            return super().validate(url, purpose=purpose)
        effective = OutboundPolicy(
            public_origins=self.public_origins | self._enabled_provider_origins(),
            private_origins=self.private_origins,
            transfer_origins=self.transfer_origins,
            proxy_fake_ip_networks=self.proxy_fake_ip_networks,
        )
        return effective.validate(url, purpose=purpose)

    def approve_public_url(self, url: str, *, name: str | None = None) -> dict:
        identity = self._require_administrator()
        parts = urlsplit(url.strip()) if isinstance(url, str) else None
        if parts is None:
            raise OutboundPolicyError("invalid_outbound_url")
        origin = _format_origin(parts)
        # Validate DNS/address safety before persisting the origin.
        OutboundPolicy(
            public_origins={origin},
            private_origins=(),
            transfer_origins=(),
            proxy_fake_ip_networks=self.proxy_fake_ip_networks,
        ).validate(url, purpose="ai")
        now = int(time.time())
        database = get_db()
        existing = database.execute(
            "SELECT id FROM ai_providers WHERE origin=?", (origin,)
        ).fetchone()
        provider_id = existing["id"] if existing else str(uuid.uuid4())
        provider_name = (name or parts.hostname or "AI Provider").strip()[:80]
        database.execute(
            """INSERT INTO ai_providers(id,name,origin,enabled,created_by,created_at,updated_at)
               VALUES (?,?,?,1,?,?,?)
               ON CONFLICT(origin) DO UPDATE SET enabled=1,name=excluded.name,updated_at=excluded.updated_at""",
            (provider_id, provider_name, origin, identity.user_id, now, now),
        )
        database.commit()
        return {"id": provider_id, "name": provider_name, "origin": origin, "enabled": True}

    def list_providers(self) -> list[dict]:
        self._require_administrator()
        rows = get_db().execute(
            "SELECT id,name,origin,enabled,created_at,updated_at FROM ai_providers ORDER BY name,origin"
        ).fetchall()
        return [{**dict(row), "enabled": bool(row["enabled"])} for row in rows]

    def update_provider(self, provider_id: str, *, name=None, enabled=None) -> dict:
        self._require_administrator()
        database = get_db()
        row = database.execute("SELECT * FROM ai_providers WHERE id=?", (provider_id,)).fetchone()
        if row is None:
            raise OutboundPolicyError("provider_not_found")
        if name is not None and (not isinstance(name, str) or not name.strip()):
            raise OutboundPolicyError("invalid_provider_name")
        if enabled is not None and not isinstance(enabled, bool):
            raise OutboundPolicyError("invalid_provider_status")
        database.execute(
            "UPDATE ai_providers SET name=?,enabled=?,updated_at=? WHERE id=?",
            (name.strip()[:80] if name is not None else row["name"], int(enabled) if enabled is not None else row["enabled"], int(time.time()), provider_id),
        )
        database.commit()
        return next(item for item in self.list_providers() if item["id"] == provider_id)

    def delete_provider(self, provider_id: str) -> None:
        self._require_administrator()
        database = get_db()
        database.execute("DELETE FROM ai_providers WHERE id=?", (provider_id,))
        database.commit()


def guarded_request(
    policy: OutboundPolicy,
    method: str,
    url: str,
    *,
    purpose: str = "ai",
    **kwargs,
):
    """Validate a destination and make one non-redirecting requests call."""
    import requests

    target = policy.validate(url, purpose=purpose)
    kwargs["allow_redirects"] = False
    response = requests.request(method, target.url, **kwargs)
    policy.reject_redirect(response.status_code)
    return response
