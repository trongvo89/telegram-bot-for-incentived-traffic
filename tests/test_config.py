from __future__ import annotations

import pytest

from app.config import Settings


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for k in (
        "BOT_TOKEN",
        "SUPER_ADMIN_IDS",
        "CONTROL_SHEET_ID",
        "GOOGLE_APPLICATION_CREDENTIALS",
        "SQLITE_PATH",
        "TZ",
        "LOG_LEVEL",
    ):
        monkeypatch.delenv(k, raising=False)


def test_super_admin_ids_single(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOT_TOKEN", "t")
    monkeypatch.setenv("SUPER_ADMIN_IDS", "539294389")
    s = Settings()  # type: ignore[call-arg]
    assert s.super_admin_ids == [539294389]


def test_super_admin_ids_csv(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOT_TOKEN", "t")
    monkeypatch.setenv("SUPER_ADMIN_IDS", "123, 456 ,789")
    s = Settings()  # type: ignore[call-arg]
    assert s.super_admin_ids == [123, 456, 789]


def test_super_admin_ids_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOT_TOKEN", "t")
    monkeypatch.setenv("SUPER_ADMIN_IDS", "")
    s = Settings()  # type: ignore[call-arg]
    assert s.super_admin_ids == []


def test_super_admin_ids_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOT_TOKEN", "t")
    s = Settings()  # type: ignore[call-arg]
    assert s.super_admin_ids == []
