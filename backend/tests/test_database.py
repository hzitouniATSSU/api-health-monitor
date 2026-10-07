from app.config import settings


def test_uses_test_database():
    assert settings.database_url.endswith("/healthmonitor_test")