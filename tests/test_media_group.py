from __future__ import annotations

import asyncio

import pytest

from app.utils.media_group import MediaGroupBuffer


@pytest.mark.asyncio
async def test_single_message_flushes_after_debounce() -> None:
    buf = MediaGroupBuffer(debounce_sec=0.05)
    result = await buf.add("g1", "a")
    assert result == ["a"]


@pytest.mark.asyncio
async def test_three_messages_aggregated_into_one_batch() -> None:
    buf = MediaGroupBuffer(debounce_sec=0.1)

    # Fire 3 messages with tiny gaps; only the last call should receive the
    # full batch — earlier ones get cancelled (None).
    async def push(item: str, delay: float):
        await asyncio.sleep(delay)
        return await buf.add("g1", item)

    results = await asyncio.gather(
        push("a", 0.0),
        push("b", 0.02),
        push("c", 0.04),
    )
    # Exactly one call returns the full batch.
    full = [r for r in results if r is not None]
    nones = [r for r in results if r is None]
    assert len(full) == 1
    assert sorted(full[0]) == ["a", "b", "c"]
    assert len(nones) == 2


@pytest.mark.asyncio
async def test_groups_are_isolated() -> None:
    buf = MediaGroupBuffer(debounce_sec=0.05)
    res_a, res_b = await asyncio.gather(buf.add("g1", "x"), buf.add("g2", "y"))
    assert res_a == ["x"]
    assert res_b == ["y"]
