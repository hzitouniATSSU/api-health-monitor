from unittest.mock import AsyncMock, patch

import pytest

from app.database import SessionLocal
from app.models.check import Check
from app.models.monitor import Monitor
from app.services.checker import CheckResult
from app.services.monitoring import run_check


@pytest.mark.anyio
async def test_run_check_persists_success():
    with SessionLocal() as db:
        monitor = Monitor(
            name="Test API",
            url="https://example.com/health",
        )

        db.add(monitor)
        db.commit()
        db.refresh(monitor)

        monitor_id = monitor.id

        fake_result = CheckResult(
            success=True,
            status_code=200,
            response_time_ms=123,
            error_type=None,
            error_message=None,
        )

        with patch(
            "app.services.monitoring.check_url",
            new=AsyncMock(return_value=fake_result),
        ):
            check = await run_check(db, monitor)

        assert check.monitor_id == monitor_id
        assert check.success is True
        assert check.status_code == 200
        assert check.response_time_ms == 123

        db.refresh(monitor)

        assert monitor.current_status == "UP"
        assert monitor.last_checked_at is not None

        stored_check = db.get(Check, check.id)

        assert stored_check is not None
        assert stored_check.success is True

        db.delete(monitor)
        db.commit()