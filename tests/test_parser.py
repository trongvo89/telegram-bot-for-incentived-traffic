from __future__ import annotations

from app.models.campaign import Campaign
from app.models.parsed import UploadStatus
from app.services.parser import extract_fields


def _camp(**overrides) -> Campaign:
    base = {
        "name": "alpha",
        "active": True,
        "sheet_id": "s",
        "worksheet": "data",
        "admin_chat_id": None,
        "storage_channel_id": None,
        "txid_regex": None,
        "name_regex": None,
        "phone_regex": None,
        "notes": "",
    }
    base.update(overrides)
    return Campaign(**base)


def test_full_extract_with_campaign_regexes() -> None:
    text = (
        "Giao dịch thành công\n"
        "Người nhận: NGUYEN VAN A\n"
        "Số điện thoại: 0912 345 678\n"
        "Mã giao dịch: MOMO1234567890\n"
    )
    camp = _camp(
        txid_regex=r"MOMO\d{10}",
        name_regex=r"Người nhận:\s*(.+)",
        phone_regex=None,
    )
    parsed = extract_fields(text, camp)
    assert parsed.customer_name == "NGUYEN VAN A"
    assert parsed.phone == "0912345678"
    assert parsed.transaction_id == "MOMO1234567890"
    assert parsed.status is UploadStatus.OK


def test_partial_when_txid_missing() -> None:
    text = "Tên: A B C\nSĐT: 0901234567\n"
    parsed = extract_fields(text, _camp())
    assert parsed.phone == "0901234567"
    assert parsed.transaction_id is None
    assert parsed.status is UploadStatus.PARTIAL


def test_failed_on_empty_text() -> None:
    parsed = extract_fields("", _camp())
    assert parsed.status is UploadStatus.FAILED


def test_phone_normalization_plus84() -> None:
    parsed = extract_fields("Phone +84-912-345-678", _camp())
    assert parsed.phone == "0912345678"


def test_heuristic_name_from_line_above_phone() -> None:
    text = "Họ và tên\nTRAN VAN B\n0978111222\n"
    parsed = extract_fields(text, _camp())
    assert parsed.phone == "0978111222"
    assert parsed.customer_name == "TRAN VAN B"


def test_invalid_user_regex_falls_back() -> None:
    parsed = extract_fields("Phone: 0912345678", _camp(phone_regex="(unclosed"))
    # bad regex is ignored; default VN matcher still finds the phone
    assert parsed.phone == "0912345678"


def test_txid_first_capture_group_used() -> None:
    text = "Reference: ABC-XYZ-99988877\n"
    parsed = extract_fields(text, _camp(txid_regex=r"Reference:\s*([A-Z0-9\-]+)"))
    assert parsed.transaction_id == "ABC-XYZ-99988877"


def test_phone_not_extracted_from_account_number() -> None:
    # Real MSB receipt: a 14-digit beneficiary account number sits between
    # the amount and the name. The phone regex must NOT pluck a 10-digit
    # subsequence (``0333350830``) out of it.
    text = (
        "Số tiền\n"
        "173,298,132 VND\n"
        "19033335083012\n"
        "VO VAN TRONG\n"
        "Tên tài khoản thụ hưởng\n"
    )
    parsed = extract_fields(text, _camp())
    assert parsed.phone is None
