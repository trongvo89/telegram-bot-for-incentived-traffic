from __future__ import annotations

from pathlib import Path

import pytest

from app.services.ocr import VisionOCRClient


async def test_ocr_disabled_returns_empty(tmp_path: Path) -> None:
    client = VisionOCRClient(credentials_path=None)
    assert client.enabled is False
    assert await client.extract_text(b"\x89PNG\r\n") == ""


async def test_ocr_disabled_when_file_missing(tmp_path: Path) -> None:
    client = VisionOCRClient(credentials_path=tmp_path / "missing.json")
    assert client.enabled is False
    assert await client.extract_text(b"\x89PNG\r\n") == ""


@pytest.mark.asyncio
async def test_sheets_writer_disabled_when_no_creds(tmp_path: Path) -> None:
    from app.services.sheets import SheetsWriter
    from app.services.state import State

    s = State(db_path=tmp_path / "test.db", tz="UTC")
    await s.connect()
    try:
        writer = SheetsWriter(credentials_path=None, state=s)
        assert writer.enabled is False
        # start/stop are safe even when disabled — they just spin the worker
        await writer.start()
        await writer.stop()
    finally:
        await s.close()
