from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture(autouse=True)
def _no_live_bluez():
    """Keep connect() from querying the real system bus during tests."""
    with patch("fichero.printer._bluez_connected_printer", AsyncMock(return_value=None)):
        yield
