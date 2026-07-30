from __future__ import annotations

import logging
import time
from typing import Any

import requests

LOGGER = logging.getLogger(__name__)


class APIError(RuntimeError):
    """Raised when an external API remains unavailable after retries."""


class HTTPCollector:
    def __init__(
        self,
        *,
        timeout: float = 15,
        max_retries: int = 3,
        backoff: float = 1.0,
    ) -> None:
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff = backoff
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "crypto-advisor-bot/1.0"})

    def get_json(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        error: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                response = self.session.get(
                    url,
                    params=params,
                    headers=headers,
                    timeout=self.timeout,
                )
                if response.status_code == 429 or response.status_code >= 500:
                    raise requests.HTTPError(
                        f"HTTP {response.status_code}", response=response
                    )
                # Retrying legal/authorization/not-found responses only delays the
                # fallback provider and cannot make the request succeed.
                if 400 <= response.status_code < 500:
                    raise APIError(
                        f"HTTP {response.status_code} from {url}: "
                        f"{response.text[:160]}"
                    )
                response.raise_for_status()
                return response.json()
            except APIError:
                raise
            except (requests.RequestException, ValueError) as exc:
                error = exc
                if attempt + 1 < self.max_retries:
                    wait = self.backoff * (2**attempt)
                    LOGGER.warning(
                        "API attempt %s/%s failed for %s; retrying in %.1fs",
                        attempt + 1,
                        self.max_retries,
                        url,
                        wait,
                    )
                    time.sleep(wait)
        raise APIError(f"API unavailable: {url}: {error}") from error
