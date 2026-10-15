"""In-memory event bus. Every agent action becomes an event that the dashboard streams over WebSocket."""

import asyncio
import itertools
from datetime import datetime, timezone

_counter = itertools.count(1)


class EventBus:
    def __init__(self, history_limit: int = 2000):
        self.history: list[dict] = []
        self.history_limit = history_limit
        self.subscribers: set[asyncio.Queue] = set()

    def publish(self, type_: str, **data) -> dict:
        event = {"id": next(_counter), "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "type": type_, **data}
        self.history.append(event)
        del self.history[: -self.history_limit]
        for q in self.subscribers:
            q.put_nowait(event)
        return event

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self.subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self.subscribers.discard(q)


bus = EventBus()
