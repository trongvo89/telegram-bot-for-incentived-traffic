from __future__ import annotations

from dataclasses import dataclass

# Campaign processing modes:
#   "single"    — one screenshot per upload, regex extraction (default; legacy)
#   "multi_msb" — album of MSB screenshots (account opening, account detail,
#                 additional info), auto-classified by OCR content
CAMPAIGN_TYPE_SINGLE = "single"
CAMPAIGN_TYPE_MULTI_MSB = "multi_msb"
CAMPAIGN_TYPES = (CAMPAIGN_TYPE_SINGLE, CAMPAIGN_TYPE_MULTI_MSB)

CONTROL_SHEET_HEADERS = (
    "campaign_name",
    "active",
    "campaign_type",
    "sheet_id",
    "worksheet",
    "admin_chat_id",
    "storage_channel_id",
    "txid_regex",
    "name_regex",
    "phone_regex",
    "notes",
)


def _truthy(v: object) -> bool:
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in {"true", "1", "yes", "y"}


def _opt_str(v: object) -> str | None:
    s = str(v).strip() if v is not None else ""
    return s or None


def _opt_int(v: object) -> int | None:
    s = str(v).strip() if v is not None else ""
    if not s:
        return None
    try:
        return int(s)
    except ValueError:
        return None


@dataclass(frozen=True, slots=True)
class Campaign:
    name: str
    active: bool
    campaign_type: str
    sheet_id: str
    worksheet: str
    admin_chat_id: int | None
    storage_channel_id: int | None
    txid_regex: str | None
    name_regex: str | None
    phone_regex: str | None
    notes: str = ""

    @classmethod
    def from_row(cls, row: dict) -> "Campaign | None":
        name = _opt_str(row.get("campaign_name"))
        sheet_id = _opt_str(row.get("sheet_id"))
        if not name or not sheet_id:
            return None
        ctype = (_opt_str(row.get("campaign_type")) or CAMPAIGN_TYPE_SINGLE).lower()
        if ctype not in CAMPAIGN_TYPES:
            # Unknown type: degrade to single rather than dropping the row, so
            # a typo in the sheet doesn't make a campaign disappear.
            ctype = CAMPAIGN_TYPE_SINGLE
        return cls(
            name=name,
            active=_truthy(row.get("active")),
            campaign_type=ctype,
            sheet_id=sheet_id,
            worksheet=_opt_str(row.get("worksheet")) or "data",
            admin_chat_id=_opt_int(row.get("admin_chat_id")),
            storage_channel_id=_opt_int(row.get("storage_channel_id")),
            txid_regex=_opt_str(row.get("txid_regex")),
            name_regex=_opt_str(row.get("name_regex")),
            phone_regex=_opt_str(row.get("phone_regex")),
            notes=str(row.get("notes") or ""),
        )
