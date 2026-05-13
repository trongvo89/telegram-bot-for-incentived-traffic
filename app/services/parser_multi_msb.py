"""Field extractor for the ``multi_msb`` campaign type.

Publishers send 3 MSB screenshots as a Telegram album:

  1. *Account opening*    — "Mở tài khoản thành công" page with
                            ``Tên đăng nhập`` (used as phone) and ``Chủ tài khoản``.
  2. *Account detail*     — "Chi tiết tài khoản" with the
                            "Giao dịch gần đây" list (we just need a boolean:
                            has at least one transaction).
  3. *Additional info*    — "Bổ sung thông tin" form containing
                            ``Mã giới thiệu`` (referral code).

OCR output for each image is classified by content keywords (publishers may
upload in any order). Missing pages do not abort the flow — the row is
written to the sheet with a PARTIAL status so admins can follow up.
"""
from __future__ import annotations

import re
from enum import Enum

from app.models.parsed import ParsedMultiMsb


class MsbPage(str, Enum):
    ACCOUNT = "account"      # "Mở tài khoản thành công"
    DETAIL = "detail"        # "Chi tiết tài khoản" + "Giao dịch gần đây"
    INFO = "info"            # "Bổ sung thông tin"
    UNKNOWN = "unknown"


# ---- classification -------------------------------------------------------

# Lowercase, accent-free fragments unique to each page. We keep them short
# and conservative — false negatives (an UNKNOWN classification) are OK,
# false positives across pages are not.
_PAGE_MARKERS: dict[MsbPage, tuple[str, ...]] = {
    MsbPage.ACCOUNT: (
        "mo tai khoan thanh cong",
        "ten dang nhap",
    ),
    MsbPage.DETAIL: (
        "chi tiet tai khoan",
        "giao dich gan day",
    ),
    MsbPage.INFO: (
        "bo sung thong tin",
        "ma gioi thieu",
    ),
}


def _strip_accents(s: str) -> str:
    # Cheap fold for Vietnamese: lowercase + remove diacritics by mapping the
    # common combining chars. Avoids depending on unicodedata.normalize being
    # exactly right on every host.
    table = str.maketrans(
        "àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđÀÁẢÃẠĂẰẮẲẴẶÂẦẤẨẪẬÈÉẺẼẸÊỀẾỂỄỆÌÍỈĨỊÒÓỎÕỌÔỒỐỔỖỘƠỜỚỞỠỢÙÚỦŨỤƯỪỨỬỮỰỲÝỶỸỴĐ",
        "aaaaaaaaaaaaaaaaaeeeeeeeeeeeiiiiiooooooooooooooooouuuuuuuuuuuyyyyydAAAAAAAAAAAAAAAAAEEEEEEEEEEEIIIIIOOOOOOOOOOOOOOOOOUUUUUUUUUUUYYYYYD",
    )
    return s.translate(table).lower()


def classify_page(raw_text: str) -> MsbPage:
    """Return which MSB page the OCR text most likely came from.

    Falls back to ``UNKNOWN`` when no marker matches, so the caller can keep
    the OCR text around for the dead-letter / raw_text columns even if the
    page couldn't be slotted.
    """
    if not raw_text:
        return MsbPage.UNKNOWN
    flat = _strip_accents(raw_text)
    best: MsbPage = MsbPage.UNKNOWN
    best_score = 0
    for page, markers in _PAGE_MARKERS.items():
        score = sum(1 for m in markers if m in flat)
        if score > best_score:
            best = page
            best_score = score
    return best


# ---- per-page field extraction -------------------------------------------

# Vision OCR breaks the MSB UI into label/value pairs that are usually on
# *adjacent lines* (not "Label: Value" same-line). We scan line-by-line and
# return the first non-empty, non-label line following a known label line.
_LABEL_NORMALISERS = {
    "chu tai khoan": "owner",
    "ten dang nhap": "login",
    "ma gioi thieu": "referral",
}


def _line_label(line: str) -> str | None:
    """Match a line against the known column labels (ignoring case + accents)."""
    flat = _strip_accents(line).strip().rstrip(":").strip()
    return _LABEL_NORMALISERS.get(flat)


# Strip stray label leftovers/glyphs OCR sometimes drops into the value cell.
_VALUE_STRIP = " :*\t-"


