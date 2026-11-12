import uuid
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError
from sqlalchemy import delete, text
from sqlalchemy.exc import OperationalError

from app.config import Settings
from app.database import engine
from app.models.worker_heartbeat import WorkerHeartbeat
from app.schemas.health import WorkerStatus
from app.services import scheduler
from app.services.heartbeat import (
    HeartbeatWriter,
    evaluate_worker_health,
    read_worker_health,
)

STALE_AFTER = 120
NOW = datetime(2026, 10, 13, 12, 0, 0, tzinfo=timezone.utc)


def make_row(
    *,
    heartbeat_age: float = 5,
    started_ago: float = 600,
    cycle_started_ago: float | None = 30,
    cycle_completed_ago: float | None = 20,
    instance_id: str = "worker-a",
) -> dict:
    def ago(seconds):
        if seconds is None:
            return None
        return NOW - timedelta(seconds=seconds)

    return {
        "worker_name": "monitoring",
        "instance_id": instance_id,
        "started_at": ago(started_ago),
        "last_heartbeat_at": ago(heartbeat_age),
        "last_cycle_started_at": ago(cycle_started_ago),
        "last_cycle_completed_at": ago(cycle_completed_ago),
        "last_cycle_duration_ms": 1500,
        "last_cycle_monitor_count": 3,
    }


# --- Classification (pure, deterministic clock) ---------------------------


def test_fresh_heartbeat_is_healthy():
    health = evaluate_worker_health(make_row(), NOW, STALE_AFTER)

    assert health.status == WorkerStatus.HEALTHY
    assert health.heartbeat_age_seconds == 5
    assert health.cycle_in_progress is False
    assert health.instance_id == "worker-a"


def test_stale_heartbeat_is_stale():
    health = evaluate_worker_health(
        make_row(heartbeat_age=600),
        NOW,
        STALE_AFTER,
    )

    assert health.status == WorkerStatus.STALE
    assert "600s" in health.detail
    assert "threshold 120s" in health.detail


def test_missing_heartbeat_is_missing():
    health = evaluate_worker_health(None, NOW, STALE_AFTER)

    assert health.status == WorkerStatus.MISSING
    assert health.heartbeat_age_seconds is None
    assert health.checked_at == NOW


@pytest.mark.parametrize(
    ("age", "expected"),
    [
        (STALE_AFTER - 0.001, WorkerStatus.HEALTHY),
        (STALE_AFTER, WorkerStatus.HEALTHY),
        (STALE_AFTER + 0.001, WorkerStatus.STALE),
    ],
    ids=["just-below", "exactly-at", "just-above"],
)
def test_staleness_threshold_boundary(age, expected):
    health = evaluate_worker_health(
        make_row(heartbeat_age=age),
        NOW,
        STALE_AFTER,
    )

    assert health.status == expected


def test_threshold_is_respected_when_configured_lower():
    row = make_row(heartbeat_age=45)

    assert evaluate_worker_health(row, NOW, 60).status == WorkerStatus.HEALTHY
    assert evaluate_worker_health(row, NOW, 30).status == WorkerStatus.STALE


def test_worker_that_never_completed_a_cycle_is_starting():
    health = evaluate_worker_health(
        make_row(
            started_ago=8,
            cycle_started_ago=None,
            cycle_completed_ago=None,
        ),
        NOW,
        STALE_AFTER,
    )

    assert health.status == WorkerStatus.STARTING
    assert health.cycle_in_progress is False


def test_restarted_worker_is_starting_despite_older_completed_cycle():
    # The previous instance completed a cycle before this one started.
    health = evaluate_worker_health(
        make_row(
            heartbeat_age=1,
            started_ago=5,
            cycle_started_ago=300,
            cycle_completed_ago=290,
        ),
        NOW,
        STALE_AFTER,
    )

    assert health.status == WorkerStatus.STARTING


