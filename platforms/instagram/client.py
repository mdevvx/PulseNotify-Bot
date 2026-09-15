"""Thin async HTTP client for the Instagram Graph API "Business Discovery"
call this adapter uses. Authenticates with a long-lived access token
belonging to the bot operator's OWN connected Instagram professional
account — see platforms/instagram/adapter.py's module docstring for why
that's the credential this needs, and what it can/can't monitor.

No token-fetch/refresh dance here: unlike TwitchClient/KickClient's
client-credentials flow, this token is a long-lived (about 60 days)
credential the operator generates via Meta's tools and renews manually —
the same operational model as X's Bearer token.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

import httpx

from utils.errors import PermanentPlatformError, RateLimitedError, TransientPlatformError

_BASE_URL = "https://graph.facebook.com/v25.0"
# How many of the target's most recent media items to fetch per call —
# only enough to catch up since the last cursor, matching the "small page
# size per poll" pattern used by the YouTube/X adapters.
_MEDIA_PAGE_SIZE = 5
# Meta's Graph API doesn't document a simple Retry-After-style header for
# this call shape — fall back to a fixed, generous wait on a 429.
_DEFAULT_RATE_LIMIT_WAIT_SECONDS = 60.0


class InstagramClient:
    def __init__(
        self,
        access_token: str,
        business_account_id: str,
        *,
        timeout_seconds: float = 15.0,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ) -> None:
        """`transport` is exposed purely for tests (httpx.MockTransport) to
        drive this client's error-classification logic without a real
        network call — production code never passes it. `business_account_id`
        is the operator's OWN Instagram professional account's IG user ID —
        Business Discovery is queried as "my account, looking up someone
        else's public data," not with the target's own ID."""
        self._access_token = access_token
        self._business_account_id = business_account_id
        self._http = httpx.AsyncClient(base_url=_BASE_URL, timeout=timeout_seconds, transport=transport)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def get_business_discovery(self, username: str) -> Optional[Dict[str, Any]]:
        """Looks up another Business/Creator account's public profile +
        recent media by username — no authorization from that account is
        needed, only that this client's own linked account (and the Meta
        app behind it) has App Review approval for this feature (see
        platforms/instagram/adapter.py). Returns None if the target
        doesn't resolve (wrong username, not a professional account, or
        this app hasn't been approved to query accounts beyond its own
        testers)."""
        fields = (
            f"business_discovery.username({username})"
            f"{{id,username,name,media.limit({_MEDIA_PAGE_SIZE})"
            f"{{id,caption,timestamp,media_type,media_url,permalink}}}}"
        )
        data = await self._get(f"/{self._business_account_id}", {"fields": fields})
        discovery = data.get("business_discovery")
        if discovery is None:
            return None

        media_items: List[Dict[str, Any]] = discovery.get("media", {}).get("data", [])
        return {**discovery, "media": media_items}

    async def _get(self, path: str, params: Dict[str, Any]) -> Dict[str, Any]:
        request_params = {**params, "access_token": self._access_token}
        try:
            response = await self._http.get(path, params=request_params)
        except httpx.TimeoutException as exc:
            raise TransientPlatformError(f"Instagram API request timed out: {path}") from exc
        except httpx.HTTPError as exc:
            raise TransientPlatformError(f"Instagram API request failed: {path}: {exc}") from exc

        if response.status_code == 200:
            return response.json()

        self._raise_for_error(response)
        raise AssertionError("unreachable")  # _raise_for_error always raises

    def _raise_for_error(self, response: httpx.Response) -> None:
        message = response.text
        try:
            body = response.json()
            message = body.get("error", {}).get("message", message)
        except ValueError:
            pass  # non-JSON error body; fall back to the raw text already set above

        if response.status_code == 429:
            raise RateLimitedError(f"Instagram API rate limited: {message}", retry_after=_DEFAULT_RATE_LIMIT_WAIT_SECONDS)

        if response.status_code == 400:
            # Graph API returns 400 for "no such account," "not a
            # professional account," and "this app isn't approved to
            # query accounts beyond its own testers" alike — all
            # non-retryable from this bot's perspective.
            raise PermanentPlatformError(f"Instagram API rejected the request: {message}")

        if response.status_code in {401, 403}:
            # Auth/permission trouble (expired/invalid access token)
            # rather than a bad request for a specific account — a
            # configuration problem, not evidence this specific account is
            # invalid. Same reasoning as the other clients' 401/403
            # handling.
            raise TransientPlatformError(f"Instagram API auth/permission error ({response.status_code}): {message}")

        if response.status_code == 404:
            raise PermanentPlatformError(f"Instagram resource not found: {message}")

        raise TransientPlatformError(f"Instagram API error {response.status_code}: {message}")
