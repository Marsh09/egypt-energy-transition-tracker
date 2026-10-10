"""HTTP client: timeouts on every call, retry with exponential backoff."""

from __future__ import annotations

import logging
from typing import Any, Iterable, Mapping

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from ingestion.redact import redact

log = logging.getLogger(__name__)

RETRY_STATUSES = (429, 500, 502, 503, 504)


class SourceError(Exception):
    """A source could not be read (network, HTTP status, or unexpected payload)."""


class HttpClient:
    def __init__(
        self,
        connect_timeout: float = 10,
        read_timeout: float = 60,
        max_retries: int = 5,
        backoff_factor: float = 1.0,
        user_agent: str = "energy-ingestion",
    ) -> None:
        self.timeout = (float(connect_timeout), float(read_timeout))
        retry = Retry(
            total=max_retries,
            connect=max_retries,
            read=max_retries,
            status=max_retries,
            backoff_factor=backoff_factor,
            status_forcelist=RETRY_STATUSES,
            allowed_methods=frozenset({"GET"}),
            respect_retry_after_header=True,  # honours Retry-After on 429/503
            raise_on_status=True,
        )
        self.session = requests.Session()
        self.session.headers["User-Agent"] = user_agent
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    @classmethod
    def from_settings(cls, http: Mapping[str, Any]) -> "HttpClient":
        return cls(
            connect_timeout=http["connect_timeout"],
            read_timeout=http["read_timeout"],
            max_retries=int(http["max_retries"]),
            backoff_factor=float(http["backoff_factor"]),
            user_agent=http.get("user_agent", "energy-ingestion"),
        )

    def get(self, url: str, params: Mapping[str, Any] | Iterable[tuple[str, Any]] | None = None) -> requests.Response:
        """GET with retries. Raises SourceError (key-safe message) on any failure."""
        try:
            response = self.session.get(url, params=params, timeout=self.timeout)
        except requests.exceptions.RetryError as exc:
            raise SourceError(redact(f"GET {url} still failing after {self.session.adapters['https://'].max_retries.total} retries: {exc}")) from None
        except requests.exceptions.RequestException as exc:
            raise SourceError(redact(f"GET {url} failed: {type(exc).__name__}: {exc}")) from None

        if response.status_code >= 400:
            snippet = response.text[:300].replace("\n", " ")
            hint = " (check the API key)" if response.status_code in (401, 403) else ""
            raise SourceError(redact(f"HTTP {response.status_code}{hint} from {response.url}: {snippet}"))
        return response
