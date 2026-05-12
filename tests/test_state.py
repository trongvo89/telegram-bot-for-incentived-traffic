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
