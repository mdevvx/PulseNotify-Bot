"""Thin async HTTP client for the X (Twitter) API v2 calls this adapter
uses. Authenticates with a static app-only Bearer token — see
platforms/twitter/adapter.py's module docstring for why that's the right
credential type here, and the real per-read cost of using it at all.

Unlike TwitchClient/KickClient, there's no token-fetch/refresh dance: the
Bearer token is a long-lived credential the operator generates once in the
X Developer Portal and pastes into .env, the same operational model as
YouTube's API key.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

import httpx

from utils.errors import PermanentPlatformError, RateLimitedError, TransientPlatformError

_BASE_URL = "https://api.x.com/2"
# X doesn't send Retry-After on 429 — only x-rate-limit-reset (a unix
# timestamp for the current window's reset, mirroring Twitch's
# Ratelimit-Reset). Fall back to this if the header is somehow missing.
_DEFAULT_RATE_LIMIT_WAIT_SECONDS = 60.0


class TwitterClient:
    def __init__(
        self,
        bearer_token: str,
        *,
        timeout_seconds: float = 15.0,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ) -> None:
        """`transport` is exposed purely for tests (httpx.MockTransport) to
        drive this client's error-classification logic without a real
        network call — production code never passes it."""
        self._bearer_token = bearer_token
        self._http = httpx.AsyncClient(base_url=_BASE_URL, timeout=timeout_seconds, transport=transport)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def get_user_by_username(self, username: str) -> Optional[Dict[str, Any]]:
        data = await self._get(f"/users/by/username/{username}")
        return data.get("data")

    async def get_user_tweets(
        self, user_id: str, *, since_id: Optional[str] = None, max_results: int = 5
    ) -> List[Dict[str, Any]]:
        """Newest-first, original posts only (retweets/replies excluded —
        both to match POST_CREATED's semantics and to minimize billed
        reads). `max_results=5` is the minimum X's API allows; there's no
        reason to request more per poll than this bot needs to catch up
        since the last cursor."""
        params: Dict[str, Any] = {
            "exclude": "retweets,replies",
            "tweet.fields": "created_at",
            "max_results": max_results,
        }
        if since_id:
            params["since_id"] = since_id

        data = await self._get(f"/users/{user_id}/tweets", params)
        return data.get("data", [])

    async def _get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        headers = {"Authorization": f"Bearer {self._bearer_token}"}
        try:
            response = await self._http.get(path, params=params, headers=headers)
        except httpx.TimeoutException as exc:
            raise TransientPlatformError(f"X API request timed out: {path}") from exc
        except httpx.HTTPError as exc:
            raise TransientPlatformError(f"X API request failed: {path}: {exc}") from exc

        if response.status_code == 200:
            return response.json()

        self._raise_for_error(response)
        raise AssertionError("unreachable")  # _raise_for_error always raises

    def _raise_for_error(self, response: httpx.Response) -> None:
        message = response.text
        try:
            body = response.json()
            message = body.get("detail") or body.get("title") or message
        except ValueError:
            pass  # non-JSON error body; fall back to the raw text already set above

        if response.status_code == 429:
            raise RateLimitedError(
                f"X API rate limited: {message}",
                retry_after=_seconds_until_reset(response.headers.get("x-rate-limit-reset")),
            )

        if response.status_code == 400:
            raise PermanentPlatformError(f"X API rejected the request: {message}")

        if response.status_code in {401, 403}:
            # Auth/permission trouble (bad/expired bearer token) rather
            # than a bad request for a specific account — a configuration
            # problem, not evidence this specific account is invalid. Same
            # reasoning as YouTubeClient's/TwitchClient's 401/403 handling.
            raise TransientPlatformError(f"X API auth/permission error ({response.status_code}): {message}")

        if response.status_code == 404:
            raise PermanentPlatformError(f"X resource not found: {message}")

        raise TransientPlatformError(f"X API error {response.status_code}: {message}")


def _seconds_until_reset(value: Optional[str]) -> float:
    if not value:
        return _DEFAULT_RATE_LIMIT_WAIT_SECONDS
    try:
        reset_at = float(value)
    except ValueError:
        return _DEFAULT_RATE_LIMIT_WAIT_SECONDS
    return max(reset_at - time.time(), 0.0)
