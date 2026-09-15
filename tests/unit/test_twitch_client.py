"""TwitchClient's token handling and error classification (status
code -> the right PlatformError subclass), driven through
httpx.MockTransport so no real network call is ever made."""

from __future__ import annotations

import json
import time

import httpx
import pytest

from platforms.twitch.client import TwitchClient
from utils.errors import PermanentPlatformError, RateLimitedError, TransientPlatformError


def _client_with(handler) -> TwitchClient:
    return TwitchClient("fake-client-id", "fake-client-secret", transport=httpx.MockTransport(handler))


def _json_response(status: int, body: dict, headers: dict | None = None) -> httpx.Response:
    return httpx.Response(status, content=json.dumps(body), headers=headers or {})


def _token_response(*, access_token: str = "test-token", expires_in: int = 3600) -> httpx.Response:
    return _json_response(200, {"access_token": access_token, "expires_in": expires_in, "token_type": "bearer"})


def _is_auth_request(request: httpx.Request) -> bool:
    return request.url.host == "id.twitch.tv"


async def test_get_user_returns_first_matching_user() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if _is_auth_request(request):
            return _token_response()
        return _json_response(200, {"data": [{"id": "123", "login": "somestreamer"}]})

    client = _client_with(handler)
    user = await client.get_user(login="somestreamer")

    assert user == {"id": "123", "login": "somestreamer"}


async def test_get_user_returns_none_when_no_data() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if _is_auth_request(request):
            return _token_response()
        return _json_response(200, {"data": []})

    client = _client_with(handler)
    user = await client.get_user(login="nonexistent")

    assert user is None


async def test_get_user_requires_login_or_user_id() -> None:
    client = _client_with(lambda request: _token_response())
    with pytest.raises(ValueError):
        await client.get_user()


async def test_get_stream_returns_none_when_offline() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if _is_auth_request(request):
            return _token_response()
        return _json_response(200, {"data": []})

    client = _client_with(handler)
    stream = await client.get_stream("123")

    assert stream is None


async def test_get_stream_returns_the_stream_when_live() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if _is_auth_request(request):
            return _token_response()
        return _json_response(200, {"data": [{"id": "s1", "user_id": "123"}]})

    client = _client_with(handler)
    stream = await client.get_stream("123")

    assert stream == {"id": "s1", "user_id": "123"}


async def test_token_is_fetched_once_and_reused_across_calls() -> None:
    auth_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal auth_calls
        if _is_auth_request(request):
            auth_calls += 1
            return _token_response()
        return _json_response(200, {"data": []})

    client = _client_with(handler)
    await client.get_stream("1")
    await client.get_stream("2")
    await client.get_stream("3")

    assert auth_calls == 1


async def test_token_sends_client_credentials_grant() -> None:
    seen_body = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if _is_auth_request(request):
            seen_body.update(dict(httpx.QueryParams(request.content.decode())))
            return _token_response()
        return _json_response(200, {"data": []})

    client = _client_with(handler)
    await client.get_stream("1")

    assert seen_body["client_id"] == "fake-client-id"
    assert seen_body["client_secret"] == "fake-client-secret"
    assert seen_body["grant_type"] == "client_credentials"


async def test_helix_request_sends_client_id_and_bearer_token_headers() -> None:
    seen_headers = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if _is_auth_request(request):
            return _token_response(access_token="abc123")
        seen_headers.update(dict(request.headers))
        return _json_response(200, {"data": []})

    client = _client_with(handler)
    await client.get_stream("1")

    assert seen_headers["client-id"] == "fake-client-id"
    assert seen_headers["authorization"] == "Bearer abc123"


async def test_token_is_refreshed_once_it_expires() -> None:
    auth_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal auth_calls
        if _is_auth_request(request):
            auth_calls += 1
            # expires_in=0 (clamped) means the token is treated as already
            # due for refresh by the very next call, without needing to
            # fake the passage of time.
            return _token_response(expires_in=0)
        return _json_response(200, {"data": []})

    client = _client_with(handler)
    await client.get_stream("1")
    await client.get_stream("2")

    assert auth_calls == 2


async def test_unexpected_401_forces_a_token_refresh_and_retries_once() -> None:
    auth_calls = 0
    stream_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal auth_calls, stream_calls
        if _is_auth_request(request):
            auth_calls += 1
            return _token_response()
        stream_calls += 1
        if stream_calls == 1:
            return _json_response(401, {"message": "invalid access token"})
        return _json_response(200, {"data": []})

    client = _client_with(handler)
    result = await client.get_stream("123")

    assert result is None
    assert auth_calls == 2  # initial fetch + forced refresh after the 401
    assert stream_calls == 2


async def test_persistent_401_after_retry_raises_transient_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if _is_auth_request(request):
            return _token_response()
        return _json_response(401, {"message": "invalid access token"})

    client = _client_with(handler)
    with pytest.raises(TransientPlatformError):
        await client.get_stream("123")


async def test_oauth_token_endpoint_failure_raises_transient_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if _is_auth_request(request):
            return httpx.Response(500, content="internal error")
        return _json_response(200, {"data": []})

    client = _client_with(handler)
    with pytest.raises(TransientPlatformError):
        await client.get_stream("123")


async def test_rate_limited_raises_with_retry_after_from_reset_header() -> None:
    reset_at = int(time.time()) + 45

    def handler(request: httpx.Request) -> httpx.Response:
        if _is_auth_request(request):
            return _token_response()
        return _json_response(
            429, {"message": "rate limited"}, headers={"Ratelimit-Reset": str(reset_at)}
        )

    client = _client_with(handler)
    with pytest.raises(RateLimitedError) as exc_info:
        await client.get_stream("123")

    assert exc_info.value.retry_after is not None
    assert 0 < exc_info.value.retry_after <= 45


async def test_rate_limited_without_reset_header_falls_back_to_a_default_wait() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if _is_auth_request(request):
            return _token_response()
        return _json_response(429, {"message": "rate limited"})

    client = _client_with(handler)
    with pytest.raises(RateLimitedError) as exc_info:
        await client.get_stream("123")

    assert exc_info.value.retry_after is not None


async def test_bad_request_raises_permanent_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if _is_auth_request(request):
            return _token_response()
        return _json_response(400, {"message": "invalid user_id"})

    client = _client_with(handler)
    with pytest.raises(PermanentPlatformError):
        await client.get_stream("not-a-valid-id")


async def test_not_found_raises_permanent_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if _is_auth_request(request):
            return _token_response()
        return _json_response(404, {"message": "not found"})

    client = _client_with(handler)
    with pytest.raises(PermanentPlatformError):
        await client.get_stream("123")


async def test_server_error_raises_transient_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if _is_auth_request(request):
            return _token_response()
        return httpx.Response(500, content="internal error")

    client = _client_with(handler)
    with pytest.raises(TransientPlatformError):
        await client.get_stream("123")


async def test_timeout_raises_transient_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if _is_auth_request(request):
            return _token_response()
        raise httpx.ConnectTimeout("timed out", request=request)

    client = _client_with(handler)
    with pytest.raises(TransientPlatformError):
        await client.get_stream("123")
