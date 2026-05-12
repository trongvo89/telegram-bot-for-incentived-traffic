"""Admin ping wrapper.

Kept as a separate module so the photo handler doesn't need to know how the
message is formatted, and so we have one place to add rate-limit / batching
later if admin chats get noisy.
"""
from __future__ import annotations

from html import escape

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

from app.models.parsed import ParsedData, UploadStatus
from app.utils.logging import get_logger

log = get_logger("services.notifier")


def _fmt_value(v: str | None) -> str:
    return escape(v) if v else "<i>—</i>"


class Notifier:
    def __init__(self, bot: Bot) -> None:
        self._bot = bot

    async def notify_admin_partial(
        self,
        *,
        admin_chat_id: int | None,
        campaign: str,
        username: str | None,
        user_id: int,
        parsed: ParsedData,
        screenshot_link: str | None,
    ) -> None:
        if not admin_chat_id:
            return

        status_icon = "⚠" if parsed.status is UploadStatus.PARTIAL else "✗"
        body_lines = [
            f"{status_icon} <b>{parsed.status.value}</b> — chiến dịch <code>{escape(campaign)}</code>",
            f"User: <code>@{escape(username) if username else user_id}</code> ({user_id})",
            f"Tên: {_fmt_value(parsed.customer_name)}",
            f"Phone: {_fmt_value(parsed.phone)}",
            f"TXID: {_fmt_value(parsed.transaction_id)}",
        ]
        if screenshot_link:
            body_lines.append(f"<a href=\"{screenshot_link}\">Screenshot</a>")
        text = "\n".join(body_lines)
        try:
            await self._bot.send_message(admin_chat_id, text, disable_web_page_preview=True)
        except TelegramAPIError as exc:
            log.warning(
                "notify_admin_failed",
                admin_chat_id=admin_chat_id,
                error_type=type(exc).__name__,
                error=str(exc),
            )

    async def notify_admin_dead_letter(
        self,
        *,
        admin_chat_id: int | None,
        campaign: str,
        reason: str,
    ) -> None:
        if not admin_chat_id:
            return
        text = (
            f"🚨 <b>Dead-letter</b> — chiến dịch <code>{escape(campaign)}</code>\n"
            f"Lý do: <code>{escape(reason)}</code>"
        )
        try:
            await self._bot.send_message(admin_chat_id, text)
        except TelegramAPIError as exc:
            log.warning(
                "notify_admin_failed",
                admin_chat_id=admin_chat_id,
                error_type=type(exc).__name__,
                error=str(exc),
            )
