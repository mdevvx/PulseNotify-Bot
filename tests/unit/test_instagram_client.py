"""InstagramClient's error classification (status code -> the right
PlatformError subclass) and business_discovery response unwrapping,
driven through httpx.MockTransport so no real network call is ever made."""

from __future__ import annotations

import json

import httpx
import pytest

from platforms.instagram.client import InstagramClient
from utils.errors import PermanentPlatformError, RateLimitedError, TransientPlatformError


def _client_with(handler) -> InstagramClient:
    return InstagramClient("fake-token", "17800000000000000", transport=httpx.MockTransport(handler))


def _json_response(status: int, body: dict) -> httpx.Response:
    return httpx.Response(status, content=json.dumps(body))


async def test_get_business_discovery_unwraps_the_nested_media_edge() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _json_response(
            200,
            {
                "business_discovery": {
                    "id": "17841400",
                    "username": "somecreator",
                    "media": {"data": [{"id": "1"}, {"id": "2"}], "paging": {}},
                },
                "id": "17800000000000000",
            },
        )

    client = _client_with(handler)
    discovery = await client.get_business_discovery("somecreator")

    assert discovery is not None
    assert discovery["username"] == "somecreator"
    assert discovery["media"] == [{"id": "1"}, {"id": "2"}]


async def test_get_business_discovery_returns_none_when_field_absent() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _json_response(200, {"id": "17800000000000000"})

    client = _client_with(handler)
    discovery = await client.get_business_discovery("somecreator")

    assert discovery is None


async def test_request_sends_access_token_and_fields_params() -> None:
    seen_params = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen_params.update(dict(request.url.params))
        return _json_response(200, {"business_discovery": {"id": "1", "media": {"data": []}}})

    client = _client_with(handler)
    await client.get_business_discovery("somecreator")

    assert seen_params["access_token"] == "fake-token"
    assert "business_discovery.username(somecreator)" in seen_params["fields"]


async def test_bad_request_raises_permanent_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _json_response(400, {"error": {"message": "Unsupported get request."}})

    client = _client_with(handler)
    with pytest.raises(PermanentPlatformError):
        await client.get_business_discovery("nonexistent")


async def test_auth_error_raises_transient_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _json_response(401, {"error": {"message": "Invalid OAuth access token."}})

    client = _client_with(handler)
    with pytest.raises(TransientPlatformError):
        await client.get_business_discovery("somecreator")


async def test_not_found_raises_permanent_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _json_response(404, {"error": {"message": "not found"}})

    client = _client_with(handler)
    with pytest.raises(PermanentPlatformError):
        await client.get_business_discovery("somecreator")


async def test_rate_limited_raises_with_a_default_retry_after() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _json_response(429, {"error": {"message": "rate limited"}})

    client = _client_with(handler)
    with pytest.raises(RateLimitedError) as exc_info:
        await client.get_business_discovery("somecreator")

    assert exc_info.value.retry_after is not None


async def test_server_error_raises_transient_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, content="internal error")

    client = _client_with(handler)
    with pytest.raises(TransientPlatformError):
        await client.get_business_discovery("somecreator")


async def test_timeout_raises_transient_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out", request=request)

    client = _client_with(handler)
    with pytest.raises(TransientPlatformError):
        await client.get_business_discovery("somecreator")