def _value_after_label(text: str, label_key: str) -> str | None:
    """Return the first non-blank value line directly after a label line.

    ``label_key`` is the normalised key from ``_LABEL_NORMALISERS``. Returns
    ``None`` when the label isn't found or no value follows it within a few
    lines (e.g. label was the last thing OCR'd).
    """
    lines = [ln.strip() for ln in text.splitlines()]
    for i, ln in enumerate(lines):
        if _line_label(ln) != label_key:
            continue
        # Take the next non-empty line that isn't itself a label.
        for nxt in lines[i + 1 : i + 5]:
            if not nxt:
                continue
            if _line_label(nxt) is not None:
                continue
            cleaned = nxt.strip(_VALUE_STRIP)
            if cleaned:
                return cleaned
        return None
    return None


_PHONE_DIGITS_RE = re.compile(r"\b0\d{9}\b")


def _extract_owner(text: str) -> str | None:
    return _value_after_label(text, "owner")


def _extract_login_phone(text: str) -> str | None:
    raw = _value_after_label(text, "login")
    if not raw:
        return None
    # MSB uses the user's phone (10 digits, leading 0) as the login. Strip
    # any incidental spaces / separators OCR may have inserted.
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 10 and digits.startswith("0"):
        return digits
    if len(digits) == 11 and digits.startswith("84"):
        return "0" + digits[2:]
    # OCR sometimes drops a digit — return the raw value so the admin can
    # still see what was on the screen instead of silently nullifying it.
    return raw or None


def _extract_referral(text: str) -> str | None:
    val = _value_after_label(text, "referral")
    if val is None:
        return None
    # Referral codes on MSB are typically alphanumeric, all caps. Pull the
    # first such token — guards against trailing UI fragments OCR slipped in.
    m = re.search(r"[A-Z0-9][A-Z0-9_\-]{2,}", val.upper())
    return m.group(0) if m else val or None


# Money lines on the account-detail page look like ``+20,000 VND`` or
# ``-20,000 VND`` next to each transaction. Their presence is the simplest
# robust signal that the account has activity.
_AMOUNT_LINE_RE = re.compile(r"[+\-]?\s*\d{1,3}(?:[.,]\d{3})*\s*VND", re.IGNORECASE)
_EMPTY_HISTORY_MARKERS = (
    "chua co giao dich",
    "khong co giao dich",
)


def _detect_has_transaction(detail_text: str) -> bool | None:
    """``True``/``False``/``None`` — see :class:`ParsedMultiMsb.has_transaction`."""
    if not detail_text:
        return None
    flat = _strip_accents(detail_text)
    if any(m in flat for m in _EMPTY_HISTORY_MARKERS):
        return False
    # Require ≥1 amount line *after* the "giao dich gan day" header, to avoid
    # picking up the total-balance figure at the top of the page.
    header_idx = flat.find("giao dich gan day")
    search_window = detail_text if header_idx < 0 else detail_text[header_idx:]
    return bool(_AMOUNT_LINE_RE.search(search_window))


# ---- public entry point ---------------------------------------------------


def extract_multi_msb(texts: list[str]) -> ParsedMultiMsb:
    """Classify each OCR text into a page slot and extract its fields.

    ``texts`` is the list of OCR results in the order the album arrived
    (1–3 items typically). Pages classified as ``UNKNOWN`` are dropped from
    the field-extraction pass but their raw text is still discoverable via
    the ``raw_text_*`` outputs of pages that *were* matched (best effort).
    """
    slot_account: str | None = None
    slot_detail: str | None = None
    slot_info: str | None = None
    for text in texts:
        if not text:
            continue
        page = classify_page(text)
        # First match wins for each slot; subsequent duplicates are ignored
        # to keep extraction deterministic on noisy uploads.
        if page is MsbPage.ACCOUNT and slot_account is None:
            slot_account = text
        elif page is MsbPage.DETAIL and slot_detail is None:
            slot_detail = text
        elif page is MsbPage.INFO and slot_info is None:
            slot_info = text

    customer_name = _extract_owner(slot_account) if slot_account else None
    phone = _extract_login_phone(slot_account) if slot_account else None
    referral_code = _extract_referral(slot_info) if slot_info else None
    has_transaction = _detect_has_transaction(slot_detail) if slot_detail else None

    return ParsedMultiMsb(
        customer_name=customer_name,
        phone=phone,
        referral_code=referral_code,
        has_transaction=has_transaction,
        raw_text_account=slot_account,
        raw_text_detail=slot_detail,
        raw_text_info=slot_info,
    )
