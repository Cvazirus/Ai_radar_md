import time
from typing import Any, Dict, Optional
import httpx
import structlog

logger = structlog.get_logger()

RETRY_STATUS_CODES = {429, 500, 502, 503, 504}


def fetch_json(
    url: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    timeout_seconds: int = 20,
    max_retries: int = 3,
    retry_delay: float = 2.0,
    source_name: str = "",
) -> Any:
    """GET-запрос с ретраями на временные ошибки, возвращает распарсенный JSON."""
    return _fetch(
        url, params=params, headers=headers, timeout_seconds=timeout_seconds,
        max_retries=max_retries, retry_delay=retry_delay, source_name=source_name,
    ).json()


def fetch_text(
    url: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    timeout_seconds: int = 20,
    max_retries: int = 3,
    retry_delay: float = 2.0,
    source_name: str = "",
) -> str:
    """GET-запрос с ретраями на временные ошибки, возвращает тело ответа как текст."""
    return _fetch(
        url, params=params, headers=headers, timeout_seconds=timeout_seconds,
        max_retries=max_retries, retry_delay=retry_delay, source_name=source_name,
    ).text


def _fetch(
    url: str,
    *,
    params: Optional[Dict[str, Any]],
    headers: Optional[Dict[str, str]],
    timeout_seconds: int,
    max_retries: int,
    retry_delay: float,
    source_name: str,
) -> httpx.Response:
    last_exc: Optional[Exception] = None
    for attempt in range(1, max_retries + 1):
        try:
            with httpx.Client(follow_redirects=True, timeout=timeout_seconds) as client:
                resp = client.get(url, params=params, headers=headers)
                if resp.status_code == 200:
                    return resp
                if resp.status_code in RETRY_STATUS_CODES:
                    raise httpx.HTTPStatusError(
                        f"HTTP Status {resp.status_code}", request=resp.request, response=resp
                    )
                resp.raise_for_status()
        except (httpx.RequestError, httpx.HTTPStatusError) as e:
            last_exc = e
            logger.warn(
                "collector_fetch_attempt_failed",
                source_name=source_name,
                url=url,
                attempt=attempt,
                error=str(e),
            )
            if attempt == max_retries:
                raise
            time.sleep(retry_delay * attempt)

    raise last_exc or RuntimeError("Unexpected end of retry loop")
