"""TwitterClient's error classification (status code -> the right
PlatformError subclass), driven through httpx.MockTransport so no real
network call is ever made."""

from __future__ import annotations

import json
import time

import httpx
import pytest

from platforms.twitter.client import TwitterClient
from utils.errors import PermanentPlatformError, RateLimitedError, TransientPlatformError


def _client_with(handler) -> TwitterClient:
    return TwitterClient("fake-bearer-token", transport=httpx.MockTransport(handler))


def _json_response(status: int, body: dict, headers: dict | None = None) -> httpx.Response:
    return httpx.Response(status, content=json.dumps(body), headers=headers or {})


async def test_get_user_by_username_returns_the_user() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _json_response(200, {"data": {"id": "123", "username": "someuser"}})

    client = _client_with(handler)
    user = await client.get_user_by_username("someuser")

    assert user == {"id": "123", "username": "someuser"}


async def test_get_user_by_username_returns_none_when_not_found() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _json_response(200, {"errors": [{"title": "Not Found Error"}]})

    client = _client_with(handler)
    user = await client.get_user_by_username("nonexistent")

    assert user is None


async def test_request_sends_bearer_token_header() -> None:
    seen_headers = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen_headers.update(dict(request.headers))
        return _json_response(200, {"data": {"id": "1"}})

    client = _client_with(handler)
    await client.get_user_by_username("someuser")

    assert seen_headers["authorization"] == "Bearer fake-bearer-token"


async def test_get_user_tweets_returns_the_list() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _json_response(200, {"data": [{"id": "2"}, {"id": "1"}]})

    client = _client_with(handler)
    tweets = await client.get_user_tweets("123")

    assert tweets == [{"id": "2"}, {"id": "1"}]


async def test_get_user_tweets_returns_empty_list_when_no_data() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _json_response(200, {"meta": {"result_count": 0}})

    client = _client_with(handler)
    tweets = await client.get_user_tweets("123")

    assert tweets == []


async def test_get_user_tweets_sends_since_id_and_excludes_retweets_and_replies() -> None:
    seen_params = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen_params.update(dict(request.url.params))
        return _json_response(200, {"data": []})

    client = _client_with(handler)
    await client.get_user_tweets("123", since_id="999")

    assert seen_params["since_id"] == "999"
    assert seen_params["exclude"] == "retweets,replies"


async def test_get_user_tweets_omits_since_id_on_first_poll() -> None:
    seen_params = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen_params.update(dict(request.url.params))
        return _json_response(200, {"data": []})

    client = _client_with(handler)
    await client.get_user_tweets("123", since_id=None)

    assert "since_id" not in seen_params


async def test_rate_limited_raises_with_retry_after_from_reset_header() -> None:
    reset_at = int(time.time()) + 45

    def handler(request: httpx.Request) -> httpx.Response:
        return _json_response(429, {"title": "Too Many Requests"}, headers={"x-rate-limit-reset": str(reset_at)})

    client = _client_with(handler)
    with pytest.raises(RateLimitedError) as exc_info:
        await client.get_user_by_username("someuser")

    assert exc_info.value.retry_after is not None
    assert 0 < exc_info.value.retry_after <= 45


async def test_rate_limited_without_reset_header_falls_back_to_a_default_wait() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _json_response(429, {"title": "Too Many Requests"})

    client = _client_with(handler)
    with pytest.raises(RateLimitedError) as exc_info:
        await client.get_user_by_username("someuser")

    assert exc_info.value.retry_after is not None


async def test_bad_request_raises_permanent_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _json_response(400, {"title": "Invalid Request", "detail": "bad params"})

    client = _client_with(handler)
    with pytest.raises(PermanentPlatformError):
        await client.get_user_by_username("not valid")


async def test_unauthorized_raises_transient_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _json_response(401, {"title": "Unauthorized"})

    client = _client_with(handler)
    with pytest.raises(TransientPlatformError):
        await client.get_user_by_username("someuser")


async def test_not_found_status_raises_permanent_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _json_response(404, {"title": "Not Found Error"})

    client = _client_with(handler)
    with pytest.raises(PermanentPlatformError):
        await client.get_user_by_username("someuser")


async def test_server_error_raises_transient_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, content="internal error")

    client = _client_with(handler)
    with pytest.raises(TransientPlatformError):
        await client.get_user_by_username("someuser")


async def test_timeout_raises_transient_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out", request=request)

    client = _client_with(handler)
    with pytest.raises(TransientPlatformError):
        await client.get_user_by_username("someuser")
