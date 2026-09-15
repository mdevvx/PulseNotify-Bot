"""Instagram Graph API adapter — new-post detection via "Business
Discovery" (Phase 7).

API research (2026-09-15), verified against Meta's current developer
documentation, not scraped/undocumented endpoints — see
[[project-platform-api-policy]] / README.md for the standing policy this
follows.

**Read this before enabling it — this platform has real setup and policy
constraints, not just an API key to paste in.** As of 2026, Meta's
official APIs do not allow discovering or reading an arbitrary Instagram
account's content the way YouTube/Twitch/Kick's app-token model does.
There is exactly one officially-supported path that doesn't require the
*target* account's cooperation: Business Discovery.

| Feature                | Method                                                     | Auth                                   | Notes |
|--------------------------|----------------------------------------------------------------|------------------------------------------|-------|
| Profile + recent media   | GET /{your_ig_user_id}?fields=business_discovery.username(...) | Long-lived access token for YOUR OWN linked IG professional account | No authorization from the *target* account needed — but see the constraints below. |

Constraints that make this meaningfully different from every other
adapter in this project:
1. **The target must itself be a Business or Creator account.** A regular
   personal Instagram account cannot be monitored this way at all — there
   is no official API for that (confirmed: Meta closed general
   public-account discovery in 2020). Not a heuristic gap like YouTube's
   Shorts detection — a hard capability boundary.
2. **The operator needs their own qualifying setup**: a Meta Developer
   app, with a Facebook Page connected to their own Instagram
   Business/Creator account, providing the access token and IG user ID
   this adapter authenticates as.
3. **Meta App Review is required before this works against arbitrary
   accounts.** In Development mode, Business Discovery only succeeds
   against accounts added as testers on the operator's own app — i.e. it
   cannot monitor an arbitrary creator until the app has passed Review for
   the relevant permission. This is a real approval process on Meta's
   side, not something this codebase can shortcut.
4. **Lookup is by username only** — there is no by-ID variant of Business
   Discovery. If a monitored account renames its handle, this adapter's
   next poll fails (see platforms/instagram/parser.py's docstring); the
   account must be removed and re-added under the new handle.
5. **No webhook exists for this** (Instagram's webhook system only
   delivers events for accounts *your own app manages*, never for a
   Business-Discovery-only target) — this is a straightforward poll, not
   a case where a push alternative was evaluated and rejected the way
   Twitch/Kick's EventSub was.

Credentials: INSTAGRAM_ACCESS_TOKEN (a long-lived token for the
operator's own linked account) + INSTAGRAM_BUSINESS_ACCOUNT_ID (that
account's own IG user ID). Renewed manually roughly every 60 days — no
in-app OAuth refresh flow is implemented, the same operational trade-off
as YouTube's static API key.
"""

from __future__ import annotations

from typing import Any, ClassVar, FrozenSet, Optional

from events.models import NormalizedEvent
from platforms.base import AccountRef, Capability, FetchResult, LiveStatus, PlatformAdapter
from platforms.instagram import parser
from platforms.instagram.client import InstagramClient
from utils.errors import PermanentPlatformError


class InstagramAdapter(PlatformAdapter):
    platform: ClassVar[str] = "instagram"
    capabilities: ClassVar[FrozenSet[Capability]] = frozenset({Capability.POSTS})

    def __init__(self, client: InstagramClient) -> None:
        self._client = client

    async def aclose(self) -> None:
        await self._client.aclose()

    async def validate_account(self, identifier: str) -> AccountRef:
        username = parser.parse_identifier(identifier)
        discovery = await self._client.get_business_discovery(username)
        if discovery is None:
            raise PermanentPlatformError(
                f"No Instagram Business/Creator account found for {identifier!r} — personal accounts and "
                "unapproved-for-review targets can't be monitored via Business Discovery (see README)."
            )
        return parser.discovery_to_account_ref(discovery)

    async def fetch_updates(self, account: AccountRef, cursor: Optional[str]) -> FetchResult:
        # Business Discovery has no by-ID lookup — account.username (not
        # platform_account_id) is the actual query key on every poll.
        discovery = await self._client.get_business_discovery(account.username)
        if discovery is None:
            raise PermanentPlatformError(
                f"Instagram account {account.username!r} no longer resolves via Business Discovery "
                "(renamed, deleted, no longer a professional account, or no longer approved for this app)."
            )

        media_items = discovery.get("media", [])
        if not media_items:
            return FetchResult(items=[], next_cursor=cursor)

        newest_id = media_items[0]["id"]  # newest-first, matching the API's documented default ordering
        if cursor is None:
            # First-ever poll for this account: establish a baseline
            # without notifying about its entire existing post history.
            return FetchResult(items=[], next_cursor=newest_id)

        new_items = []
        for item in media_items:
            if item["id"] == cursor:
                break
            new_items.append(item)

        if not new_items:
            return FetchResult(items=[], next_cursor=newest_id)

        return FetchResult(items=list(reversed(new_items)), next_cursor=newest_id)

    async def get_live_status(self, account: AccountRef) -> Optional[LiveStatus]:
        raise NotImplementedError("InstagramAdapter declares no live-status capability — the worker never calls this.")

    def normalize_event(self, account: AccountRef, raw_item: Any) -> NormalizedEvent:
        return parser.normalize_media(account, raw_item)
