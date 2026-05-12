from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import Message

from app.config import Settings
from app.services.campaigns import CampaignsRegistry
from app.services.state import State

router = Router(name="commands")


WELCOME = (
    "👋 <b>Screenshot OCR Bot</b>\n\n"
    "Gửi ảnh chụp giao dịch cho bot, dữ liệu sẽ tự đẩy vào Google Sheet "
    "của chiến dịch.\n\n"
    "Bắt đầu:\n"
    "• <code>/campaign &lt;tên&gt;</code> — chọn chiến dịch trước khi gửi ảnh\n"
    "• Gửi screenshot — bot sẽ OCR và ghi sheet\n"
    "• <code>/today</code> — xem số upload hôm nay\n"
    "• <code>/help</code> — danh sách lệnh"
)

HELP = (
    "<b>Các lệnh</b>\n"
    "• <code>/campaign &lt;tên&gt;</code> — set chiến dịch hiện tại\n"
    "• <code>/campaign</code> — xem chiến dịch đang chọn + danh sách active\n"
    "• <code>/today</code> — số upload hôm nay\n"
    "• <code>/help</code> — bảng này\n"
    "\n"
    "<b>Cho admin</b>\n"
    "• <code>/reload</code> — nạp lại danh sách chiến dịch từ control sheet"
)


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    await message.answer(WELCOME)


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(HELP)


@router.message(Command("campaign"))
async def cmd_campaign(
    message: Message,
    command: CommandObject,
    state: State,
    campaigns: CampaignsRegistry,
) -> None:
    assert message.from_user is not None
    user_id = message.from_user.id

    active = await campaigns.list_active()
    active_names = sorted(c.name for c in active)
    active_list = (
        "\n".join(f"• <code>{n}</code>" for n in active_names)
        if active_names
        else "<i>(chưa có chiến dịch nào active)</i>"
    )

    arg = (command.args or "").strip()
    if not arg:
        current = await state.get_campaign(user_id)
        current_line = (
            f"Chiến dịch hiện tại: <b>{current}</b>"
            if current
            else "Bạn chưa chọn chiến dịch."
        )
        await message.answer(
            f"{current_line}\n\nDùng <code>/campaign &lt;tên&gt;</code>. "
            f"Danh sách:\n{active_list}"
        )
        return

    name = arg.split()[0]
    camp = await campaigns.get(name)
    if camp is None:
        await message.answer(
            f"Không thấy chiến dịch <code>{name}</code> (hoặc đang inactive).\n\n"
            f"Active:\n{active_list}"
        )
        return

    await state.set_campaign(user_id, camp.name)
    await message.answer(f"✓ Đã chọn chiến dịch <b>{camp.name}</b>.")


@router.message(Command("today"))
async def cmd_today(message: Message, state: State) -> None:
    assert message.from_user is not None
    n = await state.count_uploads_today(message.from_user.id)
    await message.answer(f"📊 Hôm nay bạn đã upload <b>{n}</b> screenshot.")


@router.message(Command("reload"))
async def cmd_reload(
    message: Message,
    settings: Settings,
    campaigns: CampaignsRegistry,
) -> None:
    assert message.from_user is not None
    if message.from_user.id not in settings.super_admin_ids:
        await message.answer("⛔ Lệnh này chỉ dành cho super admin.")
        return
    if not campaigns.enabled:
        await message.answer(
            "⚠ Control sheet chưa cấu hình (cần CONTROL_SHEET_ID + service account)."
        )
        return
    try:
        n = await campaigns.reload()
    except Exception as exc:  # noqa: BLE001
        await message.answer(f"✗ Reload lỗi: <code>{exc}</code>")
        return
    await message.answer(f"✓ Đã reload. <b>{n}</b> chiến dịch active.")
