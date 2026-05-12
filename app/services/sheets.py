"""Async append queue for Google Sheets.

Single in-process background worker drains an asyncio.Queue, opening (and
caching) the target worksheet per ``(sheet_id, worksheet_name)``. On quota /
transient errors we retry with exponential backoff; on permanent failure we
push to the dead-letter table so an admin can replay manually.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path

import gspread
from google.oauth2.service_account import Credentials
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.services.state import State
from app.utils.logging import get_logger

log = get_logger("services.sheets")

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# The fixed column layout written to each campaign's data tab.
DATA_HEADERS = [
    "timestamp",
    "telegram_user_id",
    "telegram_username",
    "customer_name",
    "phone",
    "transaction_id",
    "screenshot_link",
    "raw_ocr_text",
    "status",
]


@dataclass(frozen=True, slots=True)
class AppendJob:
    sheet_id: str
    worksheet: str
    row: list[object]
    # Carried through so a failure ends up in dead_letter with enough context
    # to manually replay.
    context: dict[str, object]


class SheetsWriter:
    def __init__(
        self,
        *,
        credentials_path: Path | None,
        state: State,
        max_queue: int = 256,
    ) -> None:
        self._credentials_path = credentials_path
        self._state = state
        self._queue: asyncio.Queue[AppendJob | None] = asyncio.Queue(maxsize=max_queue)
        self._worker_task: asyncio.Task[None] | None = None
        self._client: gspread.Client | None = None
        # cache of (sheet_id, worksheet_name) → worksheet handle
        self._ws_cache: dict[tuple[str, str], gspread.Worksheet] = {}

    @property
    def enabled(self) -> bool:
        return self._credentials_path is not None and self._credentials_path.exists()

    # ---- lifecycle ------------------------------------------------------

    async def start(self) -> None:
        if self._worker_task is None:
            self._worker_task = asyncio.create_task(self._run(), name="sheets-writer")
            log.info("sheets_worker_started", enabled=self.enabled)

    async def stop(self) -> None:
        if self._worker_task is None:
            return
        await self._queue.put(None)  # sentinel
        try:
            await asyncio.wait_for(self._worker_task, timeout=10)
        except asyncio.TimeoutError:
            self._worker_task.cancel()
            log.warning("sheets_worker_stop_timeout")
        self._worker_task = None

    # ---- producer -------------------------------------------------------

    async def enqueue(
        self,
        *,
        sheet_id: str,
        worksheet: str,
        row: list[object],
        context: dict[str, object] | None = None,
    ) -> None:
        await self._queue.put(
            AppendJob(
                sheet_id=sheet_id,
                worksheet=worksheet,
                row=row,
                context=context or {},
            )
        )

    # ---- worker ---------------------------------------------------------

    async def _run(self) -> None:
        while True:
            job = await self._queue.get()
            if job is None:
                log.info("sheets_worker_shutdown")
                return
            try:
                await self._append_with_retry(job)
            except Exception as exc:  # noqa: BLE001
                log.error(
                    "sheets_append_failed",
                    error_type=type(exc).__name__,
                    error=str(exc),
                    sheet_id=job.sheet_id,
                    worksheet=job.worksheet,
                )
                await self._state.push_dead_letter(
                    payload=json.dumps(
                        {
                            "sheet_id": job.sheet_id,
                            "worksheet": job.worksheet,
                            "row": [str(x) for x in job.row],
                            "context": job.context,
                        },
                        ensure_ascii=False,
                    ),
                    reason=f"sheets_append:{type(exc).__name__}:{exc}",
                )
            finally:
                self._queue.task_done()

    async def _append_with_retry(self, job: AppendJob) -> None:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(5),
            wait=wait_exponential(multiplier=2, min=2, max=60),
            retry=retry_if_exception_type(Exception),
            reraise=True,
        ):
            with attempt:
                await asyncio.to_thread(self._append_sync, job)
                log.info(
                    "sheets_appended",
                    sheet_id=job.sheet_id,
                    worksheet=job.worksheet,
                )

    # ---- gspread plumbing ----------------------------------------------

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

    def _get_worksheet(self, sheet_id: str, worksheet_name: str) -> gspread.Worksheet:
        key = (sheet_id, worksheet_name)
        cached = self._ws_cache.get(key)
        if cached is not None:
            return cached
        client = self._build_client()
        sh = client.open_by_key(sheet_id)
        try:
            ws = sh.worksheet(worksheet_name)
        except gspread.WorksheetNotFound:
            ws = sh.add_worksheet(title=worksheet_name, rows=1000, cols=len(DATA_HEADERS))
            ws.append_row(DATA_HEADERS, value_input_option="RAW")
        else:
            # If empty, seed headers so the sheet is self-describing.
            first = ws.row_values(1)
            if not first:
                ws.append_row(DATA_HEADERS, value_input_option="RAW")
        self._ws_cache[key] = ws
        return ws

    def _append_sync(self, job: AppendJob) -> None:
        ws = self._get_worksheet(job.sheet_id, job.worksheet)
        ws.append_row(job.row, value_input_option="USER_ENTERED")
