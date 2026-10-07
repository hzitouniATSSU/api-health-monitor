from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.models.incident import Incident
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

@pytest.mark.anyio
async def test_down_down_up_creates_and_resolves_one_incident():
    with SessionLocal() as db:
        monitor = Monitor(
            name="Incident Test",
            url="https://example.com/health",
            current_status="UP",
        )

        db.add(monitor)
        db.commit()
        db.refresh(monitor)

        monitor_id = monitor.id

        down_result = CheckResult(
            success=False,
            status_code=503,
            response_time_ms=100,
            error_type=None,
            error_message=None,
        )

        up_result = CheckResult(
            success=True,
            status_code=200,
            response_time_ms=80,
            error_type=None,
            error_message=None,
        )

        with (
            patch(
                "app.services.monitoring.check_url",
                new=AsyncMock(
                    side_effect=[
                        down_result,
                        down_result,
                        up_result,
                    ]
                ),
            ),
            patch(
                "app.services.monitoring.send_down_alert"
            ) as mock_down_alert,
            patch(
                "app.services.monitoring.send_recovery_alert"
            ) as mock_recovery_alert,
        ):
            await run_check(db, monitor)
            assert monitor.current_status == "DOWN"

            await run_check(db, monitor)
            assert monitor.current_status == "DOWN"

            await run_check(db, monitor)
            assert monitor.current_status == "UP"

            assert mock_down_alert.call_count == 1
            assert mock_recovery_alert.call_count == 1
                

        incidents = list(
            db.scalars(
                select(Incident)
                .where(Incident.monitor_id == monitor_id)
            ).all()
        )

        assert len(incidents) == 1
        assert incidents[0].started_at is not None
        assert incidents[0].resolved_at is not None
        assert incidents[0].resolved_at >= incidents[0].started_at

        db.delete(monitor)
        db.commit()