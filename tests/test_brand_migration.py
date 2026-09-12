"""Compatibility checks against persistent pre-rename identifiers."""
import uuid
from unittest.mock import patch
from ipaper.environment import getenv
from ipaper.auth import AuthConfig
from ipaper.security.credentials import _secret_aad, ENVELOPE_VERSION
from ipaper.security.paths import _CATEGORY_NAMESPACE
from ipaper.document_worker.safety import DocumentLimits


def test_environment_legacy_and_new_precedence(caplog):
    values = {'PAPERPILOT_VALUE': 'legacy-secret', 'IPAPER_VALUE': 'new-secret'}
    assert getenv('IPAPER_VALUE', environ=values) == 'new-secret'
    assert 'legacy-secret' not in caplog.text and 'new-secret' not in caplog.text
    assert 'IPAPER_VALUE' in caplog.text
    assert getenv('IPAPER_VALUE', environ={'PAPERPILOT_VALUE': 'old'}) == 'old'
    assert getenv('IPAPER_VALUE', 'default', environ={}) == 'default'
    assert getenv('IPAPER_VALUE', environ={'IPAPER_VALUE': '', 'PAPERPILOT_VALUE': 'old'}) == ''


def test_legacy_configuration_reaches_auth_and_worker_limits():
    old = {'PAPERPILOT_ENV': 'development', 'PAPERPILOT_AUTH_MODE': 'disabled'}
    assert not AuthConfig.from_environ(old).enabled
    with patch.dict('os.environ', {'PAPERPILOT_MAX_PDF_BYTES': '2048'}, clear=True):
        assert DocumentLimits.from_env().max_pdf_bytes == 2048


def test_existing_storage_namespace_and_ciphertext_aad_are_unchanged():
    assert _CATEGORY_NAMESPACE == uuid.uuid5(uuid.NAMESPACE_URL, 'https://github.com/ifzzh/PaperPilot/category-storage/v1')
    from ipaper.security.credentials import ALLOWED_SECRET_NAMES
    name = next(iter(ALLOWED_SECRET_NAMES))
    assert _secret_aad(name, 'owner') == f'paperpilot:agentic-secret:{ENVELOPE_VERSION}:{name}:owner'.encode('ascii')
