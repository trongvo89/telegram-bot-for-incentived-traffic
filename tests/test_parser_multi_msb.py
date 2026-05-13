from __future__ import annotations

from app.models.parsed import UploadStatus
from app.services.parser_multi_msb import MsbPage, classify_page, extract_multi_msb


# OCR samples mimic the line-broken output Vision returns for the real MSB
# screens — labels and values land on separate lines.

ACCOUNT_TEXT = """\
12:00
MSB
Mở tài khoản thành công
Thông tin tài khoản
Tên đăng nhập
0977101320
Chủ tài khoản
Tran Thi Huong
Số tài khoản
80003144101
Ngày mở
11:59, 12/05/2026
"""

DETAIL_TEXT_WITH_TX = """\
12:00
Chi tiết tài khoản
TK thanh toán 1
80003144101
0 VND
Tháng 5
Giao dịch gần đây
12/05/2026 12:00
80003144101-Ref
6132MCOBQ2YM27BJ-CK
-20,000 VND
12/05/2026 11:59
80003144101-6132BIDVE2
+20,000 VND
"""

DETAIL_TEXT_EMPTY = """\
Chi tiết tài khoản
TK thanh toán 1
80003144101
0 VND
Giao dịch gần đây
Chưa có giao dịch nào
"""

INFO_TEXT = """\
Bổ sung thông tin
Lương
Mức thu nhập
Cá nhân dưới 8 triệu VND
Nghề nghiệp
Khác
Chức vụ
Thất nghiệp
Email
ngnssjsj@gmqil.com
Mã giới thiệu
CITYADS111
Chi nhánh/PGD
PGD Trần Hưng Đạo
"""


def test_classify_account_page() -> None:
    assert classify_page(ACCOUNT_TEXT) is MsbPage.ACCOUNT


def test_classify_detail_page() -> None:
    assert classify_page(DETAIL_TEXT_WITH_TX) is MsbPage.DETAIL


def test_classify_info_page() -> None:
    assert classify_page(INFO_TEXT) is MsbPage.INFO


def test_classify_unknown_on_garbage() -> None:
    assert classify_page("just some random text") is MsbPage.UNKNOWN
    assert classify_page("") is MsbPage.UNKNOWN


def test_extract_all_three_pages_ok() -> None:
    parsed = extract_multi_msb([INFO_TEXT, ACCOUNT_TEXT, DETAIL_TEXT_WITH_TX])
    assert parsed.customer_name == "Tran Thi Huong"
    assert parsed.phone == "0977101320"
    assert parsed.referral_code == "CITYADS111"
    assert parsed.has_transaction is True
    assert parsed.status is UploadStatus.OK


def test_extract_partial_when_info_page_missing() -> None:
    parsed = extract_multi_msb([ACCOUNT_TEXT, DETAIL_TEXT_WITH_TX])
    assert parsed.customer_name == "Tran Thi Huong"
    assert parsed.phone == "0977101320"
    assert parsed.referral_code is None
    assert parsed.has_transaction is True
    assert parsed.status is UploadStatus.PARTIAL


def test_extract_partial_when_no_transactions_yet() -> None:
    parsed = extract_multi_msb([ACCOUNT_TEXT, DETAIL_TEXT_EMPTY, INFO_TEXT])
    assert parsed.has_transaction is False
    # All fields extracted but the account hasn't transacted → still PARTIAL,
    # since OK requires has_transaction.
    assert parsed.status is UploadStatus.PARTIAL


def test_extract_failed_on_all_unknown_pages() -> None:
    parsed = extract_multi_msb(["garbage one", "garbage two"])
    assert parsed.customer_name is None
    assert parsed.phone is None
    assert parsed.referral_code is None
    assert parsed.has_transaction is None
    assert parsed.status is UploadStatus.FAILED


def test_extract_ignores_empty_strings() -> None:
    parsed = extract_multi_msb(["", ACCOUNT_TEXT, ""])
    assert parsed.customer_name == "Tran Thi Huong"
    assert parsed.phone == "0977101320"


def test_extract_first_match_wins_for_duplicate_pages() -> None:
    # Two info pages — only the first should drive referral_code.
    second_info = INFO_TEXT.replace("CITYADS111", "WRONGCODE")
    parsed = extract_multi_msb([INFO_TEXT, second_info, ACCOUNT_TEXT])
    assert parsed.referral_code == "CITYADS111"
