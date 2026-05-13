"""Upload pipeline.

Two flows live behind a single ``F.photo`` handler, dispatched by the
campaign's ``campaign_type``:

* ``single``   — one screenshot per upload (legacy). Regex extraction.
* ``multi_msb`` — Telegram album of MSB screenshots; classified by content
                  and reduced to a single sheet row.
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
from app.models.campaign import CAMPAIGN_TYPE_MULTI_MSB, Campaign
from app.models.parsed import ParsedData, ParsedMultiMsb, UploadStatus
from app.services.campaigns import CampaignsRegistry
from app.services.notifier import Notifier
from app.services.ocr import VisionOCRClient
from app.services.parser import extract_fields
from app.services.parser_multi_msb import extract_multi_msb
from app.services.sheets import (
    DATA_HEADERS_MULTI_MSB,
    DATA_HEADERS_SINGLE,
    SheetsWriter,
)
from app.services.state import State
from app.services.storage import ChannelStorage, StoredRef
from app.utils.logging import get_logger
from app.utils.media_group import MediaGroupBuffer

router = Router(name="photo")
log = get_logger("handlers.photo")


def _format_active_list(active_names: list[str]) -> str:
    if not active_names:
        return "<i>(chưa có chiến dịch nào active)</i>"
    return "\n".join(f"• <code>{escape(n)}</code>" for n in sorted(active_names))


def _outcome_text_single(parsed: ParsedData, link: str | None) -> str:
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


def _outcome_text_multi_msb(parsed: ParsedMultiMsb, links: list[str]) -> str:
    pieces = []
    if parsed.customer_name:
        pieces.append(f"Tên: <b>{escape(parsed.customer_name)}</b>")
    if parsed.phone:
        pieces.append(f"Phone: <code>{escape(parsed.phone)}</code>")
    if parsed.referral_code:
        pieces.append(f"Mã giới thiệu: <code>{escape(parsed.referral_code)}</code>")
    if parsed.has_transaction is True:
        pieces.append("Đã có giao dịch ✓")
    elif parsed.has_transaction is False:
        pieces.append("<i>Chưa phát sinh giao dịch</i>")
    body = "\n".join(pieces) if pieces else "<i>(không trích xuất được trường nào)</i>"
    if parsed.status is UploadStatus.OK:
        head = "✓ Đã ghi nhận"
    elif parsed.status is UploadStatus.PARTIAL:
        head = "⚠ Đã ghi (thiếu trường) — admin sẽ kiểm tra"
    else:
        head = "✗ Không đọc được — admin sẽ kiểm tra thủ công"
    tail = "".join(
        f"\n<a href=\"{lnk}\">Screenshot {i}</a>" for i, lnk in enumerate(links, start=1)
    )
    return f"{head}\n{body}{tail}"


@router.message(F.photo)
async def on_photo(
    message: Message,
    bot: Bot,
    settings: Settings,
    app_state: State,
    campaigns: CampaignsRegistry,
    storage: ChannelStorage,
    ocr: VisionOCRClient,
    sheets: SheetsWriter,
    notifier: Notifier,
    media_buffer: MediaGroupBuffer,
) -> None:
    assert message.from_user is not None
    assert message.photo, "F.photo guarantees at least one PhotoSize"
    user = message.from_user

    campaign_name = await app_state.get_campaign(user.id)
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

    if camp.campaign_type == CAMPAIGN_TYPE_MULTI_MSB:
        gid = message.media_group_id
        if gid is None:
            # Standalone photo on a multi-shot campaign — treat as a single-
            # image album so the same processing path applies.
            await _process_multi_msb(
                [message], camp,
                bot=bot, settings=settings, app_state=app_state,
                storage=storage, ocr=ocr, sheets=sheets, notifier=notifier,
            )
            return
        batch = await media_buffer.add(gid, message)
        if batch is None:
            return  # another message in the album will own the flush
        await _process_multi_msb(
            batch, camp,
            bot=bot, settings=settings, app_state=app_state,
            storage=storage, ocr=ocr, sheets=sheets, notifier=notifier,
        )
        return

    await _process_single(
        message, camp,
        bot=bot, settings=settings, app_state=app_state,
        storage=storage, ocr=ocr, sheets=sheets, notifier=notifier,
    )


# ---- single-screenshot flow ----------------------------------------------


async def _process_single(
    message: Message,
    camp: Campaign,
    *,
    bot: Bot,
    settings: Settings,
    app_state: State,
    storage: ChannelStorage,
    ocr: VisionOCRClient,
    sheets: SheetsWriter,
    notifier: Notifier,
) -> None:
    assert message.from_user is not None
    assert message.photo
    user = message.from_user

    photo = message.photo[-1]
    file_unique_id = photo.file_unique_id

    existing = await app_state.exists_upload(file_unique_id, camp.name)
    if existing is not None:
        await message.reply(
            f"♻️ Ảnh này đã ghi nhận trước đó "
            f"(lúc <code>{escape(str(existing['created_at']))}</code>, "
            f"status <code>{escape(str(existing['status']))}</code>)."
        )
        return

    placeholder = await message.reply("⏳ Đang xử lý...")

    stored, image_bytes = await _forward_and_download(
        bot=bot, storage=storage, message=message,
        photo_file_id=photo.file_id,
        storage_channel_id=camp.storage_channel_id,
        app_state=app_state, notifier=notifier,
        campaign_name=camp.name, admin_chat_id=camp.admin_chat_id,
        file_unique_id=file_unique_id,
    )

    raw_text = await _ocr_safe(ocr, image_bytes)
    parsed = extract_fields(raw_text, camp)
    link = stored.link if stored else None

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
            headers=DATA_HEADERS_SINGLE,
            context={
                "campaign": camp.name,
                "user_id": user.id,
                "file_unique_id": file_unique_id,
            },
        )
    else:
        log.warning("sheets_disabled_skipping_enqueue", campaign=camp.name)

    try:
        await app_state.insert_upload(
            user_id=user.id,
            username=username or None,
            campaign=camp.name,
            file_unique_id=file_unique_id,
            storage_chat_id=stored.chat_id if stored else None,
            storage_msg_id=stored.message_id if stored else None,
            status=parsed.status.value,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("insert_upload_failed", error_type=type(exc).__name__, error=str(exc))

    await _safe_edit(placeholder, _outcome_text_single(parsed, link))

    if parsed.status is not UploadStatus.OK:
        await notifier.notify_admin_partial(
            admin_chat_id=camp.admin_chat_id,
            campaign=camp.name,
            username=username or None,
            user_id=user.id,
            parsed=parsed,
            screenshot_link=link,
        )


# ---- multi_msb album flow ------------------------------------------------


async def _process_multi_msb(
    messages: list[Message],
    camp: Campaign,
    *,
    bot: Bot,
    settings: Settings,
    app_state: State,
    storage: ChannelStorage,
    ocr: VisionOCRClient,
    sheets: SheetsWriter,
    notifier: Notifier,
) -> None:
    # The album is keyed on the first photo's file_unique_id — re-sending the
    # same screenshot set later won't match (Telegram regenerates IDs), but
    # a real double-tap within the same session is caught.
    first = messages[0]
    assert first.from_user is not None
    user = first.from_user
    head_photo = first.photo[-1] if first.photo else None
    if head_photo is None:
        return
    album_key = f"album:{head_photo.file_unique_id}"

    existing = await app_state.exists_upload(album_key, camp.name)
    if existing is not None:
        await first.reply(
            f"♻️ Album này đã ghi nhận trước đó "
            f"(lúc <code>{escape(str(existing['created_at']))}</code>, "
            f"status <code>{escape(str(existing['status']))}</code>)."
        )
        return

    placeholder = await first.reply(
        f"⏳ Đang xử lý {len(messages)} ảnh..."
    )

    # Forward + download + OCR each message in parallel.
    async def _one(m: Message) -> tuple[StoredRef | None, str]:
        if not m.photo:
            return None, ""
        photo = m.photo[-1]
        stored, image_bytes = await _forward_and_download(
            bot=bot, storage=storage, message=m,
            photo_file_id=photo.file_id,
            storage_channel_id=camp.storage_channel_id,
            app_state=app_state, notifier=notifier,
            campaign_name=camp.name, admin_chat_id=camp.admin_chat_id,
            file_unique_id=photo.file_unique_id,
        )
        text = await _ocr_safe(ocr, image_bytes)
        return stored, text

    results = await asyncio.gather(*(_one(m) for m in messages))
    stored_refs: list[StoredRef | None] = [r[0] for r in results]
    texts: list[str] = [r[1] for r in results]

    parsed = extract_multi_msb(texts)

    # Match links to the parsed slots in extract_multi_msb order — we rerun
    # the classification here so the sheet links line up with the
    # account/detail/info columns even if the publisher uploaded out of order.
    from app.services.parser_multi_msb import MsbPage, classify_page

    slot_links: dict[MsbPage, str] = {}
    for stored, text in zip(stored_refs, texts):
        if not text or not stored:
            continue
        page = classify_page(text)
        slot_links.setdefault(page, stored.link)

    link_account = slot_links.get(MsbPage.ACCOUNT, "")
    link_detail = slot_links.get(MsbPage.DETAIL, "")
    link_info = slot_links.get(MsbPage.INFO, "")
    all_links = [lnk for lnk in (link_account, link_detail, link_info) if lnk]

    raw_text_combined = "\n\n--- PAGE BREAK ---\n\n".join(t for t in texts if t)

    now_local = datetime.now(ZoneInfo(settings.tz))
    timestamp = now_local.strftime("%Y-%m-%d %H:%M:%S")
    username = user.username or ""
    has_tx_cell: str
    if parsed.has_transaction is True:
        has_tx_cell = "TRUE"
    elif parsed.has_transaction is False:
        has_tx_cell = "FALSE"
    else:
        has_tx_cell = ""
    row: list[object] = [
        timestamp,
        user.id,
        username,
        parsed.customer_name or "",
        parsed.phone or "",
        parsed.referral_code or "",
        has_tx_cell,
        link_account,
        link_detail,
        link_info,
        raw_text_combined,
        parsed.status.value,
    ]

    if sheets.enabled:
        await sheets.enqueue(
            sheet_id=camp.sheet_id,
            worksheet=camp.worksheet,
            row=row,
            headers=DATA_HEADERS_MULTI_MSB,
            context={
                "campaign": camp.name,
                "user_id": user.id,
                "album_key": album_key,
            },
        )
    else:
        log.warning("sheets_disabled_skipping_enqueue", campaign=camp.name)

    head_stored = stored_refs[0]
    try:
        await app_state.insert_upload(
            user_id=user.id,
            username=username or None,
            campaign=camp.name,
            file_unique_id=album_key,
            storage_chat_id=head_stored.chat_id if head_stored else None,
            storage_msg_id=head_stored.message_id if head_stored else None,
            status=parsed.status.value,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("insert_upload_failed", error_type=type(exc).__name__, error=str(exc))

    await _safe_edit(placeholder, _outcome_text_multi_msb(parsed, all_links))

    if parsed.status is not UploadStatus.OK:
        await notifier.notify_admin_multi_msb(
            admin_chat_id=camp.admin_chat_id,
            campaign=camp.name,
            username=username or None,
            user_id=user.id,
            parsed=parsed,
            screenshot_links=all_links,
        )


# ---- shared building blocks ----------------------------------------------


async def _forward_and_download(
    *,
    bot: Bot,
    storage: ChannelStorage,
    message: Message,
    photo_file_id: str,
    storage_channel_id: int | None,
    app_state: State,
    notifier: Notifier,
    campaign_name: str,
    admin_chat_id: int | None,
    file_unique_id: str,
) -> tuple[StoredRef | None, bytes]:
    async def _forward() -> StoredRef | None:
        if not storage_channel_id:
            return None
        return await storage.forward(bot, message, storage_channel_id)

    async def _download() -> bytes:
        buf = BytesIO()
        await bot.download(photo_file_id, destination=buf)
        return buf.getvalue()

    forward_res, download_res = await asyncio.gather(
        _forward(), _download(), return_exceptions=True
    )

    stored: StoredRef | None
    if isinstance(forward_res, Exception):
        log.warning(
            "forward_failed",
            error_type=type(forward_res).__name__,
            error=str(forward_res),
            channel=storage_channel_id,
        )
        assert message.from_user is not None
        await app_state.push_dead_letter(
            payload=json.dumps(
                {
                    "campaign": campaign_name,
                    "user_id": message.from_user.id,
                    "file_unique_id": file_unique_id,
                    "stage": "forward",
                },
                ensure_ascii=False,
            ),
            reason=f"forward:{type(forward_res).__name__}:{forward_res}",
        )
        await notifier.notify_admin_dead_letter(
            admin_chat_id=admin_chat_id,
            campaign=campaign_name,
            reason=f"forward_failed: {type(forward_res).__name__}",
        )
        stored = None
    else:
        stored = forward_res

    image_bytes: bytes
    if isinstance(download_res, Exception):
        log.warning(
            "download_failed",
            error_type=type(download_res).__name__,
            error=str(download_res),
        )
        image_bytes = b""
    else:
        image_bytes = download_res

    return stored, image_bytes


async def _ocr_safe(ocr: VisionOCRClient, image_bytes: bytes) -> str:
    if not image_bytes:
        return ""
    try:
        return await ocr.extract_text(image_bytes)
    except Exception as exc:  # noqa: BLE001
        log.warning("ocr_failed", error_type=type(exc).__name__, error=str(exc))
        return ""


async def _safe_edit(message: Message, text: str) -> None:
    try:
        await message.edit_text(text, disable_web_page_preview=True)
    except TelegramAPIError as exc:
        log.warning("edit_placeholder_failed", error_type=type(exc).__name__, error=str(exc))