def test_previous_instance_unfinished_cycle_is_not_in_progress():
    # The old instance died mid-cycle; the new one has not started a cycle.
    health = evaluate_worker_health(
        make_row(
            heartbeat_age=1,
            started_ago=5,
            cycle_started_ago=60,
            cycle_completed_ago=400,
        ),
        NOW,
        STALE_AFTER,
    )

    assert health.status == WorkerStatus.STARTING
    assert health.cycle_in_progress is False


def test_stale_takes_precedence_over_starting():
    # A worker that registered and then hung before finishing its first
    # cycle must not be reported as merely "starting".
    health = evaluate_worker_health(
        make_row(
            heartbeat_age=STALE_AFTER + 30,
            started_ago=STALE_AFTER + 30,
            cycle_started_ago=None,
            cycle_completed_ago=None,
        ),
        NOW,
        STALE_AFTER,
    )

    assert health.status == WorkerStatus.STALE


def test_long_running_cycle_with_fresh_heartbeat_is_healthy():
    # The cycle has run far longer than the threshold, but per-check
    # heartbeats show it is still making progress.
    health = evaluate_worker_health(
        make_row(
            heartbeat_age=4,
            started_ago=3600,
            cycle_started_ago=STALE_AFTER * 5,
            cycle_completed_ago=STALE_AFTER * 5 + 10,
        ),
        NOW,
        STALE_AFTER,
    )

    assert health.status == WorkerStatus.HEALTHY
    assert health.cycle_in_progress is True


def test_long_running_first_cycle_is_starting_not_stale():
    health = evaluate_worker_health(
        make_row(
            heartbeat_age=4,
            started_ago=STALE_AFTER * 5,
            cycle_started_ago=STALE_AFTER * 5 - 1,
            cycle_completed_ago=None,
        ),
        NOW,
        STALE_AFTER,
    )

    assert health.status == WorkerStatus.STARTING
    assert health.cycle_in_progress is True


def test_heartbeat_slightly_in_the_future_is_clamped_to_zero_age():
    health = evaluate_worker_health(
        make_row(heartbeat_age=-0.5),
        NOW,
        STALE_AFTER,
    )

    assert health.status == WorkerStatus.HEALTHY
    assert health.heartbeat_age_seconds == 0


@pytest.mark.parametrize("value", [29, 0, -1])
def test_stale_threshold_below_minimum_is_rejected(value):
    with pytest.raises(ValidationError):
        Settings(
            database_url="postgresql+psycopg://x@localhost/healthmonitor_test",
            worker_heartbeat_stale_seconds=value,
        )


def test_stale_threshold_minimum_is_accepted():
    configured = Settings(
        database_url="postgresql+psycopg://x@localhost/healthmonitor_test",
        worker_heartbeat_stale_seconds=30,
    )

    assert configured.worker_heartbeat_stale_seconds == 30


# --- Writer and reader against the test database --------------------------


@pytest.fixture
def worker_name():
    # A unique row per test so tests never see each other's heartbeats.
    name = f"test-{uuid.uuid4().hex[:12]}"
    yield name

    with engine.begin() as connection:
        connection.execute(
            delete(WorkerHeartbeat).where(WorkerHeartbeat.worker_name == name)
        )


def read(worker_name, stale_after=STALE_AFTER):
    with engine.connect() as connection:
        return read_worker_health(connection, stale_after, worker_name)


def shift_back(worker_name, seconds, *columns):
    assignments = ", ".join(
        f"{column} = {column} - make_interval(secs => :seconds)"
        for column in columns
    )

    with engine.begin() as connection:
        connection.execute(
            text(
                f"UPDATE worker_heartbeats SET {assignments} "
                "WHERE worker_name = :name"
            ),
            {"seconds": seconds, "name": worker_name},
        )


def test_missing_heartbeat_row_reads_as_missing(worker_name):
    assert read(worker_name).status == WorkerStatus.MISSING


