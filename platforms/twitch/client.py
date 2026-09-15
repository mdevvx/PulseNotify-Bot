"""Thin async HTTP client for the Twitch Helix API calls this adapter uses.

Authenticates with an app access token (OAuth client-credentials grant) —
see platforms/twitch/adapter.py's module docstring for why that's enough
for every call made here (stream/channel lookups require no broadcaster
authorization). The token is fetched lazily on first use, cached until
shortly before its reported expiry, and force-refreshed once if a Helix
call unexpectedly 401s (e.g. the app's client secret was regenerated in
the Twitch dev console).
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional

import httpx

from utils.errors import PermanentPlatformError, RateLimitedError, TransientPlatformError
from utils.logger import get_logger

logger = get_logger(__name__)

_AUTH_URL = "https://id.twitch.tv/oauth2/token"
_BASE_URL = "https://api.twitch.tv/helix"

# Refresh this many seconds before the token's reported expiry, so an
# in-flight request never races the exact expiry instant.
_TOKEN_REFRESH_MARGIN_SECONDS = 60.0
# Twitch doesn't send a Retry-After on 429 — only Ratelimit-Reset (a unix
# timestamp for when the bucket refills, see _seconds_until_reset). Fall
# back to this if the header is somehow missing.
_DEFAULT_RATE_LIMIT_WAIT_SECONDS = 60.0


class TwitchClient:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        *,
        timeout_seconds: float = 15.0,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ) -> None:
        """`transport` is exposed purely for tests (httpx.MockTransport) to
        drive this client's error-classification/token logic without a
        real network call — production code never passes it. No base_url
        is set (unlike YouTubeClient) since this client talks to two hosts
        (api.twitch.tv and id.twitch.tv): full URLs are passed to every
        request instead."""
        self._client_id = client_id
        self._client_secret = client_secret
        self._http = httpx.AsyncClient(timeout=timeout_seconds, transport=transport)
        self._access_token: Optional[str] = None
        self._token_expires_at: float = 0.0

    async def aclose(self) -> None:
        await self._http.aclose()

    async def get_user(self, *, login: Optional[str] = None, user_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        params: Dict[str, Any] = {}
        if login:
            params["login"] = login
        elif user_id:
            params["id"] = user_id
        else:
            raise ValueError("Provide one of login or user_id")

        data = await self._get("/users", params)
        items = data.get("data", [])
        return items[0] if items else None

    async def get_stream(self, user_id: str) -> Optional[Dict[str, Any]]:
        """None means offline — Twitch just omits offline channels from the
        response entirely rather than returning an explicit status."""
        data = await self._get("/streams", {"user_id": user_id})
        items = data.get("data", [])
        return items[0] if items else None

    async def _get(self, path: str, params: Dict[str, Any], *, _retried: bool = False) -> Dict[str, Any]:
        await self._ensure_token()
        headers = {"Client-Id": self._client_id, "Authorization": f"Bearer {self._access_token}"}
        try:
            response = await self._http.get(f"{_BASE_URL}{path}", params=params, headers=headers)
        except httpx.TimeoutException as exc:
            raise TransientPlatformError(f"Twitch API request timed out: {path}") from exc
        except httpx.HTTPError as exc:
            raise TransientPlatformError(f"Twitch API request failed: {path}: {exc}") from exc

        if response.status_code == 200:
            return response.json()

        if response.status_code == 401 and not _retried:
            # Our cached token looked valid but Twitch rejected it anyway —
            # force one refresh and retry before giving up.
            logger.info("Twitch API returned 401 with a cached token — forcing a refresh and retrying once.")
            self._access_token = None
            return await self._get(path, params, _retried=True)

        self._raise_for_error(response)
        raise AssertionError("unreachable")  # _raise_for_error always raises

    async def _ensure_token(self) -> None:
        if self._access_token is not None and time.monotonic() < self._token_expires_at:
            return

        try:
            response = await self._http.post(
                _AUTH_URL,
                data={
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "grant_type": "client_credentials",
                },
            )
        except httpx.TimeoutException as exc:
            raise TransientPlatformError("Twitch OAuth token request timed out") from exc
        except httpx.HTTPError as exc:
            raise TransientPlatformError(f"Twitch OAuth token request failed: {exc}") from exc

        if response.status_code != 200:
            raise TransientPlatformError(
                f"Twitch OAuth token request failed ({response.status_code}): {response.text}"
            )

        body = response.json()
        self._access_token = body["access_token"]
        expires_in = body.get("expires_in", 3600)
        self._token_expires_at = time.monotonic() + max(expires_in - _TOKEN_REFRESH_MARGIN_SECONDS, 0)

    def _raise_for_error(self, response: httpx.Response) -> None:
        message = response.text
        try:
            body = response.json()
            message = body.get("message", message)
        except ValueError:
            pass  # non-JSON error body; fall back to the raw text already set above

        if response.status_code == 429:
            raise RateLimitedError(
                f"Twitch API rate limited: {message}",
                retry_after=_seconds_until_reset(response.headers.get("Ratelimit-Reset")),
            )

        if response.status_code == 400:
            raise PermanentPlatformError(f"Twitch API rejected the request: {message}")

        if response.status_code in {401, 403}:
            # Auth/permission trouble (bad client id/secret) rather than a
            # bad request for a specific account — a configuration problem,
            # not evidence this specific account is invalid. Same reasoning
            # as YouTubeClient's 401/403 handling.
            raise TransientPlatformError(f"Twitch API auth/permission error ({response.status_code}): {message}")

        if response.status_code == 404:
            raise PermanentPlatformError(f"Twitch resource not found: {message}")

        raise TransientPlatformError(f"Twitch API error {response.status_code}: {message}")


def _seconds_until_reset(value: Optional[str]) -> float:
    if not value:
        return _DEFAULT_RATE_LIMIT_WAIT_SECONDS
    try:
        reset_at = float(value)
    except ValueError:
        return _DEFAULT_RATE_LIMIT_WAIT_SECONDS
    return max(reset_at - time.time(), 0.0)
