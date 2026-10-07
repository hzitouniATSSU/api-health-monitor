import httpx
import pytest

from app.services.checker import check_url


@pytest.mark.anyio
async def test_successful_check():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200)

    transport = httpx.MockTransport(handler)

    result = await check_url(
        "https://example.com/health",
        transport=transport,
    )

    assert result.success is True
    assert result.status_code == 200
    assert result.response_time_ms is not None
    assert result.response_time_ms >= 0
    assert result.error_type is None


@pytest.mark.anyio
async def test_server_error_is_failure():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    transport = httpx.MockTransport(handler)

    result = await check_url(
        "https://example.com/health",
        transport=transport,
    )

    assert result.success is False
    assert result.status_code == 503
    assert result.response_time_ms is not None
    assert result.error_type is None


@pytest.mark.anyio
async def test_network_error_is_failure():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(
            "Connection refused",
            request=request,
        )

    transport = httpx.MockTransport(handler)

    result = await check_url(
        "https://example.com/health",
        transport=transport,
    )

    assert result.success is False
    assert result.status_code is None
    assert result.response_time_ms is not None
    assert result.error_type == "request_error"