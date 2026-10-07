from dataclasses import dataclass
from time import monotonic
from urllib.parse import urljoin

import httpx

from app.core.url_safety import UnsafeURLError, validate_public_url


MAX_REDIRECTS = 5


@dataclass(frozen=True)
class CheckResult:
    success: bool
    status_code: int | None
    response_time_ms: int | None
    error_type: str | None
    error_message: str | None


def _elapsed_ms(start: float) -> int:
    return round((monotonic() - start) * 1000)


async def check_url(
    url: str,
    timeout_seconds: float = 10.0,
    transport: httpx.AsyncBaseTransport | None = None,
) -> CheckResult:
    start = monotonic()
    current_url = url

    try:
        async with httpx.AsyncClient(
            follow_redirects=False,
            timeout=timeout_seconds,
            transport=transport,
        ) as client:
            for redirect_count in range(MAX_REDIRECTS + 1):
                validate_public_url(current_url)

                response = await client.get(current_url)

                if not response.is_redirect:
                    return CheckResult(
                        success=200 <= response.status_code < 400,
                        status_code=response.status_code,
                        response_time_ms=_elapsed_ms(start),
                        error_type=None,
                        error_message=None,
                    )

                location = response.headers.get("location")

                if not location:
                    return CheckResult(
                        success=False,
                        status_code=response.status_code,
                        response_time_ms=_elapsed_ms(start),
                        error_type="invalid_redirect",
                        error_message="Redirect response has no Location header",
                    )

                if redirect_count == MAX_REDIRECTS:
                    return CheckResult(
                        success=False,
                        status_code=response.status_code,
                        response_time_ms=_elapsed_ms(start),
                        error_type="too_many_redirects",
                        error_message="Maximum redirect limit exceeded",
                    )

                current_url = urljoin(current_url, location)

    except UnsafeURLError as exc:
        return CheckResult(
            success=False,
            status_code=None,
            response_time_ms=_elapsed_ms(start),
            error_type="unsafe_url",
            error_message=str(exc),
        )

    except httpx.TimeoutException as exc:
        return CheckResult(
            success=False,
            status_code=None,
            response_time_ms=_elapsed_ms(start),
            error_type="timeout",
            error_message=str(exc) or "Request timed out",
        )

    except httpx.RequestError as exc:
        return CheckResult(
            success=False,
            status_code=None,
            response_time_ms=_elapsed_ms(start),
            error_type="request_error",
            error_message=str(exc) or "Request failed",
        )