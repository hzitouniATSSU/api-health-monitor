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

def test_delete_monitor():
    create_response = client.post(
        "/api/monitors",
        json={
            "name": "Delete Me",
            "url": "https://example.com/health",
        },
    )

    monitor_id = create_response.json()["id"]

    response = client.delete(
        f"/api/monitors/{monitor_id}"
    )

    assert response.status_code == 204

    list_response = client.get("/api/monitors")

    assert all(
        monitor["id"] != monitor_id
        for monitor in list_response.json()
    )


def test_delete_missing_monitor_returns_404():
    response = client.delete("/api/monitors/999999")

    assert response.status_code == 404
    assert response.json() == {
        "detail": "Monitor not found"
    }


def test_list_incidents_for_missing_monitor_returns_404():
    response = client.get(
        "/api/monitors/999999/incidents"
    )

    assert response.status_code == 404
    assert response.json() == {
        "detail": "Monitor not found"
    }

def test_create_monitor_rejects_unsafe_url(
    monkeypatch,
):
    from app.api import monitors
    from app.core.url_safety import UnsafeURLError

    def reject_url(url: str) -> None:
        raise UnsafeURLError(
            "URL resolves to a non-public IP address"
        )

    monkeypatch.setattr(
        monitors,
        "validate_public_url",
        reject_url,
    )

    response = client.post(
        "/api/monitors",
        json={
            "name": "Internal Service",
            "url": "http://127.0.0.1:8000",
        },
    )

    list_response = client.get("/api/monitors")

    assert list_response.status_code == 200
    assert list_response.json() == []

    assert response.status_code == 400
    assert response.json() == {
        "detail": "URL resolves to a non-public IP address"
    }