from __future__ import annotations

from contextlib import suppress

from aiogram import Dispatcher
from aiogram.exceptions import TelegramAPIError
from aiogram.types import ErrorEvent, Message

from app.utils.logging import get_logger

log = get_logger("handlers.errors")


def register_error_handler(dp: Dispatcher) -> None:
    @dp.error()
    async def on_error(event: ErrorEvent) -> bool:
        exc = event.exception
        log.exception(
            "unhandled_error",
            update_id=getattr(event.update, "update_id", None),
            exc_type=type(exc).__name__,
            exc=str(exc),
        )
        # Tell the user something went wrong instead of silently dropping
        # the update. Plain text so a bad HTML reply can't double-fault.
        msg = getattr(event.update, "message", None)
        if isinstance(msg, Message):
            with suppress(TelegramAPIError):
                await msg.answer(
                    f"✗ Lỗi xử lý: {type(exc).__name__}: {exc}"[:300],
                    parse_mode=None,
                )
        return True
