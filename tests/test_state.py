from __future__ import annotations

from pathlib import Path

import pytest

from app.services.state import State


@pytest.fixture
async def state(tmp_path: Path) -> State:
    s = State(db_path=tmp_path / "test.db", tz="Asia/Ho_Chi_Minh")
    await s.connect()
    try:
        yield s
    finally:
        await s.close()


async def test_set_and_get_campaign(state: State) -> None:
    assert await state.get_campaign(42) is None
    await state.set_campaign(42, "alpha")
    assert await state.get_campaign(42) == "alpha"
    await state.set_campaign(42, "beta")
    assert await state.get_campaign(42) == "beta"


async def test_dedup_unique_per_campaign(state: State) -> None:
    await state.insert_upload(
        user_id=1,
        username="x",
        campaign="alpha",
        file_unique_id="abc",
        storage_chat_id=-100,
        storage_msg_id=1,
        status="OK",
    )
    assert await state.exists_upload("abc", "alpha") is not None
    assert await state.exists_upload("abc", "beta") is None


async def test_count_today(state: State) -> None:
    assert await state.count_uploads_today(7) == 0
    for i in range(3):
        await state.insert_upload(
            user_id=7,
            username="u",
            campaign="alpha",
            file_unique_id=f"f{i}",
            storage_chat_id=-100,
            storage_msg_id=i,
            status="OK",
        )
    assert await state.count_uploads_today(7) == 3
    assert await state.count_uploads_today(8) == 0


async def test_stats_for_range_aggregates_per_user(state: State) -> None:
    # Two users, alpha campaign: u1 has 2 OK + 1 PARTIAL, u2 has 1 FAILED.
    statuses_u1 = ["OK", "OK", "PARTIAL"]
    for i, st in enumerate(statuses_u1):
        await state.insert_upload(
            user_id=1, username="alice", campaign="alpha",
            file_unique_id=f"u1-{i}", storage_chat_id=-100,
            storage_msg_id=i, status=st,
        )
    await state.insert_upload(
        user_id=2, username="bob", campaign="alpha",
        file_unique_id="u2-0", storage_chat_id=-100,
        storage_msg_id=99, status="FAILED",
    )
    # Wide window catches everything.
    rows = await state.stats_for_range(
        start_utc="2000-01-01 00:00:00", end_utc="2999-01-01 00:00:00"
    )
    by_user = {r["user_id"]: r for r in rows}
    assert by_user[1]["total"] == 3
    assert by_user[1]["ok"] == 2
    assert by_user[1]["partial"] == 1
    assert by_user[1]["failed"] == 0
    assert by_user[1]["username"] == "alice"
    assert by_user[2]["total"] == 1
    assert by_user[2]["failed"] == 1
    # Order: u1 first (3 > 1).
    assert rows[0]["user_id"] == 1


async def test_stats_for_range_filters_by_campaign(state: State) -> None:
    await state.insert_upload(
        user_id=1, username="a", campaign="alpha",
        file_unique_id="x", storage_chat_id=-100,
        storage_msg_id=1, status="OK",
    )
    await state.insert_upload(
        user_id=1, username="a", campaign="beta",
        file_unique_id="y", storage_chat_id=-100,
        storage_msg_id=2, status="OK",
    )
    rows = await state.stats_for_range(
        start_utc="2000-01-01 00:00:00",
        end_utc="2999-01-01 00:00:00",
        campaign="alpha",
    )
    assert len(rows) == 1
    assert rows[0]["total"] == 1
