from app.services import scheduler
import pytest



class FakeMonitor:
    def __init__(self, monitor_id: int):
        self.id = monitor_id
        self.current_status = "UNKNOWN"


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
async def test_monitoring_cycle_checks_every_monitor(monkeypatch):
    monitors = [
        FakeMonitor(1),
        FakeMonitor(2),
    ]

    checked_ids: list[int] = []

    monkeypatch.setattr(
        scheduler,
        "SessionLocal",
        lambda: FakeSession(monitors),
    )

    async def fake_run_check(db, monitor):
        checked_ids.append(monitor.id)
        monitor.current_status = "UP"

    monkeypatch.setattr(
        scheduler,
        "run_check",
        fake_run_check,
    )

    await scheduler.run_monitoring_cycle()

    assert checked_ids == [1, 2]