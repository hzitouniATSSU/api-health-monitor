from unittest.mock import patch

from app.models.monitor import Monitor
from app.services.alerts import send_down_alert, send_recovery_alert


def make_monitor() -> Monitor:
    return Monitor(
        id=42,
        name="Payments API",
        url="https://example.com/health",
        current_status="DOWN",
    )


@patch("app.services.alerts.settings")
@patch("app.services.alerts.resend.Emails.send")
def test_send_down_alert(mock_send, mock_settings):
    mock_settings.resend_api_key = "test-key"
    mock_settings.alert_from_email = "alerts@example.com"
    mock_settings.alert_to_email = "owner@example.com"

    monitor = make_monitor()

    send_down_alert(monitor)

    mock_send.assert_called_once()

    payload = mock_send.call_args.args[0]

    assert payload["from"] == "alerts@example.com"
    assert payload["to"] == ["owner@example.com"]
    assert payload["subject"] == "DOWN: Payments API"
    assert "https://example.com/health" in payload["text"]


@patch("app.services.alerts.settings")
@patch("app.services.alerts.resend.Emails.send")
def test_send_recovery_alert(mock_send, mock_settings):
    mock_settings.resend_api_key = "test-key"
    mock_settings.alert_from_email = "alerts@example.com"
    mock_settings.alert_to_email = "owner@example.com"

    monitor = make_monitor()

    send_recovery_alert(monitor)

    mock_send.assert_called_once()

    payload = mock_send.call_args.args[0]

    assert payload["subject"] == "RECOVERED: Payments API"
    assert "https://example.com/health" in payload["text"]


@patch("app.services.alerts.settings")
@patch("app.services.alerts.resend.Emails.send")
def test_alert_is_skipped_when_not_configured(
    mock_send,
    mock_settings,
):
    mock_settings.resend_api_key = None
    mock_settings.alert_from_email = None
    mock_settings.alert_to_email = None

    send_down_alert(make_monitor())

    mock_send.assert_not_called()