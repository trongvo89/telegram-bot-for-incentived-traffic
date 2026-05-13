from __future__ import annotations

from datetime import datetime, timedelta
from html import escape
from zoneinfo import ZoneInfo

from aiogram import Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import Message

from app.config import Settings
from app.models.campaign import Campaign
from app.services.campaigns import CampaignsRegistry
from app.services.state import State

router = Router(name="commands")


WELCOME = (
    "👋 <b>Screenshot OCR Bot</b>\n\n"
    "Gửi ảnh chụp giao dịch cho bot, dữ liệu sẽ tự đẩy vào Google Sheet "
    "của chiến dịch.\n\n"
    "Bắt đầu:\n"
    "• <code>/campaign TÊN</code> — chọn chiến dịch (ví dụ: <code>/campaign msb</code>)\n"
    "• Gửi screenshot — bot sẽ OCR và ghi sheet\n"
    "• <code>/today</code> — xem số upload hôm nay\n"
    "• <code>/help</code> — danh sách lệnh"
)

HELP = (
    "<b>Các lệnh</b>\n"
    "• <code>/campaign TÊN</code> — set chiến dịch hiện tại\n"
    "• <code>/campaign</code> — xem chiến dịch đang chọn + danh sách active\n"
    "• <code>/today</code> — số upload hôm nay\n"
    "• <code>/help</code> — bảng này\n"
    "\n"
    "<b>Cho admin</b>\n"
    "• <code>/reload</code> — nạp lại danh sách chiến dịch từ control sheet\n"
    "• <code>/stats [day|month] [YYYY-MM-DD|YYYY-MM] [campaign]</code> — "
    "leaderboard upload theo ngày/tháng\n"
    "• <code>/deadletter</code> — xem 10 lỗi gần nhất\n"
    "• <code>/resolve ID</code> — đánh dấu dead-letter đã xử lý"
)


def _sheet_link(sheet_id: str) -> str:
    return f"https://docs.google.com/spreadsheets/d/{sheet_id}"


def _format_campaign_destination(camp: Campaign) -> str:
    name = escape(camp.name)
    worksheet = escape(camp.worksheet)
    return (
        f"✓ Đã chọn chiến dịch <b>{name}</b>.\n\n"
        f"📄 Dữ liệu sẽ ghi vào: "
        f"<a href=\"{_sheet_link(camp.sheet_id)}\">Google Sheet</a> "
        f"(tab <code>{worksheet}</code>)"
    )


def _format_active_list(active: list[Campaign]) -> str:
    if not active:
        return "<i>(chưa có chiến dịch nào active — admin cần thêm vào control sheet)</i>"
    return "\n".join(f"• <code>{escape(c.name)}</code>" for c in sorted(active, key=lambda c: c.name))


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
    app_state: State,
    campaigns: CampaignsRegistry,
) -> None:
    assert message.from_user is not None
    user_id = message.from_user.id

    active = await campaigns.list_active()
    active_list = _format_active_list(active)

    arg_raw = (command.args or "").strip()
    if not arg_raw:
        current = await app_state.get_campaign(user_id)
        if current:
            current_camp = await campaigns.get(current)
            if current_camp is not None:
                current_block = _format_campaign_destination(current_camp)
            else:
                current_block = (
                    f"Chiến dịch hiện tại: <b>{escape(current)}</b> "
                    "<i>(không còn active)</i>"
                )
        else:
            current_block = "Bạn chưa chọn chiến dịch."
        await message.answer(
            f"{current_block}\n\nDùng <code>/campaign TÊN</code>. Danh sách active:\n{active_list}",
            disable_web_page_preview=True,
        )
        return

    # Be forgiving: strip surrounding angle brackets / quotes the user may have
    # copied from the help text placeholder.
    name = arg_raw.split()[0].strip("<>\"'`")
    if not name:
        await message.answer("Tên chiến dịch không hợp lệ. Ví dụ: <code>/campaign msb</code>")
        return

    camp = await campaigns.get(name)
    if camp is None:
        await message.answer(
            f"Không thấy chiến dịch <code>{escape(name)}</code> "
            "(hoặc đang inactive).\n\nActive:\n" + active_list
        )
        return

    await app_state.set_campaign(user_id, camp.name)
    await message.answer(_format_campaign_destination(camp), disable_web_page_preview=True)


@router.message(Command("today"))
async def cmd_today(message: Message, app_state: State) -> None:
    assert message.from_user is not None
    n = await app_state.count_uploads_today(message.from_user.id)
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
        await message.answer(
            f"✗ Reload lỗi: <code>{escape(type(exc).__name__)}: "
            f"{escape(str(exc) or '(no message)')}</code>"
        )
        return
    await message.answer(f"✓ Đã reload. <b>{n}</b> chiến dịch active.")


@router.message(Command("deadletter"))
async def cmd_deadletter(message: Message, settings: Settings, app_state: State) -> None:
    assert message.from_user is not None
    if message.from_user.id not in settings.super_admin_ids:
        await message.answer("⛔ Lệnh này chỉ dành cho super admin.")
        return
    items = await app_state.list_dead_letter(limit=10, only_unresolved=True)
    if not items:
        await message.answer("✓ Không có dead-letter chưa xử lý.")
        return
    lines = ["<b>Dead-letter chưa xử lý (mới nhất trước):</b>"]
    for it in items:
        lines.append(
            f"• <code>#{it['id']}</code> {escape(str(it['created_at']))} — "
            f"<code>{escape(str(it['reason']))[:200]}</code>"
        )
    lines.append("\nDùng <code>/resolve ID</code> để đánh dấu đã xử lý.")
    await message.answer("\n".join(lines))


