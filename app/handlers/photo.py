"""Main upload flow.

Triggered on every photo/document(image) message sent to the bot:

  1. resolve active campaign for the user
  2. dedup on ``(file_unique_id, campaign)``
  3. forward to the campaign's storage channel + download bytes in parallel
  4. OCR (Vision) + parse fields with the campaign's regexes
  5. enqueue a row append on the SheetsWriter and insert the SQLite audit row
  6. edit the placeholder reply with the outcome; ping admin on PARTIAL/FAILED
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime
from html import escape
from io import BytesIO
from zoneinfo import ZoneInfo

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import Message

from app.config import Settings
from app.models.parsed import ParsedData, UploadStatus
from app.services.campaigns import CampaignsRegistry
from app.services.notifier import Notifier
from app.services.ocr import VisionOCRClient
from app.services.parser import extract_fields
from app.services.sheets import SheetsWriter
from app.services.state import State
from app.services.storage import ChannelStorage, StoredRef
from app.utils.logging import get_logger

router = Router(name="photo")
log = get_logger("handlers.photo")


def _format_active_list(active_names: list[str]) -> str:
    if not active_names:
        return "<i>(chưa có chiến dịch nào active)</i>"
    return "\n".join(f"• <code>{escape(n)}</code>" for n in sorted(active_names))


def _outcome_text(parsed: ParsedData, link: str | None) -> str:
    pieces = []
    if parsed.customer_name:
        pieces.append(f"Tên: <b>{escape(parsed.customer_name)}</b>")
    if parsed.phone:
        pieces.append(f"Phone: <code>{escape(parsed.phone)}</code>")
    if parsed.transaction_id:
        pieces.append(f"TXID: <code>{escape(parsed.transaction_id)}</code>")
    body = "\n".join(pieces) if pieces else "<i>(không trích xuất được trường nào)</i>"
    if parsed.status is UploadStatus.OK:
        head = "✓ Đã ghi nhận"
    elif parsed.status is UploadStatus.PARTIAL:
        head = "⚠ Đã ghi (thiếu trường) — admin sẽ kiểm tra"
    else:
        head = "✗ Không đọc được — admin sẽ kiểm tra thủ công"
    tail = f"\n<a href=\"{link}\">Screenshot lưu</a>" if link else ""
    return f"{head}\n{body}{tail}"


@router.message(F.photo)
async def on_photo(
    message: Message,
    bot: Bot,
    settings: Settings,
    state: State,
    campaigns: CampaignsRegistry,
    storage: ChannelStorage,
    ocr: VisionOCRClient,
    sheets: SheetsWriter,
    notifier: Notifier,
) -> None:
    assert message.from_user is not None
    assert message.photo, "F.photo guarantees at least one PhotoSize"
    user = message.from_user

    # ---- campaign resolution ------------------------------------------
    campaign_name = await state.get_campaign(user.id)
    if not campaign_name:
        active = await campaigns.list_active()
        await message.reply(
            "Bạn chưa chọn chiến dịch. Dùng <code>/campaign TÊN</code>.\n\n"
            "Active:\n" + _format_active_list([c.name for c in active]),
            disable_web_page_preview=True,
        )
        return

    camp = await campaigns.get(campaign_name)
    if camp is None:
        active = await campaigns.list_active()
        await message.reply(
            f"Chiến dịch <code>{escape(campaign_name)}</code> không còn active. "
            "Chọn lại bằng <code>/campaign TÊN</code>.\n\n"
            "Active:\n" + _format_active_list([c.name for c in active]),
            disable_web_page_preview=True,
        )
        return

    # ---- dedup ---------------------------------------------------------
    photo = message.photo[-1]  # largest resolution
    file_unique_id = photo.file_unique_id

    existing = await state.exists_upload(file_unique_id, camp.name)
    if existing is not None:
        await message.reply(
            f"♻️ Ảnh này đã ghi nhận trước đó "
            f"(lúc <code>{escape(str(existing['created_at']))}</code>, "
            f"status <code>{escape(str(existing['status']))}</code>)."
        )
        return

    placeholder = await message.reply("⏳ Đang xử lý...")

    # ---- forward + download in parallel --------------------------------
    stored: StoredRef | None = None
    image_bytes: bytes = b""

    async def _forward() -> StoredRef | None:
        if not camp.storage_channel_id:
            return None
        return await storage.forward(bot, message, camp.storage_channel_id)

    async def _download() -> bytes:
        buf = BytesIO()
        await bot.download(photo.file_id, destination=buf)
        return buf.getvalue()

    try:
        forward_res, download_res = await asyncio.gather(
            _forward(), _download(), return_exceptions=True
        )
    except Exception as exc:  # noqa: BLE001 - belt-and-braces; gather catches
        log.exception("photo_pipeline_setup_failed", error=str(exc))
        await _safe_edit(placeholder, "✗ Lỗi khi xử lý. Báo admin.")
        return

    if isinstance(forward_res, Exception):
        log.warning(
            "forward_failed",
            error_type=type(forward_res).__name__,
            error=str(forward_res),
            channel=camp.storage_channel_id,
        )
        await state.push_dead_letter(
            payload=json.dumps(
                {
                    "campaign": camp.name,
                    "user_id": user.id,
                    "file_unique_id": file_unique_id,
                    "stage": "forward",
                },
                ensure_ascii=False,
            ),
            reason=f"forward:{type(forward_res).__name__}:{forward_res}",
        )
        await notifier.notify_admin_dead_letter(
            admin_chat_id=camp.admin_chat_id,
            campaign=camp.name,
            reason=f"forward_failed: {type(forward_res).__name__}",
        )
        # We continue without the link — sheet row still gets written so the
        # OCR work isn't wasted, link column will be blank.
        stored = None
    else:
        stored = forward_res

    if isinstance(download_res, Exception):
        log.warning(
            "download_failed",
            error_type=type(download_res).__name__,
            error=str(download_res),
        )
        image_bytes = b""
    else:
        image_bytes = download_res

    # ---- OCR + parse ---------------------------------------------------
    raw_text = ""
    if image_bytes:
        try:
            raw_text = await ocr.extract_text(image_bytes)
        except Exception as exc:  # noqa: BLE001
            log.warning("ocr_failed", error_type=type(exc).__name__, error=str(exc))
            raw_text = ""

    parsed = extract_fields(raw_text, camp)
    link = stored.link if stored else None

    # ---- persist + enqueue --------------------------------------------
    now_local = datetime.now(ZoneInfo(settings.tz))
    timestamp = now_local.strftime("%Y-%m-%d %H:%M:%S")
    username = user.username or ""
    row: list[object] = [
        timestamp,
        user.id,
        username,
        parsed.customer_name or "",
        parsed.phone or "",
        parsed.transaction_id or "",
        link or "",
        raw_text,
        parsed.status.value,
    ]

    if sheets.enabled:
        await sheets.enqueue(
            sheet_id=camp.sheet_id,
            worksheet=camp.worksheet,
            row=row,
            context={
                "campaign": camp.name,
                "user_id": user.id,
                "file_unique_id": file_unique_id,
            },
        )
    else:
        log.warning("sheets_disabled_skipping_enqueue", campaign=camp.name)

    try:
        await state.insert_upload(
            user_id=user.id,
            username=username or None,
            campaign=camp.name,
            file_unique_id=file_unique_id,
            storage_chat_id=stored.chat_id if stored else None,
            storage_msg_id=stored.message_id if stored else None,
            status=parsed.status.value,
        )
    except Exception as exc:  # noqa: BLE001
        # Most likely the UNIQUE(file_unique_id, campaign) constraint — a
        # racing duplicate upload. Don't fail the user-facing reply.
        log.warning("insert_upload_failed", error_type=type(exc).__name__, error=str(exc))

    # ---- user reply + admin ping --------------------------------------
    await _safe_edit(placeholder, _outcome_text(parsed, link))

    if parsed.status is not UploadStatus.OK:
        await notifier.notify_admin_partial(
            admin_chat_id=camp.admin_chat_id,
            campaign=camp.name,
            username=username or None,
            user_id=user.id,
            parsed=parsed,
            screenshot_link=link,
        )


async def _safe_edit(message: Message, text: str) -> None:
    try:
        await message.edit_text(text, disable_web_page_preview=True)
    except TelegramAPIError as exc:
        log.warning("edit_placeholder_failed", error_type=type(exc).__name__, error=str(exc))
