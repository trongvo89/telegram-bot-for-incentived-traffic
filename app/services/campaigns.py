from __future__ import annotations

import asyncio
import time
from pathlib import Path

import gspread
from google.oauth2.service_account import Credentials

from app.models.campaign import CONTROL_SHEET_HEADERS, Campaign
from app.utils.logging import get_logger

log = get_logger("services.campaigns")

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
WORKSHEET_NAME = "campaigns"


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
        return bool(self._control_sheet_id and self._credentials_path)

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
        ws = client.open_by_key(self._control_sheet_id).worksheet(WORKSHEET_NAME)
        rows = ws.get_all_records(expected_headers=list(CONTROL_SHEET_HEADERS))
        out: dict[str, Campaign] = {}
        for row in rows:
            camp = Campaign.from_row(row)
            if camp is not None:
                out[camp.name] = camp
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
