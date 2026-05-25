import asyncio
import logging

from app.config import get_settings
from app.services.market_data import refresh_market_data
from app.services.market_refresh import try_run_refresh

logger = logging.getLogger(__name__)
_task: asyncio.Task | None = None
_poll_counter = 0


async def _poll_loop() -> None:
    global _poll_counter
    settings = get_settings()
    while True:
        _poll_counter += 1
        include_macro = _poll_counter % max(settings.MACRO_REFRESH_EVERY_N_POLLS, 1) == 0
        loop = asyncio.get_running_loop()

        def _job() -> None:
            try_run_refresh(refresh_market_data, fast=True, include_macro=include_macro)

        await loop.run_in_executor(None, _job)
        await asyncio.sleep(settings.POLL_INTERVAL_SECONDS)


def start_scheduler() -> None:
    global _task
    if _task and not _task.done():
        return
    _task = asyncio.create_task(_poll_loop())
    logger.info("行情定时任务已启动")


def stop_scheduler() -> None:
    global _task
    if _task:
        _task.cancel()
        _task = None
