"""Fail-closed checks that must finish before Gunicorn binds its listener."""

from __future__ import annotations

from ipaper.environment import getenv as brand_getenv

import os
from pathlib import Path

from dotenv import load_dotenv

from ipaper.auth import AuthConfig
from ipaper.local_auth import LocalAuthService
from ipaper.database.connection import DB_PATH, close_db
from ipaper.database.db_manager import init_db_schema
from ipaper.migrations.agentic_secrets import assert_no_plaintext_credentials
from ipaper.migrations.tenant_storage import assert_tenant_migrated
from ipaper.security.agentic_credentials import AgenticCredentialStore
from ipaper.security.outbound import DynamicOutboundPolicy


def preflight_environment() -> None:
    """Validate process configuration and persistent state without starting services."""
    load_dotenv()
    auth_config = AuthConfig.from_environ()

    papers_root = Path(
        brand_getenv("IPAPER_PAPERS_DIR", "./papers")
    ).resolve()
    papers_root.mkdir(parents=True, exist_ok=True)
    if not papers_root.is_dir() or papers_root.is_symlink():
        raise RuntimeError("invalid papers root")

    try:
        init_db_schema(DB_PATH)
        if auth_config.enabled and not LocalAuthService().has_active_admin():
            raise RuntimeError("local authentication has no active administrator")
        key_file = brand_getenv(
            "IPAPER_SETTINGS_KEY_FILE", "/run/secrets/ipaper_settings_key"
        ).strip()
        assert_no_plaintext_credentials(DB_PATH)
        credential_store = AgenticCredentialStore.from_key_file(key_file)
        credential_store.validate_all()
        DynamicOutboundPolicy.from_environ(os.environ)
        assert_tenant_migrated(str(papers_root), DB_PATH)
    finally:
        # Credential validation uses the non-request SQLite connection. Never let
        # that connection survive Gunicorn's subsequent worker fork.
        close_db()
