from __future__ import annotations

import asyncio

from app.bot import create_bot, create_dispatcher
from app.config import load_settings
from app.handlers import commands_router, register_error_handler
from app.utils.logging import configure_logging, get_logger


async def run() -> None:
    settings = load_settings()
    configure_logging(settings.log_level)
    log = get_logger("main")

    bot = create_bot(settings)
    dp = create_dispatcher()

    register_error_handler(dp)
    dp.include_router(commands_router)

    me = await bot.get_me()
    log.info("bot_started", username=me.username, id=me.id)

    try:
        await bot.delete_webhook(drop_pending_updates=False)
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot.session.close()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
