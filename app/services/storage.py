"""Forward incoming screenshots to a per-campaign Telegram private channel.

We keep the channel as the canonical image store (no S3, no local disk):
forwarding is one API call, preserves the original uploader as audit trail,
and the resulting ``t.me/c/<id>/<msg>`` deep-link is what we paste into the
Google Sheet. The link only opens for channel members — by design.
"""
from __future__ import annotations

from dataclasses import dataclass

from aiogram import Bot
from aiogram.types import Message

from app.utils.logging import get_logger

log = get_logger("services.storage")


@dataclass(frozen=True, slots=True)
class StoredRef:
    chat_id: int
    message_id: int
    link: str


def _public_link(channel_id: int, message_id: int) -> str:
    """Build the ``t.me/c/<short_id>/<msg_id>`` deep-link.

    Telegram channel IDs from getUpdates look like ``-1001234567890``. The
    deep-link uses the *short* id (without the ``-100`` prefix).
    """
    short = str(channel_id).removeprefix("-100").removeprefix("-")
    return f"https://t.me/c/{short}/{message_id}"


class ChannelStorage:
    async def forward(self, bot: Bot, message: Message, channel_id: int) -> StoredRef:
        """Forward ``message`` to ``channel_id``; return chat/msg ids + link.

        Caller is responsible for making sure the bot is admin in the target
        channel with ``can_post_messages``. The Telegram API raises
        ``TelegramForbiddenError`` / ``TelegramBadRequest`` otherwise.
        """
        forwarded = await bot.forward_message(
            chat_id=channel_id,
            from_chat_id=message.chat.id,
            message_id=message.message_id,
        )
        ref = StoredRef(
            chat_id=forwarded.chat.id,
            message_id=forwarded.message_id,
            link=_public_link(forwarded.chat.id, forwarded.message_id),
        )
        log.info("forwarded", channel=channel_id, msg_id=forwarded.message_id)
        return ref
