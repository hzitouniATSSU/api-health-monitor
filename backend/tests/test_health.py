import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, text
from sqlalchemy.exc import OperationalError, ProgrammingError

from app.config import settings
from app.database import engine
from app.main import app
from app.models.worker_heartbeat import WorkerHeartbeat
from app.services.heartbeat import MONITORING_WORKER, HeartbeatWriter

client = TestClient(app)


def test_health_returns_ok():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status" : "ok"}

def test_readiness_checks_database():
    response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


def test_readiness_reports_database_failure(monkeypatch):
    from app import main

    class BrokenEngine:
        def connect(self):
            raise OperationalError("SELECT 1", {}, Exception("down"))

    monkeypatch.setattr(main, "engine", BrokenEngine())

    response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "unavailable",
        "database": "unreachable",
    }


# --- /health/worker -------------------------------------------------------


@pytest.fixture
def clean_heartbeat():
    def clear():
        with engine.begin() as connection:
            connection.execute(
                delete(WorkerHeartbeat).where(
                    WorkerHeartbeat.worker_name == MONITORING_WORKER
                )
            )

    clear()
    yield
    clear()


def record_completed_cycle(instance_id="test-worker"):
    writer = HeartbeatWriter(instance_id=instance_id)
    writer.beat()
    writer.beat(cycle_started=True, monitor_count=0)
    writer.beat(cycle_completed=True, cycle_duration_ms=3)


def age_heartbeat(seconds):
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE worker_heartbeats SET "
                "started_at = started_at - make_interval(secs => :s), "
                "last_heartbeat_at = last_heartbeat_at - make_interval(secs => :s), "
                "last_cycle_started_at = last_cycle_started_at - make_interval(secs => :s), "
                "last_cycle_completed_at = last_cycle_completed_at - make_interval(secs => :s) "
                "WHERE worker_name = :name"
            ),
            {"s": seconds, "name": MONITORING_WORKER},
        )


def test_worker_health_fresh_heartbeat(clean_heartbeat):
    record_completed_cycle()

    response = client.get("/health/worker")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"
    assert body["worker"]["status"] == "healthy"
    assert body["worker"]["instance_id"] == "test-worker"
    assert body["worker"]["stale_after_seconds"] == 120
    assert body["worker"]["last_cycle_monitor_count"] == 0
    assert body["worker"]["cycle_in_progress"] is False


def test_worker_health_stale_heartbeat(clean_heartbeat):
    record_completed_cycle()
    age_heartbeat(121)

    response = client.get("/health/worker")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "unavailable"
    assert body["database"] == "ok"
    assert body["worker"]["status"] == "stale"
    assert body["worker"]["heartbeat_age_seconds"] > 120


def test_worker_health_uses_configured_threshold(clean_heartbeat, monkeypatch):
    record_completed_cycle()
    age_heartbeat(45)

    monkeypatch.setattr(settings, "worker_heartbeat_stale_seconds", 60)
    assert client.get("/health/worker").status_code == 200

    monkeypatch.setattr(settings, "worker_heartbeat_stale_seconds", 30)
    response = client.get("/health/worker")
    assert response.status_code == 503
    assert response.json()["worker"]["stale_after_seconds"] == 30


def test_worker_health_missing_heartbeat(clean_heartbeat):
    response = client.get("/health/worker")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "unavailable"
    assert body["database"] == "ok"
    assert body["worker"]["status"] == "missing"
    assert body["worker"]["checked_at"] is not None


def test_worker_health_starting_is_not_an_error(clean_heartbeat):
    HeartbeatWriter(instance_id="booting").beat()

    response = client.get("/health/worker")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["worker"]["status"] == "starting"


def test_worker_health_database_unavailable(monkeypatch):
    from app import main

    class BrokenEngine:
        def connect(self):
            raise OperationalError("SELECT now()", {}, Exception("down"))

    monkeypatch.setattr(main, "engine", BrokenEngine())

    response = client.get("/health/worker")

    assert response.status_code == 503
    assert response.json() == {
        "status": "unavailable",
        "database": "unreachable",
        "worker": {
            "status": "unknown",
            "detail": "Database unreachable; worker health cannot be determined.",
            "stale_after_seconds": 120,
            "checked_at": None,
            "heartbeat_age_seconds": None,
            "instance_id": None,
            "started_at": None,
            "last_heartbeat_at": None,
            "last_cycle_started_at": None,
            "last_cycle_completed_at": None,
            "last_cycle_duration_ms": None,
            "last_cycle_monitor_count": None,
            "cycle_in_progress": None,
        },
    }


def test_worker_health_reports_unapplied_migration(monkeypatch):
    from app import main

    class UndefinedTable(Exception):
        sqlstate = "42P01"

    class MissingTableEngine:
        def connect(self):
            raise ProgrammingError("SELECT", {}, UndefinedTable())

    monkeypatch.setattr(main, "engine", MissingTableEngine())

    response = client.get("/health/worker")

    assert response.status_code == 503
    body = response.json()
    assert body["database"] == "ok"
    assert body["worker"]["status"] == "unknown"
    assert "alembic upgrade head" in body["worker"]["detail"]


def test_stale_worker_does_not_affect_liveness_or_readiness(clean_heartbeat):
    record_completed_cycle()
    age_heartbeat(3600)

    assert client.get("/health/worker").status_code == 503

    assert client.get("/health").json() == {"status": "ok"}

    ready = client.get("/health/ready")
    assert ready.status_code == 200
    assert ready.json() == {"status": "ok", "database": "ok"}