def _parse_stats_args(
    raw: str, *, tz: ZoneInfo, now_local: datetime
) -> tuple[datetime, datetime, str, str, str | None]:
    """Return (start_local, end_local, period, label, campaign_filter).

    Raises ValueError with a user-facing message on bad input.
    """
    args = raw.split()
    period = "day"
    date_arg: str | None = None
    campaign: str | None = None

    if args:
        head = args[0].lower()
        if head in ("day", "month"):
            period = head
            rest = args[1:]
        else:
            # No period specified — treat first arg as date or campaign.
            rest = args
        if rest:
            cand = rest[0]
            # Date-shaped tokens contain a digit + '-'; everything else is the
            # campaign name. Letting "msb" through here means /stats msb works.
            if "-" in cand and cand.replace("-", "").isdigit():
                date_arg = cand
                rest = rest[1:]
            if rest:
                campaign = rest[0]

    if period == "day":
        if date_arg:
            day = datetime.strptime(date_arg, "%Y-%m-%d").replace(tzinfo=tz)
        else:
            day = now_local
        start = day.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
        label = start.strftime("%Y-%m-%d")
    else:
        if date_arg:
            ym = datetime.strptime(date_arg, "%Y-%m").replace(tzinfo=tz)
        else:
            ym = now_local
        start = ym.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if start.month == 12:
            end = start.replace(year=start.year + 1, month=1)
        else:
            end = start.replace(month=start.month + 1)
        label = start.strftime("%Y-%m")
    return start, end, period, label, campaign


@router.message(Command("stats"))
async def cmd_stats(
    message: Message,
    command: CommandObject,
    settings: Settings,
    app_state: State,
) -> None:
    assert message.from_user is not None
    if message.from_user.id not in settings.super_admin_ids:
        await message.answer("⛔ Lệnh này chỉ dành cho super admin.")
        return

    tz = ZoneInfo(settings.tz)
    try:
        start_local, end_local, period, label, campaign_filter = _parse_stats_args(
            command.args or "", tz=tz, now_local=datetime.now(tz)
        )
    except ValueError:
        await message.answer(
            "Cú pháp: <code>/stats [day|month] [YYYY-MM-DD|YYYY-MM] [campaign]</code>\n"
            "Ví dụ: <code>/stats</code>, <code>/stats month</code>, "
            "<code>/stats day 2026-05-10 msb</code>"
        )
        return

    start_utc = start_local.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%d %H:%M:%S")
    end_utc = end_local.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%d %H:%M:%S")
    rows = await app_state.stats_for_range(
        start_utc=start_utc, end_utc=end_utc, campaign=campaign_filter
    )

    period_label = "ngày" if period == "day" else "tháng"
    camp_label = (
        f"campaign <code>{escape(campaign_filter)}</code>"
        if campaign_filter else "tất cả campaign"
    )
    header = f"📊 <b>Stats {period_label} {label}</b> ({camp_label})"
    if not rows:
        await message.answer(f"{header}\nKhông có upload nào.")
        return

    total = sum(r["total"] for r in rows)
    total_ok = sum(r["ok"] for r in rows)
    total_partial = sum(r["partial"] for r in rows)
    total_failed = sum(r["failed"] for r in rows)

    lines = [
        header,
        f"Tổng: <b>{total}</b> (OK {total_ok}, PART {total_partial}, FAIL {total_failed})",
        f"Publisher: <b>{len(rows)}</b>",
        "",
    ]
    display = rows[:30]
    for i, r in enumerate(display, start=1):
        uname = f"@{r['username']}" if r["username"] else "(no username)"
        lines.append(
            f"{i}. <code>{escape(uname)}</code> "
            f"(<code>{r['user_id']}</code>): "
            f"<b>{r['total']}</b> "
            f"(OK {r['ok']}, PART {r['partial']}, FAIL {r['failed']})"
        )
    if len(rows) > len(display):
        lines.append(f"\n<i>... và {len(rows) - len(display)} publisher khác</i>")

    await message.answer("\n".join(lines))


@router.message(Command("resolve"))
async def cmd_resolve(
    message: Message,
    command: CommandObject,
    settings: Settings,
    app_state: State,
) -> None:
    assert message.from_user is not None
    if message.from_user.id not in settings.super_admin_ids:
        await message.answer("⛔ Lệnh này chỉ dành cho super admin.")
        return
    arg = (command.args or "").strip()
    try:
        dl_id = int(arg)
    except ValueError:
        await message.answer("Dùng <code>/resolve ID</code> với ID là số nguyên.")
        return
    ok = await app_state.resolve_dead_letter(dl_id)
    if ok:
        await message.answer(f"✓ Đã đánh dấu dead-letter <code>#{dl_id}</code> resolved.")
    else:
        await message.answer(f"Không tìm thấy dead-letter <code>#{dl_id}</code>.")
