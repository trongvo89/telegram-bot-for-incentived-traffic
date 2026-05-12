from __future__ import annotations

from app.services.storage import _public_link


def test_public_link_strips_minus_100() -> None:
    assert _public_link(-1001234567890, 42) == "https://t.me/c/1234567890/42"


def test_public_link_handles_already_short_id() -> None:
    # if someone configures the short form, accept it as-is
    assert _public_link(1234567890, 5) == "https://t.me/c/1234567890/5"
