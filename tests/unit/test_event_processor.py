"""EventProcessor is the one place that decides "have we told anyone about
this yet" (section 48's queue architecture) — these tests drive it through
its real queue + a real EventRepository (backed by the fake DB), with only
the notification sink faked out."""

from __future__ import annotations

import asyncio

import pytest

from database.repositories.events import EventRepository
from events.models import EventType, NormalizedEvent
from events.processor import EventProcessor
from tests.unit.fakes import FakeDatabase


def _event(**overrides) -> NormalizedEvent:
    fields = dict(
        guild_id=1,
        account_id="acc-1",
        platform="youtube",
        platform_account_id="UC123",
        account_username="example",
        event_type=EventType.VIDEO_PUBLISHED,
        platform_event_id="vid-1",
        title="A new video",
    )
    fields.update(overrides)
    return NormalizedEvent(**fields)


@pytest.fixture
def sink_calls():
    calls = []

    async def sink(event: NormalizedEvent) -> None:
        calls.append(event)

    return sink, calls


async def test_new_event_reaches_the_sink(sink_calls) -> None:
    sink, calls = sink_calls
    processor = EventProcessor(EventRepository(FakeDatabase()), sink)  # type: ignore[arg-type]
    processor.start()

    await processor.submit(_event())
    await _drain(processor)

    assert len(calls) == 1
    assert calls[0].platform_event_id == "vid-1"

    await processor.stop()


async def test_duplicate_event_is_not_delivered_twice(sink_calls) -> None:
    sink, calls = sink_calls
    processor = EventProcessor(EventRepository(FakeDatabase()), sink)  # type: ignore[arg-type]
    processor.start()

    await processor.submit(_event())
    await processor.submit(_event())  # exact duplicate
    await _drain(processor)

    assert len(calls) == 1

    await processor.stop()


async def test_a_failing_sink_does_not_stop_the_processor(sink_calls) -> None:
    calls = []

    async def flaky_sink(event: NormalizedEvent) -> None:
        if event.platform_event_id == "bad":
            raise RuntimeError("Discord is down")
        calls.append(event)

    processor = EventProcessor(EventRepository(FakeDatabase()), flaky_sink)  # type: ignore[arg-type]
    processor.start()

    await processor.submit(_event(platform_event_id="bad"))
    await processor.submit(_event(platform_event_id="good"))
    await _drain(processor)

    assert [e.platform_event_id for e in calls] == ["good"]

    await processor.stop()


async def _drain(processor: EventProcessor) -> None:
    await processor._queue.join()  # type: ignore[attr-defined]
    await asyncio.sleep(0)  # let the consumer loop's finally/logging settle
