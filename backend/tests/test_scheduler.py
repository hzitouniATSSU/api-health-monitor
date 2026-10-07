from datetime import datetime, timedelta, timezone

import pytest

from app.services import scheduler


class FakeMonitor:
    def __init__(
        self,
        monitor_id: int,
        last_checked_at: datetime | None = None,
    ):
        self.id = monitor_id
        self.current_status = "UNKNOWN"
        self.last_checked_at = last_checked_at


class FakeScalars:
    def __init__(self, monitors):
        self.monitors = monitors

    def all(self):
        return self.monitors


class FakeSession:
    def __init__(self, monitors):
        self.monitors = monitors

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return None

    def scalars(self, statement):
        return FakeScalars(self.monitors)


@pytest.mark.anyio
async def test_monitoring_cycle_checks_never_checked_monitor(
    monkeypatch,
):
    monitors = [
        FakeMonitor(1, last_checked_at=None),
    ]

    checked_ids: list[int] = []

    monkeypatch.setattr(
        scheduler,
        "SessionLocal",
        lambda: FakeSession(monitors),
    )

    async def fake_run_check(db, monitor):
        checked_ids.append(monitor.id)

    monkeypatch.setattr(
        scheduler,
        "run_check",
        fake_run_check,
    )

    await scheduler.run_monitoring_cycle()

    assert checked_ids == [1]


@pytest.mark.anyio
async def test_monitoring_cycle_checks_due_monitor(
    monkeypatch,
):
    now = datetime.now(timezone.utc)

    monitors = [
        FakeMonitor(
            1,
            last_checked_at=now - timedelta(minutes=6),
        ),
    ]

    checked_ids: list[int] = []

    monkeypatch.setattr(
        scheduler,
        "SessionLocal",
        lambda: FakeSession(monitors),
    )

    async def fake_run_check(db, monitor):
        checked_ids.append(monitor.id)

    monkeypatch.setattr(
        scheduler,
        "run_check",
        fake_run_check,
    )

    await scheduler.run_monitoring_cycle(now=now)

    assert checked_ids == [1]


@pytest.mark.anyio
async def test_monitoring_cycle_skips_monitor_not_due(
    monkeypatch,
):
    now = datetime.now(timezone.utc)

    monitors = [
        FakeMonitor(
            1,
            last_checked_at=now - timedelta(minutes=2),
        ),
    ]

    checked_ids: list[int] = []

    monkeypatch.setattr(
        scheduler,
        "SessionLocal",
        lambda: FakeSession(monitors),
    )

    async def fake_run_check(db, monitor):
        checked_ids.append(monitor.id)

    monkeypatch.setattr(
        scheduler,
        "run_check",
        fake_run_check,
    )

    await scheduler.run_monitoring_cycle(now=now)

    assert checked_ids == []