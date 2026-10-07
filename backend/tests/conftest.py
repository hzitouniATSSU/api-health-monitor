import os


TEST_DATABASE_URL = (
    "postgresql+psycopg://healthmonitor:healthmonitor"
    "@localhost:5432/healthmonitor_test"
)

if not TEST_DATABASE_URL.endswith("/healthmonitor_test"):
    raise RuntimeError(
        "Refusing to run tests against a non-test database."
    )

os.environ["DATABASE_URL"] = TEST_DATABASE_URL