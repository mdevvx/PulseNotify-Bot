"""X (Twitter) API v2 adapter — new-post detection (Phase 7).

API research (2026-09-15), verified against X's current developer
documentation and pricing pages, not scraped/undocumented endpoints — see
[[project-platform-api-policy]] / README.md for the standing policy this
follows.

**This is the one platform in this project with a real, unavoidable
dollar cost — read this before enabling it.** X discontinued its free API
tier in February 2026. As of this research, reading posts is billed
pay-per-use (roughly $0.005 per post read, capped at 2,000,000 reads/month)
with no free allowance; a legacy fixed-price Basic plan ($200/month) still
exists but only for pre-existing subscribers, not new signups. There is no
way to use this adapter without a paid X API plan — setting
TWITTER_BEARER_TOKEN is an explicit opt-in to that cost, unlike every
other platform in this project (all free). Cost scales directly with how
many accounts you monitor and how often (MONITORING_CONTENT_POLL_INTERVAL_SECONDS)
— budget accordingly before adding accounts.

| Feature            | Method                                   | Cost/call         | Notes |
|----------------------|---------------------------------------------|--------------------|-------|
| Handle resolution    | GET /2/users/by/username/{username}         | billed as a read   | No target-account authorization needed — this reads public profile data. |
| New posts            | GET /2/users/{id}/tweets (since_id cursor)  | billed per post returned | Retweets/replies excluded to match POST_CREATED's semantics and to avoid paying to re-read content that isn't a new original post. Requests the API's minimum page size (5) per poll. |

Credentials: TWITTER_BEARER_TOKEN, a static app-only Bearer token
generated once in the X Developer Portal — no OAuth dance or per-account
authorization needed (this only ever reads public posts).

No adapter-level rate limiting is implemented beyond the framework's
generic per-platform RateLimiter (MONITORING_RATE_LIMIT_REQUESTS/
_PERIOD_SECONDS): unlike YouTube's hard daily quota wall, X's constraint
here is the operator's own budget, not a platform-side limit this code can
safely auto-throttle against without knowing that budget — see the cost
callout above instead.

Live status / Spaces detection was not evaluated this phase — the spec's
X/Twitter integration is about new-post alerts, matching what "post" means
for this platform.
"""

from __future__ import annotations

from typing import Any, ClassVar, FrozenSet, Optional

from events.models import NormalizedEvent
from platforms.base import AccountRef, Capability, FetchResult, LiveStatus, PlatformAdapter
from platforms.twitter import parser
from platforms.twitter.client import TwitterClient
from utils.errors import PermanentPlatformError

_PAGE_SIZE = 5  # the minimum X's API allows — no reason to pay for more per poll


class TwitterAdapter(PlatformAdapter):
    platform: ClassVar[str] = "twitter"
    capabilities: ClassVar[FrozenSet[Capability]] = frozenset({Capability.POSTS})

    def __init__(self, client: TwitterClient) -> None:
        self._client = client

    async def aclose(self) -> None:
        await self._client.aclose()

    async def validate_account(self, identifier: str) -> AccountRef:
        handle = parser.parse_identifier(identifier)
        user = await self._client.get_user_by_username(handle)
        if user is None:
            raise PermanentPlatformError(f"No X account found for {identifier!r}")
        return parser.user_to_account_ref(user)

    async def fetch_updates(self, account: AccountRef, cursor: Optional[str]) -> FetchResult:
        tweets = await self._client.get_user_tweets(account.platform_account_id, since_id=cursor, max_results=_PAGE_SIZE)
        if not tweets:
            return FetchResult(items=[], next_cursor=cursor)

        newest_id = tweets[0]["id"]  # newest-first, matching YouTube's uploads-playlist ordering
        if cursor is None:
            # First-ever poll for this account: establish a baseline
            # without notifying about (and paying to read, repeatedly,
            # were this not gated) the account's entire recent history.
            return FetchResult(items=[], next_cursor=newest_id)

        return FetchResult(items=tweets, next_cursor=newest_id)

    async def get_live_status(self, account: AccountRef) -> Optional[LiveStatus]:
        raise NotImplementedError("TwitterAdapter declares no live-status capability — the worker never calls this.")

    def normalize_event(self, account: AccountRef, raw_item: Any) -> NormalizedEvent:
        return parser.normalize_tweet(account, raw_item)
