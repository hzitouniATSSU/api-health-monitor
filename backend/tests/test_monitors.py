import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.database import SessionLocal
from app.main import app
from app.models.monitor import Monitor


client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_monitors():
    with SessionLocal() as db:
        db.execute(delete(Monitor))
        db.commit()

    yield

    with SessionLocal() as db:
        db.execute(delete(Monitor))
        db.commit()


def test_create_monitor():
    response = client.post(
        "/api/monitors",
        json={
            "name": "Example API",
            "url": "https://example.com/health",
        },
    )

    assert response.status_code == 201

    data = response.json()

    assert data["id"] is not None
    assert data["name"] == "Example API"
    assert data["url"] == "https://example.com/health"
    assert data["current_status"] == "UNKNOWN"
    assert data["last_checked_at"] is None
    assert data["created_at"] is not None


def test_list_monitors():
    client.post(
        "/api/monitors",
        json={
            "name": "First API",
            "url": "https://example.com/first",
        },
    )

    client.post(
        "/api/monitors",
        json={
            "name": "Second API",
            "url": "https://example.com/second",
        },
    )

    response = client.get("/api/monitors")

    assert response.status_code == 200

    data = response.json()

    assert len(data) == 2
    assert {monitor["name"] for monitor in data} == {
        "First API",
        "Second API",
    }


def test_create_monitor_rejects_invalid_url():
    response = client.post(
        "/api/monitors",
        json={
            "name": "Broken API",
            "url": "definitely-not-a-url",
        },
    )

    assert response.status_code == 422


def test_invalid_monitor_is_not_persisted():
    client.post(
        "/api/monitors",
        json={
            "name": "Broken API",
            "url": "definitely-not-a-url",
        },
    )

    response = client.get("/api/monitors")

    assert response.status_code == 200
    assert response.json() == []