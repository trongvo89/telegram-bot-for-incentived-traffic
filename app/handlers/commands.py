from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

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
