"""Pure-function field extractor used by the photo handler.

The campaign's optional ``txid_regex`` / ``name_regex`` / ``phone_regex`` columns
in the control sheet take precedence over the built-in fallbacks. The first
regex capture group, if present, is taken as the value; otherwise the whole
match. We intentionally don't raise on a missing field — :class:`ParsedData`
carries ``None`` and the caller decides the row status.
"""
from __future__ import annotations

import re
from re import Pattern

from app.models.campaign import Campaign
from app.models.parsed import ParsedData
from app.utils.regex_lib import find_phone_vn, heuristic_name, normalize_phone_vn


def _compile(pattern: str | None) -> Pattern[str] | None:
    if not pattern:
        return None
    try:
        return re.compile(pattern, re.IGNORECASE | re.MULTILINE)
    except re.error:
        return None


def _first(regex: Pattern[str], text: str) -> str | None:
    m = regex.search(text)
    if not m:
        return None
    if m.groups():
        return m.group(1).strip()
    return m.group(0).strip()


def extract_fields(raw_text: str, campaign: Campaign) -> ParsedData:
    text = raw_text or ""

    # ---- phone ---------------------------------------------------------
    phone: str | None = None
    phone_re = _compile(campaign.phone_regex)
    if phone_re is not None:
        m = phone_re.search(text)
        if m:
            value = m.group(1).strip() if m.groups() else m.group(0).strip()
            phone = normalize_phone_vn(value)
    if phone is None:
        phone = find_phone_vn(text)

    # ---- transaction id ------------------------------------------------
    txid: str | None = None
    txid_re = _compile(campaign.txid_regex)
    if txid_re is not None:
        txid = _first(txid_re, text)

    # ---- customer name -------------------------------------------------
    name: str | None = None
    name_re = _compile(campaign.name_regex)
    if name_re is not None:
        name = _first(name_re, text)
    if not name:
        name = heuristic_name(text, phone)

    return ParsedData(
        customer_name=name or None,
        phone=phone or None,
        transaction_id=txid or None,
        raw_text=text,
    )
