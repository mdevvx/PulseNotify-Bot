"""TwitterAdapter's own logic — the cursor/baseline behavior for
fetch_updates (mirrors YouTubeAdapter's, since both are since-cursor
content polls), driven through a fake TwitterClient (not real HTTP;
that's covered separately in test_twitter_client.py)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest

from platforms.base import AccountRef
from platforms.twitter.adapter import TwitterAdapter
from utils.errors import PermanentPlatformError

_ACCOUNT = AccountRef(platform="twitter", platform_account_id="123", username="Some User")


def _tweet(tweet_id: str) -> Dict[str, Any]:
    return {"id": tweet_id, "text": f"tweet {tweet_id}"}


class FakeTwitterClient:
    def __init__(self) -> None:
        self.user: Optional[Dict[str, Any]] = {"id": "123", "username": "someuser", "name": "Some User"}
        self.tweets_by_since_id: Dict[Optional[str], List[Dict[str, Any]]] = {}
        self.get_user_tweets_calls = 0

    async def get_user_by_username(self, username: str):
        return self.user

    async def get_user_tweets(self, user_id: str, *, since_id=None, max_results: int = 5):
        self.get_user_tweets_calls += 1
        return self.tweets_by_since_id.get(since_id, [])

    async def aclose(self) -> None:
        pass


async def test_validate_account_resolves_a_handle_to_an_account_ref() -> None:
    client = FakeTwitterClient()
    adapter = TwitterAdapter(client)  # type: ignore[arg-type]

    ref = await adapter.validate_account("@SomeUser")

    assert ref.platform == "twitter"
    assert ref.platform_account_id == "123"
    assert ref.username == "Some User"


async def test_validate_account_raises_permanent_error_when_not_found() -> None:
    client = FakeTwitterClient()
    client.user = None
    adapter = TwitterAdapter(client)  # type: ignore[arg-type]

    with pytest.raises(PermanentPlatformError):
        await adapter.validate_account("nonexistent")


async def test_first_poll_establishes_a_baseline_without_emitting_events() -> None:
    client = FakeTwitterClient()
    client.tweets_by_since_id[None] = [_tweet("3"), _tweet("2"), _tweet("1")]
    adapter = TwitterAdapter(client)  # type: ignore[arg-type]

    result = await adapter.fetch_updates(_ACCOUNT, cursor=None)

    assert result.items == []
    assert result.next_cursor == "3"


async def test_subsequent_poll_returns_new_tweets_and_advances_cursor() -> None:
    client = FakeTwitterClient()
    client.tweets_by_since_id["1"] = [_tweet("3"), _tweet("2")]
    adapter = TwitterAdapter(client)  # type: ignore[arg-type]

    result = await adapter.fetch_updates(_ACCOUNT, cursor="1")

    assert {t["id"] for t in result.items} == {"2", "3"}
    assert result.next_cursor == "3"


async def test_no_new_tweets_returns_empty_and_keeps_the_cursor() -> None:
    client = FakeTwitterClient()
    client.tweets_by_since_id["1"] = []
    adapter = TwitterAdapter(client)  # type: ignore[arg-type]

    result = await adapter.fetch_updates(_ACCOUNT, cursor="1")

    assert result.items == []
    assert result.next_cursor == "1"


async def test_get_live_status_is_never_expected_to_be_called() -> None:
    client = FakeTwitterClient()
    adapter = TwitterAdapter(client)  # type: ignore[arg-type]

    with pytest.raises(NotImplementedError):
        await adapter.get_live_status(_ACCOUNT)
