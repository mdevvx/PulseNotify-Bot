"""Decouples event detection (monitoring workers) from notification delivery
(section 48's queue architecture).

Workers call submit() to enqueue a freshly normalized event; a single
background consumer dequeues, deduplicates against the `events` table, and
only for genuinely-new events calls the sink. Centralizing the dedup check
here — rather than in every worker — means there's exactly one place that
decides "have we told anyone about this yet," regardless of which platform
or worker produced the event.

No real notification sink exists yet (that's Phase 4, alongside the first
platform); monitoring.manager wires this up with a placeholder for now.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Awaitable, Callable, Optional

from database.repositories.events import EventRepository
from events.models import NormalizedEvent
from utils.logger import get_logger

logger = get_logger(__name__)

NotificationSink = Callable[[NormalizedEvent], Awaitable[None]]


class EventProcessor:
    def __init__(self, event_repo: EventRepository, sink: NotificationSink, *, queue_size: int = 1000) -> None:
        self._event_repo = event_repo
        self._sink = sink
        self._queue: "asyncio.Queue[NormalizedEvent]" = asyncio.Queue(maxsize=queue_size)
        self._task: Optional[asyncio.Task] = None

    async def submit(self, event: NormalizedEvent) -> None:
        await self._queue.put(event)

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="event-processor")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    async def _run(self) -> None:
        while True:
            event = await self._queue.get()
            try:
                await self._handle(event)
            except Exception:
                logger.exception(
                    "Error handling %s event for guild %s account %s",
                    event.event_type.value,
                    event.guild_id,
                    event.account_id,
                )
            finally:
                self._queue.task_done()

    async def _handle(self, event: NormalizedEvent) -> None:
        assert event.guild_id is not None and event.account_id is not None, (
            "NormalizedEvent reached the processor without guild_id/account_id — "
            "the worker must fill these in before calling submit()"
        )

        row = await self._event_repo.record_if_new(
            guild_id=event.guild_id,
            account_id=event.account_id,
            platform=event.platform,
            event_type=event.event_type.value,
            platform_event_id=event.platform_event_id,
            metadata=event.metadata,
        )
        if row is None:
            return  # already seen — not a bug, just a duplicate poll/restart

        await self._sink(event)
        await self._event_repo.mark_notified(row["id"])
