"""Simple asyncio pub/sub EventBus for broadcasting events to all WebSocket clients."""

from __future__ import annotations

import asyncio


class EventBus:
    def __init__(self) -> None:
        self._queues: list[asyncio.Queue] = []

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=256)
        self._queues.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        try:
            self._queues.remove(q)
        except ValueError:
            pass

    async def publish(self, event: dict) -> None:
        self.publish_nowait(event)

    def publish_nowait(self, event: dict) -> None:
        for q in list(self._queues):
            if q.full():
                while not q.empty():
                    q.get_nowait()
                q.put_nowait({"type": "resync_required"})
            q.put_nowait(event)


_bus = EventBus()


def get_bus() -> EventBus:
    return _bus