def test_registration_reports_starting(worker_name):
    writer = HeartbeatWriter(worker_name=worker_name, instance_id="a")

    assert writer.beat() is True

    health = read(worker_name)

    assert health.status == WorkerStatus.STARTING
    assert health.instance_id == "a"
    assert health.last_cycle_completed_at is None


def test_completed_cycle_reports_healthy_with_cycle_details(worker_name):
    writer = HeartbeatWriter(worker_name=worker_name, instance_id="a")

    writer.beat()
    writer.beat(cycle_started=True, monitor_count=4)

    mid_cycle = read(worker_name)
    assert mid_cycle.status == WorkerStatus.STARTING
    assert mid_cycle.cycle_in_progress is True

    writer.beat()
    writer.beat(cycle_completed=True, cycle_duration_ms=2500)

    health = read(worker_name)

    assert health.status == WorkerStatus.HEALTHY
    assert health.cycle_in_progress is False
    assert health.last_cycle_monitor_count == 4
    assert health.last_cycle_duration_ms == 2500
    assert health.heartbeat_age_seconds < 5


def test_beats_from_same_instance_keep_started_at(worker_name):
    writer = HeartbeatWriter(worker_name=worker_name, instance_id="a")

    writer.beat()
    first = read(worker_name)

    shift_back(worker_name, 30, "started_at")
    writer.beat()
    second = read(worker_name)

    assert second.started_at == first.started_at - timedelta(seconds=30)


def test_stale_heartbeat_in_database_reads_as_stale(worker_name):
    writer = HeartbeatWriter(worker_name=worker_name, instance_id="a")
    writer.beat()
    writer.beat(cycle_started=True, monitor_count=0)
    writer.beat(cycle_completed=True, cycle_duration_ms=5)

    shift_back(
        worker_name,
        STALE_AFTER + 1,
        "started_at",
        "last_heartbeat_at",
        "last_cycle_started_at",
        "last_cycle_completed_at",
    )

    health = read(worker_name)

    assert health.status == WorkerStatus.STALE
    assert health.heartbeat_age_seconds > STALE_AFTER


def test_worker_restart_resets_started_at_and_reports_starting(worker_name):
    old = HeartbeatWriter(worker_name=worker_name, instance_id="old")
    old.beat()
    old.beat(cycle_started=True, monitor_count=2)
    old.beat(cycle_completed=True, cycle_duration_ms=10)

    shift_back(
        worker_name,
        300,
        "started_at",
        "last_heartbeat_at",
        "last_cycle_started_at",
        "last_cycle_completed_at",
    )
    assert read(worker_name).status == WorkerStatus.STALE

    new = HeartbeatWriter(worker_name=worker_name, instance_id="new")
    new.beat()

    restarted = read(worker_name)

    assert restarted.status == WorkerStatus.STARTING
    assert restarted.instance_id == "new"
    assert restarted.started_at > restarted.last_cycle_completed_at

    new.beat(cycle_started=True, monitor_count=2)
    new.beat(cycle_completed=True, cycle_duration_ms=10)

    assert read(worker_name).status == WorkerStatus.HEALTHY


def test_long_running_cycle_stays_healthy_in_database(worker_name):
    writer = HeartbeatWriter(worker_name=worker_name, instance_id="a")
    writer.beat()
    writer.beat(cycle_started=True, monitor_count=1)
    writer.beat(cycle_completed=True, cycle_duration_ms=10)
    writer.beat(cycle_started=True, monitor_count=50)

    # The cycle began 10 minutes ago and is still checking monitors.
    shift_back(worker_name, 600, "started_at", "last_cycle_completed_at")
    shift_back(worker_name, 590, "last_cycle_started_at")
    writer.beat()

    health = read(worker_name)

    assert health.status == WorkerStatus.HEALTHY
    assert health.cycle_in_progress is True


