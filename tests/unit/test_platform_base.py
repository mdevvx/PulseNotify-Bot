"""event_types_for_capabilities: what alert_configurations rows get seeded
for a new account, derived from its adapter's declared capabilities."""

from __future__ import annotations

from events.models import EventType
from platforms.base import Capability, event_types_for_capabilities


def test_videos_and_shorts_map_to_their_event_types() -> None:
    types = event_types_for_capabilities(frozenset({Capability.VIDEOS, Capability.SHORTS}))
    assert types == {EventType.VIDEO_PUBLISHED, EventType.SHORT_PUBLISHED}


def test_live_status_maps_to_stream_started_and_ended_only() -> None:
    types = event_types_for_capabilities(frozenset({Capability.LIVE_STATUS}))
    assert types == {EventType.STREAM_STARTED, EventType.STREAM_ENDED}


def test_streams_capability_also_includes_stream_updated() -> None:
    types = event_types_for_capabilities(frozenset({Capability.STREAMS}))
    assert EventType.STREAM_UPDATED in types


def test_no_capabilities_produces_no_event_types() -> None:
    assert event_types_for_capabilities(frozenset()) == frozenset()


def test_youtubes_actual_capability_set() -> None:
    from platforms.youtube.adapter import YouTubeAdapter

    types = event_types_for_capabilities(YouTubeAdapter.capabilities)
    assert types == {EventType.VIDEO_PUBLISHED, EventType.SHORT_PUBLISHED, EventType.STREAM_STARTED, EventType.STREAM_ENDED}
