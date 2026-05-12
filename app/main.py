from __future__ import annotations

import asyncio

from app.bot import create_bot, create_dispatcher
from app.config import load_settings
from app.handlers import commands_router, register_error_handler
from app.services.campaigns import CampaignsRegistry
from app.services.state import State
from app.utils.logging import configure_logging, get_logger


async def run() -> None:
    settings = load_settings()
    configure_logging(settings.log_level)
    log = get_logger("main")

    state = State(db_path=settings.sqlite_path, tz=settings.tz)
    await state.connect()

    campaigns = CampaignsRegistry(
        control_sheet_id=settings.control_sheet_id,
        credentials_path=settings.google_application_credentials,
        ttl_sec=settings.campaign_cache_ttl_sec,
    )
    if campaigns.enabled:
        try:
            await campaigns.reload()
        except Exception as exc:  # noqa: BLE001
            log.warning("campaigns_initial_load_failed", error=str(exc))
    else:
        log.warning("campaigns_disabled — CONTROL_SHEET_ID or credentials missing")

    bot = create_bot(settings)
    dp = create_dispatcher()
    dp["settings"] = settings
    dp["state"] = state
    dp["campaigns"] = campaigns

    register_error_handler(dp)
    dp.include_router(commands_router)

    me = await bot.get_me()
    log.info("bot_started", username=me.username, id=me.id)

    try:
        await bot.delete_webhook(drop_pending_updates=False)
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await state.close()
        await bot.session.close()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
