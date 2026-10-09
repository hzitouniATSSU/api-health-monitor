import os
from urllib.parse import urlparse
import pytest

DEFAULT_TEST_DATABASE_URL = (
    "postgresql+psycopg://healthmonitor:healthmonitor"
    "@localhost:5432/healthmonitor_test"
)

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    DEFAULT_TEST_DATABASE_URL,
)

parsed = urlparse(TEST_DATABASE_URL)

if parsed.path != "/healthmonitor_test":
    raise RuntimeError(
        "Refusing to run tests against a non-test database."
    )

os.environ["DATABASE_URL"] = TEST_DATABASE_URL


@pytest.fixture
def anyio_backend():
    return "asyncio"