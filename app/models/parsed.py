from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class UploadStatus(str, Enum):
    OK = "OK"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class ParsedData:
    customer_name: str | None
    phone: str | None
    transaction_id: str | None
    raw_text: str

    @property
    def status(self) -> UploadStatus:
        found = sum(x is not None for x in (self.customer_name, self.phone, self.transaction_id))
        if found == 3:
            return UploadStatus.OK
        if found == 0:
            return UploadStatus.FAILED
        return UploadStatus.PARTIAL


@dataclass(frozen=True, slots=True)
class ParsedMultiMsb:
    """Fields extracted from a 3-screenshot MSB album.

    Each ``raw_text_*`` holds the OCR text of the corresponding classified
    page (None if that page wasn't found in the album). ``has_transaction``
    is True iff the account-detail page lists at least one transaction;
    None means the page wasn't classified at all so we can't tell.
    """

    customer_name: str | None
    phone: str | None
    referral_code: str | None
    has_transaction: bool | None
    raw_text_account: str | None
    raw_text_detail: str | None
    raw_text_info: str | None

    @property
    def status(self) -> UploadStatus:
        fields_ok = all(
            x is not None
            for x in (
                self.customer_name,
                self.phone,
                self.referral_code,
                self.has_transaction,
            )
        )
        any_field = any(
            x is not None
            for x in (
                self.customer_name,
                self.phone,
                self.referral_code,
                self.has_transaction,
            )
        )
        if fields_ok and self.has_transaction:
            return UploadStatus.OK
        if any_field:
            return UploadStatus.PARTIAL
        return UploadStatus.FAILED
