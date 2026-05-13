"""Buffer Telegram album messages until the whole group has arrived.

Telegram delivers an album (media group) as several separate ``message``
updates that share the same ``media_group_id``, spaced milliseconds apart.
There is no "album complete" event — so we accumulate per group and flush
after a short quiet period.

Usage from a handler:

    async def on_photo(message: Message, ...):
        gid = message.media_group_id
        if gid is None:
            await process_single(message)
            return
        ready = await buffer.add(gid, message)
        if ready is None:
            return  # another message in the group will trigger the flush
        await process_album(ready)
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TypeVar

T = TypeVar("T")


@dataclass
class _Bucket:
    items: list = field(default_factory=list)
    # Bumped each time a new message arrives so we can tell whether the
    # debounce window expired without further activity.
    last_seen: float = 0.0
    flush_task: asyncio.Task | None = None


class MediaGroupBuffer:
    """Per-``media_group_id`` debounced collector.

    ``debounce_sec`` is the quiet-time before the album is considered complete.
    1.5s is comfortable for Telegram's typical inter-message delay (~100ms)
    while staying short enough that the user doesn't notice the wait.
    """

    def __init__(self, *, debounce_sec: float = 1.5) -> None:
        self._debounce = debounce_sec
        self._buckets: dict[str, _Bucket] = {}
        # Single lock guards bucket dict mutations; per-bucket work happens
        # outside it. This is fine — Telegram updates are processed one at a
        # time per chat by aiogram, so contention is low.
        self._lock = asyncio.Lock()

    async def add(self, group_id: str, item: T) -> list[T] | None:
        """Append an item to its group; return the full batch when ready.

        Returns ``None`` for the leading messages of an album (so the caller
        knows to defer processing), and the assembled list on the last call —
        whichever caller wins the race for the flushed bucket.
        """
        loop = asyncio.get_running_loop()
        async with self._lock:
            bucket = self._buckets.get(group_id)
            if bucket is None:
                bucket = _Bucket()
                self._buckets[group_id] = bucket
            bucket.items.append(item)
            bucket.last_seen = loop.time()
            if bucket.flush_task is not None:
                bucket.flush_task.cancel()
            # Schedule a fresh flush. The task waits ``debounce_sec`` then
            # signals via the future; the *first* call after that drain
            # returns the batch (subsequent ones for the same group return
            # an empty list since the dict entry is gone).
            ready_future: asyncio.Future[list[T]] = loop.create_future()
            bucket.flush_task = asyncio.create_task(
                self._flush_later(group_id, ready_future)
            )
        try:
            return await ready_future
        except asyncio.CancelledError:
            # Another item arrived before our debounce expired — let that
            # later call handle the flush.
            return None

    async def _flush_later(
        self, group_id: str, ready_future: asyncio.Future[list[T]]
    ) -> None:
        try:
            await asyncio.sleep(self._debounce)
        except asyncio.CancelledError:
            if not ready_future.done():
                ready_future.cancel()
            raise
        async with self._lock:
            bucket = self._buckets.pop(group_id, None)
            if bucket is None:
                if not ready_future.done():
                    ready_future.set_result([])
                return
            if not ready_future.done():
                ready_future.set_result(list(bucket.items))
