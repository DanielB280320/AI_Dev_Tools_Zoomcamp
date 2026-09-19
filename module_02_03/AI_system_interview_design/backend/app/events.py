"""The change-notification bus behind `GET /sessions/{sessionId}/events`.

Events are notifications, not payloads: a subscriber that receives `doc`
re-fetches the canvas. That keeps the broker trivial — one bounded queue per
subscriber, per session — and means a dropped event costs at most one extra
round trip, never a lost edit.

Three event names only, matching the frontend's `BusEvent["kind"]`:
`doc`, `presence`, `session`.
"""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Literal

from .config import settings

EventKind = Literal["doc", "presence", "session"]

#: Slow subscribers lose the oldest notification rather than the whole stream;
#: any surviving event makes the client re-fetch everything anyway.
QUEUE_SIZE = 64


@dataclass(eq=False)
class Subscriber:
    """One open stream. `participant_id` is what lets a writer be skipped."""

    participant_id: str | None = None
    queue: asyncio.Queue[EventKind] = field(
        default_factory=lambda: asyncio.Queue(maxsize=QUEUE_SIZE)
    )


class EventBroker:
    def __init__(self) -> None:
        self._subscribers: dict[str, set[Subscriber]] = defaultdict(set)

    def publish(
        self, session_id: str, kind: EventKind, *, exclude_participant: str | None = None
    ) -> None:
        """Fan out to this session's subscribers. Never blocks, never raises.

        `exclude_participant` skips the client that caused the change — it
        already has the new state, and re-fetching its own 120 ms-debounced
        canvas write is pure waste.
        """
        for subscriber in list(self._subscribers.get(session_id, ())):
            if exclude_participant is not None and subscriber.participant_id == exclude_participant:
                continue
            queue = subscriber.queue
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:  # pragma: no cover - raced with the reader
                    pass
            queue.put_nowait(kind)

    def subscriber_count(self, session_id: str) -> int:
        return len(self._subscribers.get(session_id, ()))

    async def stream(
        self, session_id: str, participant_id: str | None = None
    ) -> AsyncIterator[str]:
        """Yield SSE frames for one subscriber until the client disconnects."""
        subscriber = Subscriber(participant_id=participant_id)
        queue = subscriber.queue
        self._subscribers[session_id].add(subscriber)
        try:
            # An immediate comment flushes headers, so EventSource fires `open`
            # without waiting for the first real change.
            yield ": connected\n\n"
            while True:
                try:
                    kind = await asyncio.wait_for(
                        queue.get(), timeout=settings.sse_keepalive_seconds
                    )
                except TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                yield format_event(kind, session_id)
        finally:
            subscribers = self._subscribers.get(session_id)
            if subscribers is not None:
                subscribers.discard(subscriber)
                if not subscribers:
                    del self._subscribers[session_id]

    def reset(self) -> None:
        self._subscribers.clear()


def format_event(kind: EventKind, session_id: str) -> str:
    data = json.dumps({"sessionId": session_id}, separators=(",", ":"))
    return f"event: {kind}\ndata: {data}\n\n"


broker = EventBroker()
