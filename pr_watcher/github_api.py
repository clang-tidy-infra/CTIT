"""Minimal GitHub REST client used by the nightly new-check watcher."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

API_ROOT = "https://api.github.com"
PAGE_SIZE = 100
MAX_PAGES = 10
MAX_ATTEMPTS = 3
RETRY_DELAY_SECONDS = 5
REJECTED_STATUS = frozenset({403, 429})
AMBIGUOUS_STATUS = frozenset({500, 502, 503, 504})
IDEMPOTENT_METHODS = frozenset({"GET", "HEAD"})


class GitHubError(RuntimeError):
    """A GitHub API request failed."""


class GitHubClient:
    """JSON-over-HTTPS client with retries and offset pagination."""

    def __init__(self, token: str, api_root: str = API_ROOT) -> None:
        self._token = token
        self._api_root = api_root.rstrip("/")

    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return self._request("GET", path, params=params)

    def post(self, path: str, payload: dict[str, Any]) -> Any:
        return self._request("POST", path, payload=payload)

    def paginate(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        items_key: str | None = None,
    ) -> list[Any]:
        """Walk pages until a short page arrives or ``MAX_PAGES`` is reached."""
        results: list[Any] = []
        for page in range(1, MAX_PAGES + 1):
            page_params: dict[str, Any] = dict(
                params or {}, per_page=PAGE_SIZE, page=page
            )
            payload: Any = self.get(path, page_params)
            items: list[Any] = payload if items_key is None else payload[items_key]
            results.extend(items)
            if len(items) < PAGE_SIZE:
                break
        return results

    def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> Any:
        url: str = f"{self._api_root}/{path.lstrip('/')}"
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"
        body: bytes | None = None
        if payload is not None:
            body = json.dumps(payload).encode()

        request = urllib.request.Request(url, data=body, method=method)
        request.add_header("Accept", "application/vnd.github+json")
        request.add_header("X-GitHub-Api-Version", "2022-11-28")
        request.add_header("Authorization", f"Bearer {self._token}")
        if body is not None:
            request.add_header("Content-Type", "application/json")

        repeatable: bool = method in IDEMPOTENT_METHODS
        for attempt in range(1, MAX_ATTEMPTS + 1):
            last: bool = attempt == MAX_ATTEMPTS
            try:
                with urllib.request.urlopen(request, timeout=60) as response:
                    return json.loads(response.read() or b"null")
            except urllib.error.HTTPError as error:
                retry: bool = error.code in REJECTED_STATUS or (
                    repeatable and error.code in AMBIGUOUS_STATUS
                )
                if not retry or last:
                    detail: str = error.read().decode(errors="replace").strip()
                    raise GitHubError(
                        f"{method} {url} failed: {error.code} {detail}"
                    ) from error
            except urllib.error.URLError as error:
                if not repeatable or last:
                    raise GitHubError(
                        f"{method} {url} failed: {error.reason}"
                    ) from error
            time.sleep(RETRY_DELAY_SECONDS * attempt)

        raise GitHubError(f"{method} {url} failed after {MAX_ATTEMPTS} attempts")
