from __future__ import annotations

import asyncio
import time
from pathlib import Path

import gspread
from google.oauth2.service_account import Credentials

from app.models.campaign import Campaign
from app.utils.logging import get_logger

log = get_logger("services.campaigns")

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
WORKSHEET_NAME = "campaigns"

# Invisible characters that sometimes sneak into Google Sheets header cells
# when users paste from rich-text sources (BOM, ZWSP, ZWNJ, ZWJ, NBSP).
_INVISIBLE_CHARS = "﻿​‌‍ "


def _clean_header(value: str) -> str:
    return value.strip().strip(_INVISIBLE_CHARS).strip()


class CampaignsRegistry:
    """Reads campaigns from a control Google Sheet with TTL cache.

    The control sheet has a tab named ``campaigns`` whose first row holds the
    column headers listed in :data:`app.models.campaign.CONTROL_SHEET_HEADERS`.
    Each subsequent row is one campaign. Inactive rows are still loaded so we
    can warn if a publisher references them — :meth:`get` enforces ``active``.
    """

    def __init__(
        self,
        *,
        control_sheet_id: str,
        credentials_path: Path | None,
        ttl_sec: int = 300,
    ) -> None:
        self._control_sheet_id = control_sheet_id
        self._credentials_path = credentials_path
        self._ttl_sec = ttl_sec
        self._cache: dict[str, Campaign] = {}
        self._loaded_at: float = 0.0
        self._lock = asyncio.Lock()
        self._client: gspread.Client | None = None

    @property
    def enabled(self) -> bool:
        if not self._control_sheet_id or not self._credentials_path:
            return False
        return self._credentials_path.exists()

    def _build_client(self) -> gspread.Client:
        if self._client is not None:
            return self._client
        if not self._credentials_path:
            raise RuntimeError("GOOGLE_APPLICATION_CREDENTIALS not configured")
        creds = Credentials.from_service_account_file(
            str(self._credentials_path), scopes=SCOPES
        )
        self._client = gspread.authorize(creds)
        return self._client

    def _fetch_sync(self) -> dict[str, Campaign]:
        client = self._build_client()
        sh = client.open_by_key(self._control_sheet_id)
        ws = sh.worksheet(WORKSHEET_NAME)
        # Use get_all_values() instead of get_all_records() so we control the
        # header→key mapping ourselves. gspread's header keying is brittle:
        # BOMs, zero-width spaces, or trailing whitespace in row 1 silently
        # rename the keys and rows look "empty" on lookup.
        values = ws.get_all_values()
        raw_header = values[0] if values else []
        data_rows = values[1:] if len(values) > 1 else []
        # Normalize header cells: strip whitespace + common invisible chars.
        headers = [_clean_header(h) for h in raw_header]
        log.info(
            "control_sheet_fetched",
            spreadsheet_id=self._control_sheet_id,
            spreadsheet_title=sh.title,
            worksheet=ws.title,
            row_count=len(data_rows),
            headers_repr=[repr(h) for h in raw_header],
            headers_clean=headers,
            first_row_repr=[repr(c) for c in data_rows[0]] if data_rows else None,
        )
        out: dict[str, Campaign] = {}
        skipped = 0
        for row_values in data_rows:
            row = dict(zip(headers, row_values))
            camp = Campaign.from_row(row)
            if camp is None:
                skipped += 1
                continue
            out[camp.name] = camp
        if skipped:
            log.warning("control_sheet_rows_skipped", skipped=skipped)
        return out

    async def _refresh(self) -> None:
        loaded = await asyncio.to_thread(self._fetch_sync)
        self._cache = loaded
        self._loaded_at = time.monotonic()
        log.info("campaigns_loaded", count=len(loaded))

    async def ensure_loaded(self) -> None:
        if not self.enabled:
            return
        async with self._lock:
            if not self._cache or (time.monotonic() - self._loaded_at) > self._ttl_sec:
                await self._refresh()

    async def reload(self) -> int:
        """Force-refresh from the control sheet. Returns active campaign count."""
        if not self.enabled:
            return 0
        async with self._lock:
            await self._refresh()
        return sum(1 for c in self._cache.values() if c.active)

    async def get(self, name: str) -> Campaign | None:
        await self.ensure_loaded()
        camp = self._cache.get(name)
        if camp is None or not camp.active:
            return None
        return camp

    async def list_active(self) -> list[Campaign]:
        await self.ensure_loaded()
        return [c for c in self._cache.values() if c.active]
