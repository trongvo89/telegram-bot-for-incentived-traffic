from __future__ import annotations

from app.models.campaign import Campaign


def test_from_row_full() -> None:
    row = {
        "campaign_name": "momo_summer",
        "active": "TRUE",
        "sheet_id": "abc123",
        "worksheet": "data",
        "admin_chat_id": "-1001234567890",
        "storage_channel_id": "-1009876543210",
        "txid_regex": r"MOMO\d{10}",
        "name_regex": "",
        "phone_regex": "",
        "notes": "summer push",
    }
    c = Campaign.from_row(row)
    assert c is not None
    assert c.name == "momo_summer"
    assert c.active is True
    assert c.sheet_id == "abc123"
    assert c.worksheet == "data"
    assert c.admin_chat_id == -1001234567890
    assert c.storage_channel_id == -1009876543210
    assert c.txid_regex == r"MOMO\d{10}"
    assert c.name_regex is None
    assert c.phone_regex is None
    assert c.notes == "summer push"


def test_from_row_missing_required() -> None:
    assert Campaign.from_row({"campaign_name": "", "sheet_id": "x"}) is None
    assert Campaign.from_row({"campaign_name": "x", "sheet_id": ""}) is None


def test_from_row_inactive_defaults() -> None:
    row = {
        "campaign_name": "old",
        "active": "FALSE",
        "sheet_id": "s",
        "worksheet": "",
        "admin_chat_id": "",
        "storage_channel_id": "",
        "txid_regex": "",
        "name_regex": "",
        "phone_regex": "",
        "notes": "",
    }
    c = Campaign.from_row(row)
    assert c is not None
    assert c.active is False
    assert c.worksheet == "data"
    assert c.admin_chat_id is None