def test_heartbeat_failure_is_logged_not_raised(caplog):
    class BrokenEngine:
        def begin(self):
            raise OperationalError("INSERT", {}, Exception("down"))

    writer = HeartbeatWriter(instance_id="a", engine=BrokenEngine())

    assert writer.beat() is False
    assert "Failed to record heartbeat" in caplog.text


# --- Scheduler integration ------------------------------------------------


class RecordingHeartbeat:
    instance_id = "recording"

    def __init__(self):
        self.beats: list[dict] = []

    def beat(self, **kwargs):
        self.beats.append(kwargs)
        return True


class FakeMonitor:
    def __init__(self, monitor_id):
        self.id = monitor_id
        self.current_status = "UNKNOWN"
        self.last_checked_at = None


class FakeSession:
    def __init__(self, monitors):
        self.monitors = monitors

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None

    def scalars(self, statement):
        monitors = self.monitors

        class Result:
            def all(self):
                return monitors

        return Result()


@pytest.mark.anyio
async def test_cycle_with_zero_monitors_still_beats_and_completes(monkeypatch):
    heartbeat = RecordingHeartbeat()
    monkeypatch.setattr(scheduler, "SessionLocal", lambda: FakeSession([]))

    await scheduler.run_monitoring_cycle(heartbeat=heartbeat)

    assert heartbeat.beats[0] == {"cycle_started": True, "monitor_count": 0}
    assert heartbeat.beats[-1]["cycle_completed"] is True
    assert len(heartbeat.beats) == 2


@pytest.mark.anyio
async def test_cycle_beats_after_every_check_including_failures(monkeypatch):
    heartbeat = RecordingHeartbeat()
    monitors = [FakeMonitor(1), FakeMonitor(2), FakeMonitor(3)]
    monkeypatch.setattr(
        scheduler,
        "SessionLocal",
        lambda: FakeSession(monitors),
    )

    beats_seen_at_check: list[int] = []

    async def fake_run_check(db, monitor):
        beats_seen_at_check.append(len(heartbeat.beats))
        if monitor.id == 2:
            raise RuntimeError("check blew up")

    monkeypatch.setattr(scheduler, "run_check", fake_run_check)

    await scheduler.run_monitoring_cycle(heartbeat=heartbeat)

    # start, one per check (the failing one too), completion
    assert len(heartbeat.beats) == 5
    assert beats_seen_at_check == [1, 2, 3]
    assert heartbeat.beats[-1]["cycle_completed"] is True
    assert heartbeat.beats[-1]["cycle_duration_ms"] >= 0


@pytest.mark.anyio
async def test_failed_cycle_does_not_record_progress(monkeypatch):
    heartbeat = RecordingHeartbeat()

    class BrokenSession(FakeSession):
        def scalars(self, statement):
            raise OperationalError("SELECT", {}, Exception("down"))

    monkeypatch.setattr(scheduler, "SessionLocal", lambda: BrokenSession([]))

    with pytest.raises(OperationalError):
        await scheduler.run_monitoring_cycle(heartbeat=heartbeat)

    assert heartbeat.beats == []


@pytest.mark.anyio
async def test_scheduler_loop_registers_before_first_cycle(monkeypatch):
    heartbeat = RecordingHeartbeat()
    events: list[str] = []

    original_beat = heartbeat.beat

    def tracking_beat(**kwargs):
        events.append("beat")
        return original_beat(**kwargs)

    heartbeat.beat = tracking_beat

    async def fake_cycle(heartbeat=None):
        events.append("cycle")

    class StopLoop(Exception):
        pass

    async def stop_sleep(seconds):
        raise StopLoop

    monkeypatch.setattr(scheduler, "run_monitoring_cycle", fake_cycle)
    monkeypatch.setattr(scheduler.asyncio, "sleep", stop_sleep)

    with pytest.raises(StopLoop):
        await scheduler.scheduler_loop(heartbeat=heartbeat)

    assert events == ["beat", "cycle"]
