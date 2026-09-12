import pytest

from ipaper.security.identity import (
    DEVELOPMENT_USER_ID,
    Identity,
    reset_background_identity,
    set_background_identity,
)


@pytest.fixture(autouse=True)
def development_identity_for_unit_tests():
    """Run legacy unit fixtures under the explicit local development tenant."""
    token = set_background_identity(
        Identity(DEVELOPMENT_USER_ID, "development", "admin")
    )
    try:
        yield
    finally:
        reset_background_identity(token)
