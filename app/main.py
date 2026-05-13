from __future__ import annotations

import asyncio
import os
from pathlib import Path

from app.bot import create_bot, create_dispatcher
from app.config import load_settings
from app.handlers import commands_router, photo_router, register_error_handler
from app.services.campaigns import CampaignsRegistry
from app.services.notifier import Notifier
from app.services.ocr import VisionOCRClient
from app.services.sheets import SheetsWriter
from app.services.state import State
from app.services.storage import ChannelStorage
from app.utils.logging import configure_logging, get_logger
from app.utils.media_group import MediaGroupBuffer


def _materialize_sa_json() -> None:
    """Write the service-account JSON blob from env to disk, then point
    GOOGLE_APPLICATION_CREDENTIALS at it.

    The same logic exists in docker-entrypoint.sh, but Railway (and some
    other hosts) override the container ENTRYPOINT when a custom start
    command is configured. Running this in Python guarantees it happens
    regardless of how the container is launched.
    """
    blob = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS_JSON")
    if not blob:
        return
    path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") or "/app/secrets/sa.json"
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(blob)
    try:
        p.chmod(0o600)
    except OSError:
        pass
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(p)


async def run() -> None:
    settings = load_settings()
    configure_logging(settings.log_level)
    log = get_logger("main")

    gac_path = settings.google_application_credentials
    log.info(
        "creds_diag",
        control_sheet_id_set=bool(settings.control_sheet_id),
        gac_env=os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"),
        gac_json_env_present="GOOGLE_APPLICATION_CREDENTIALS_JSON" in os.environ,
        gac_json_env_size=len(os.environ.get("GOOGLE_APPLICATION_CREDENTIALS_JSON", "")),
        gac_path=str(gac_path) if gac_path else None,
        gac_path_exists=gac_path.exists() if gac_path else False,
        gac_path_size=(
            gac_path.stat().st_size if gac_path and gac_path.exists() else None
        ),
    )

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
            log.warning(
                "campaigns_initial_load_failed",
                error_type=type(exc).__name__,
                error=str(exc),
            )
    else:
        log.warning(
            "campaigns_disabled",
            control_sheet_id_set=bool(settings.control_sheet_id),
            credentials_path=str(settings.google_application_credentials)
            if settings.google_application_credentials
            else None,
            credentials_file_exists=(
                settings.google_application_credentials.exists()
                if settings.google_application_credentials
                else False
            ),
        )

    bot = create_bot(settings)
    dp = create_dispatcher()

    storage = ChannelStorage()
    ocr = VisionOCRClient(settings.google_application_credentials)
    sheets = SheetsWriter(
        credentials_path=settings.google_application_credentials,
        state=state,
    )
    await sheets.start()
    notifier = Notifier(bot)
    media_buffer = MediaGroupBuffer()

    dp["settings"] = settings
    # NOTE: must NOT be "state" — aiogram reserves that name for FSMContext.
    dp["app_state"] = state
    dp["campaigns"] = campaigns
    dp["storage"] = storage
    dp["ocr"] = ocr
    dp["sheets"] = sheets
    dp["notifier"] = notifier
    dp["media_buffer"] = media_buffer

    register_error_handler(dp)
    dp.include_router(commands_router)
    dp.include_router(photo_router)

    me = await bot.get_me()
    log.info(
        "bot_started",
        username=me.username,
        id=me.id,
        sheets_enabled=sheets.enabled,
        ocr_enabled=ocr.enabled,
        campaigns_enabled=campaigns.enabled,
    )

    try:
        await bot.delete_webhook(drop_pending_updates=False)
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await sheets.stop()
        await state.close()
        await bot.session.close()


def main() -> None:
    _materialize_sa_json()
    asyncio.run(run())


if __name__ == "__main__":
    main()
