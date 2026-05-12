"""Default regexes + small parsing helpers used by services/parser.py.

Keep this module *pure* (no I/O, no imports from app.services) so the parser
remains trivially unit-testable.
"""
from __future__ import annotations

import re

# Vietnamese mobile number:
#   - optional +84 / 84 / 0 prefix
#   - 9 digits after the prefix; major carrier prefixes start with 3/5/7/8/9
#   - allow common separators (space, dot, dash) between groups
#   - digit boundaries on both sides so we don't pluck a 10-digit subsequence
#     out of a longer account number (e.g. ``19033335083012`` would otherwise
#     match ``0333350830``).
PHONE_VN_REGEX = re.compile(
    r"(?<!\d)"
    r"(?:(?:\+?84)|0)\s*[\.\-]?\s*"
    r"(?:3|5|7|8|9)\d"
    r"(?:\s*[\.\-]?\s*\d){7}"
    r"(?!\d)"
)


def normalize_phone_vn(raw: str) -> str:
    """Strip separators and normalize a VN phone to leading-0 form.

    ``+84912345678`` / ``84912345678`` / ``0912.345.678`` → ``0912345678``.
    Returns the input untouched if it doesn't match the VN shape.
    """
    digits = re.sub(r"\D", "", raw)
    if digits.startswith("84") and len(digits) == 11:
        digits = "0" + digits[2:]
    elif digits.startswith("084"):  # +84 stripped to 084
        digits = "0" + digits[3:]
    return digits


def find_phone_vn(text: str) -> str | None:
    m = PHONE_VN_REGEX.search(text)
    if not m:
        return None
    return normalize_phone_vn(m.group(0))


# Tokens that almost always sit next to the customer name on a banking
# screenshot. We use these only as fallback hints — campaigns can override
# with their own ``name_regex``.
NAME_LABEL_RE = re.compile(
    r"(?:người nhận|nguoi nhan|tên|ten|name|chủ tk|chu tk|receiver|to)\s*[:\-]\s*(.+)",
    re.IGNORECASE,
)


def heuristic_name(text: str, phone_match: re.Match[str] | str | None = None) -> str | None:
    """Best-effort name extraction when no campaign regex matches.

    Strategy:
      1. Any line matching a known label (``Người nhận:``, ``Tên:``, …).
      2. The line directly above the phone number, if non-trivial.
    """
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    for ln in lines:
        m = NAME_LABEL_RE.search(ln)
        if m:
            candidate = m.group(1).strip(" .:-")
            if candidate:
                return candidate

    # Fallback: line directly above the first phone match.
    if phone_match is not None:
        phone_str = phone_match.group(0) if isinstance(phone_match, re.Match) else phone_match
        for i, ln in enumerate(lines):
            if phone_str in ln and i > 0:
                prev = lines[i - 1].strip(" .:-")
                # avoid label-only previous lines like "Số điện thoại"
                if prev and len(prev.split()) <= 6 and not prev.endswith(":"):
                    return prev
                break
    return None
