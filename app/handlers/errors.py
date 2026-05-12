from __future__ import annotations

from aiogram import Dispatcher
from aiogram.types import ErrorEvent

from app.utils.logging import get_logger

log = get_logger("handlers.errors")


def register_error_handler(dp: Dispatcher) -> None:
    @dp.error()
    async def on_error(event: ErrorEvent) -> bool:
        log.exception(
            "unhandled_error",
            update_id=getattr(event.update, "update_id", None),
            exc=str(event.exception),
        )
        return True
