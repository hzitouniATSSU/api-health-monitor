import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, event, func, insert, select
from datetime import datetime, timedelta, timezone

from app.database import SessionLocal, engine
from app.main import app
from app.models.monitor import Monitor
from app.models.incident import Incident
from app.models.check import Check


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

def test_list_incidents_returns_ongoing_and_resolved():
    with SessionLocal() as db:
        monitor = Monitor(
            name="Incident History Test",
            url="https://example.com/health",
        )
        db.add(monitor)
        db.flush()

        now = datetime.now(timezone.utc)

        resolved = Incident(
            monitor_id=monitor.id,
            started_at=now - timedelta(hours=2),
            resolved_at=now - timedelta(hours=1),
        )

        ongoing = Incident(
            monitor_id=monitor.id,
            started_at=now - timedelta(minutes=15),
            resolved_at=None,
        )

        db.add_all([resolved, ongoing])
        db.commit()
        monitor_id = monitor.id

    response = client.get(
        f"/api/monitors/{monitor_id}/incidents"
    )

    assert response.status_code == 200

    incidents = response.json()

    assert len(incidents) == 2

    assert incidents[0]["resolved_at"] is None
    assert incidents[1]["resolved_at"] is not None

    assert incidents[0]["monitor_id"] == monitor_id
    assert incidents[0]["id"] is not None
    assert incidents[0]["started_at"] is not None

@pytest.mark.parametrize(
    "payload",
    [
        {"name": "x" * 101, "url": "https://example.com/health"},
        {"name": "", "url": "https://example.com/health"},
        {"name": "   ", "url": "https://example.com/health"},
        {"name": "Long URL", "url": "https://example.com/" + "a" * 2050},
        # 2048 characters as sent, 2049 once normalized to ".com/?".
        {"name": "Long URL", "url": "https://example.com?" + "a" * 2028},
    ],
    ids=[
        "name-too-long",
        "name-empty",
        "name-blank",
        "url-too-long",
        "url-too-long-after-normalization",
    ],
)
def test_create_monitor_rejects_invalid_fields(payload):
    response = client.post("/api/monitors", json=payload)

    assert response.status_code == 422
    assert client.get("/api/monitors").json() == []


def test_create_monitor_strips_name_whitespace():
    response = client.post(
        "/api/monitors",
        json={
            "name": "  Padded API  ",
            "url": "https://example.com/health",
        },
    )

    assert response.status_code == 201
    assert response.json()["name"] == "Padded API"


def test_delete_monitor_relies_on_database_cascade():
    with SessionLocal() as db:
        monitor = Monitor(
            name="Cascade Test",
            url="https://example.com/health",
        )
        db.add(monitor)
        db.flush()
        monitor_id = monitor.id

        db.execute(
            insert(Check),
            [{"monitor_id": monitor_id, "success": True} for _ in range(50)],
        )
        db.add(Incident(monitor_id=monitor_id))
        db.commit()

    statements: list[str] = []

    def record(conn, cursor, statement, *args):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", record)

    try:
        response = client.delete(f"/api/monitors/{monitor_id}")
    finally:
        event.remove(engine, "before_cursor_execute", record)

    assert response.status_code == 204

    # Child rows must be removed by ON DELETE CASCADE, not loaded into
    # memory and deleted one by one by the ORM.
    assert not any("FROM checks" in s for s in statements)
    assert not any("FROM incidents" in s for s in statements)

    with SessionLocal() as db:
        assert db.scalar(
            select(func.count()).select_from(Check)
            .where(Check.monitor_id == monitor_id)
        ) == 0
        assert db.scalar(
            select(func.count()).select_from(Incident)
            .where(Incident.monitor_id == monitor_id)
        ) == 0


def test_create_monitor_accepts_values_at_column_limits():
    url = "https://example.com/" + "a" * (2048 - len("https://example.com/"))

    response = client.post(
        "/api/monitors",
        json={"name": "n" * 100, "url": url},
    )

    assert response.status_code == 201
    assert response.json()["name"] == "n" * 100
    assert response.json()["url"] == url
