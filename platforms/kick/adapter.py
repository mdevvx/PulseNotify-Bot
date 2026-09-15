"""Kick Public API adapter — live/offline detection (Phase 6).

API research (2026-09-15), verified against Kick's current official
developer documentation (docs.kick.com), not scraped/undocumented
endpoints — see [[project-platform-api-policy]] / README.md for the
standing policy this follows:

| Feature                        | Method                                          | Auth              | Notes |
|----------------------------------|--------------------------------------------------|-------------------|-------|
| Live/offline + channel resolve  | GET /public/v1/channels?slug= or ?broadcaster_user_id= | app access token | No broadcaster authorization needed. One endpoint does both identifier resolution (validate_account) and live-status polling (get_live_status) — Kick's response already nests is_live/title/category/viewer_count/thumbnail/url per channel, unlike Twitch which needs two separate endpoints. Batches up to 50 IDs/call, but (like YouTube/Twitch) this adapter polls one account at a time to match the framework's per-account worker model. |

Kick's OAuth (id.kick.com/oauth/token) supports a client_credentials grant
producing an "App Access Token" explicitly documented as usable "when user
login is not required" for public data — the same model Twitch uses, and
for the same reason this adapter needs no per-streamer authorization.

No EventSub/webhook equivalent was evaluated for Kick this phase: Kick
does have a webhook system (docs.kick.com/events), but it has the same
"needs a public HTTPS callback endpoint" infrastructure requirement that
ruled out Twitch's EventSub webhooks (see platforms/twitch/adapter.py) —
and polling here is just as cheap (no documented rate limit anywhere near
restrictive for this bot's scale), so there's no pressure to build that
infrastructure for Kick specifically either. Revisit once a public
endpoint exists for some other platform that actually requires one.

Credentials: KICK_CLIENT_ID/KICK_CLIENT_SECRET, an app access token via
the OAuth client-credentials flow — no per-broadcaster authorization.

Kick's API doesn't expose a per-session stream ID the way YouTube's video
ID or Twitch's stream.id do — see platforms/kick/parser.py's docstring and
monitoring/worker.py's platform_event_id fallback for how that's handled
without silently deduplicating every live notification after the first.
"""

from __future__ import annotations

from typing import Any, ClassVar, FrozenSet, Optional

from events.models import NormalizedEvent
from platforms.base import AccountRef, Capability, FetchResult, LiveStatus, PlatformAdapter
from platforms.kick import parser
from platforms.kick.client import KickClient
from utils.errors import PermanentPlatformError


class KickAdapter(PlatformAdapter):
    platform: ClassVar[str] = "kick"
    capabilities: ClassVar[FrozenSet[Capability]] = frozenset({Capability.LIVE_STATUS})

    def __init__(self, client: KickClient) -> None:
        self._client = client

    async def aclose(self) -> None:
        await self._client.aclose()

    async def validate_account(self, identifier: str) -> AccountRef:
        slug = parser.parse_identifier(identifier)
        channel = await self._client.get_channel_by_slug(slug)
        if channel is None:
            raise PermanentPlatformError(f"No Kick channel found for {identifier!r}")
        return parser.channel_to_account_ref(channel)

    async def fetch_updates(self, account: AccountRef, cursor: Optional[str]) -> FetchResult:
        raise NotImplementedError("KickAdapter declares no content capability — the worker never calls this.")

    async def get_live_status(self, account: AccountRef) -> Optional[LiveStatus]:
        channel = await self._client.get_channel_by_id(account.platform_account_id)
        if channel is None:
            return LiveStatus(is_live=False)
        return parser.channel_to_live_status(channel)

    def normalize_event(self, account: AccountRef, raw_item: Any) -> NormalizedEvent:
        raise NotImplementedError("KickAdapter declares no content capability — the worker never calls this.")
