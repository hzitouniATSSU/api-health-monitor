from dataclasses import dataclass
from time import monotonic

import httpx


@dataclass(frozen=True)
class CheckResult:
    success: bool
    status_code: int | None
    response_time_ms: int | None
    error_type: str | None
    error_message: str | None


async def check_url(
    url: str,
    timeout_seconds: float = 10.0,
    transport: httpx.AsyncBaseTransport | None = None,
) -> CheckResult:
    start = monotonic()

    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=timeout_seconds,
            transport=transport,
        ) as client:
            response = await client.get(url)

        elapsed_ms = round((monotonic() - start) * 1000)

        return CheckResult(
            success=200 <= response.status_code < 400,
            status_code=response.status_code,
            response_time_ms=elapsed_ms,
            error_type=None,
            error_message=None,
        )

    except httpx.TimeoutException as exc:
        elapsed_ms = round((monotonic() - start) * 1000)

        return CheckResult(
            success=False,
            status_code=None,
            response_time_ms=elapsed_ms,
            error_type="timeout",
            error_message=str(exc) or "Request timed out",
        )

    except httpx.RequestError as exc:
        elapsed_ms = round((monotonic() - start) * 1000)

        return CheckResult(
            success=False,
            status_code=None,
            response_time_ms=elapsed_ms,
            error_type="request_error",
            error_message=str(exc) or "Request failed",
        )