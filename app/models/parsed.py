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
