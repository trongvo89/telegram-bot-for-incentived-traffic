"""Thin Google Vision wrapper.

The Vision client is lazily constructed on first use so the bot can boot even
without credentials (useful in local dev / tests). When credentials are
missing, :meth:`VisionOCRClient.extract_text` returns an empty string instead
of raising — the caller will record a FAILED row with raw_text="".
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.utils.logging import get_logger

log = get_logger("services.ocr")


class VisionOCRClient:
    def __init__(self, credentials_path: Path | None) -> None:
        self._credentials_path = credentials_path
        self._client = None  # type: ignore[assignment]
        self._lock = asyncio.Lock()

    @property
    def enabled(self) -> bool:
        return self._credentials_path is not None and self._credentials_path.exists()

    async def _ensure_client(self):  # type: ignore[no-untyped-def]
        if self._client is not None:
            return self._client
        async with self._lock:
            if self._client is not None:
                return self._client
            # Imported lazily so the project can be unit-tested without the
            # google-cloud-vision wheel actually being importable yet.
            from google.cloud import vision  # type: ignore[import-not-found]

            self._client = await asyncio.to_thread(
                vision.ImageAnnotatorClient.from_service_account_file,
                str(self._credentials_path),
            )
            return self._client

    async def extract_text(self, image_bytes: bytes) -> str:
        """OCR a single image. Returns the full-text annotation, or '' on failure."""
        if not self.enabled:
            log.warning("ocr_disabled_no_credentials")
            return ""

        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=1, min=1, max=8),
            retry=retry_if_exception_type(Exception),
            reraise=True,
        ):
            with attempt:
                return await self._call(image_bytes)
        return ""  # unreachable, satisfies type checker

    async def _call(self, image_bytes: bytes) -> str:
        from google.cloud import vision  # type: ignore[import-not-found]

        client = await self._ensure_client()
        image = vision.Image(content=image_bytes)

        def _do() -> str:
            response = client.document_text_detection(image=image)
            if response.error.message:
                raise RuntimeError(f"vision_error: {response.error.message}")
            return response.full_text_annotation.text or ""

        text = await asyncio.to_thread(_do)
        log.info("ocr_ok", chars=len(text))
        return text
