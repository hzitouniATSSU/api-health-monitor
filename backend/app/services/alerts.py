import logging

import resend

from app.config import settings
from app.models.monitor import Monitor

logger = logging.getLogger(__name__)


def alerts_configured() -> bool:
    return all(
        (
            settings.resend_api_key,
            settings.alert_from_email,
            settings.alert_to_email,
        )
    )


def send_down_alert(monitor: Monitor) -> None:
    if not alerts_configured():
        logger.info(
            "Email alerts not configured; skipping DOWN alert for monitor id=%s",
            monitor.id,
        )
        return

    resend.api_key = settings.resend_api_key

    resend.Emails.send(
        {
            "from": settings.alert_from_email,
            "to": [settings.alert_to_email],
            "subject": f"DOWN: {monitor.name}",
            "text": (
                f"{monitor.name} is DOWN.\n\n"
                f"URL: {monitor.url}\n"
                f"Monitor ID: {monitor.id}"
            ),
        }
    )


def send_recovery_alert(monitor: Monitor) -> None:
    if not alerts_configured():
        logger.info(
            "Email alerts not configured; skipping recovery alert for monitor id=%s",
            monitor.id,
        )
        return

    resend.api_key = settings.resend_api_key

    resend.Emails.send(
        {
            "from": settings.alert_from_email,
            "to": [settings.alert_to_email],
            "subject": f"RECOVERED: {monitor.name}",
            "text": (
                f"{monitor.name} has recovered.\n\n"
                f"URL: {monitor.url}\n"
                f"Monitor ID: {monitor.id}"
            ),
        }
    )