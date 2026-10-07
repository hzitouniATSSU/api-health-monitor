import httpx
import pytest

from app.services import checker
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


@pytest.fixture(autouse=True)
def allow_test_urls(monkeypatch):
    monkeypatch.setattr(
        checker,
        "validate_public_url",
        lambda url: None,
    )

@pytest.mark.anyio
async def test_unsafe_url_is_rejected_before_request(monkeypatch):
    requests_made = 0

    def reject_private_url(url: str):
        raise checker.UnsafeURLError(
            "URL resolves to a non-public IP address"
        )

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests_made
        requests_made += 1
        return httpx.Response(200)

    monkeypatch.setattr(
        checker,
        "validate_public_url",
        reject_private_url,
    )

    result = await check_url(
        "http://127.0.0.1:8000",
        transport=httpx.MockTransport(handler),
    )

    assert result.success is False
    assert result.error_type == "unsafe_url"
    assert requests_made == 0


@pytest.mark.anyio
async def test_redirect_to_unsafe_url_is_blocked(monkeypatch):
    validated_urls: list[str] = []
    requests_made: list[str] = []

    def validate(url: str):
        validated_urls.append(url)

        if url.startswith("http://169.254.169.254"):
            raise checker.UnsafeURLError(
                "URL resolves to a non-public IP address"
            )

    def handler(request: httpx.Request) -> httpx.Response:
        requests_made.append(str(request.url))

        return httpx.Response(
            302,
            headers={
                "Location": "http://169.254.169.254/latest/meta-data/"
            },
        )

    monkeypatch.setattr(
        checker,
        "validate_public_url",
        validate,
    )

    result = await check_url(
        "https://example.com",
        transport=httpx.MockTransport(handler),
    )

    assert result.success is False
    assert result.error_type == "unsafe_url"

    assert validated_urls == [
        "https://example.com",
        "http://169.254.169.254/latest/meta-data/",
    ]

    # Only the public URL was actually requested.
    assert requests_made == [
        "https://example.com"
    ]