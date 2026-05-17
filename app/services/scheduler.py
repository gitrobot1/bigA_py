import asyncio
import logging
from collections import defaultdict

from app.config import get_settings
from app.core.database import SessionLocal
from app.services import bond_provider, global_index_provider, quote_provider
from app.services.alert_engine import evaluate_alerts
from app.services.quote_cache import quote_cache
from app.services.types import AssetType

logger = logging.getLogger(__name__)
_task: asyncio.Task | None = None


def _collect_symbols(db) -> dict[str, set[str]]:
    from app.models import PriceAlert, WatchlistItem

    groups: dict[str, set[str]] = defaultdict(set)
    for row in db.query(WatchlistItem).all():
        groups[row.asset_type].add(row.symbol)
    for row in db.query(PriceAlert).filter(PriceAlert.is_active == 1).all():
        groups[row.asset_type].add(row.symbol)
    return groups


def refresh_market_data(fast: bool = True) -> None:
    """fast=True：跳过东财全市场批量与新浪全表重复拉取，适合手动刷新与定时任务。"""
    db = SessionLocal()
    error: str | None = None
    try:
        if not fast:
            quote_provider.clear_spot_caches()
        symbols = _collect_symbols(db)
        try:
            indices = quote_provider.fetch_indices()
            if indices:
                quote_cache.set_indices(indices)
            else:
                logger.warning("指数行情拉取为空，保留上次缓存（周末东财易失败，已尝试新浪）")
                if not quote_cache.get_indices():
                    error = error or "指数行情暂不可用"
        except Exception as e:
            logger.warning("指数行情拉取失败: %s", e)
            error = str(e)

        for quote in quote_provider.fetch_stock_quotes(
            list(symbols.get(AssetType.STOCK.value, [])), fast=fast
        ):
            quote_cache.set_quote(quote)
        for quote in quote_provider.fetch_fund_quotes(list(symbols.get(AssetType.FUND.value, []))):
            quote_cache.set_quote(quote)
        for quote in quote_provider.fetch_gold_quotes(list(symbols.get(AssetType.GOLD.value, []))):
            quote_cache.set_quote(quote)

        global_items = global_index_provider.fetch_global_indices_spot()
        if global_items:
            quote_cache.set_global_indices(global_items)
        bond_items = bond_provider.fetch_bond_yields_spot()
        if bond_items:
            quote_cache.set_bond_yields(bond_items)

        evaluate_alerts(db)
        quote_cache.mark_refreshed(error=error, db=db)
        logger.info("行情刷新完成，共 %d 条报价", len(quote_cache.get_all_quotes()))
    except Exception as e:
        logger.exception("行情刷新失败")
        quote_cache.mark_refreshed(error=str(e), db=db)
    finally:
        db.close()


async def _poll_loop() -> None:
    settings = get_settings()
    while True:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, refresh_market_data)
        await asyncio.sleep(settings.POLL_INTERVAL_SECONDS)


def start_scheduler() -> None:
    global _task
    if _task and not _task.done():
        return
    _task = asyncio.create_task(_poll_loop())


def stop_scheduler() -> None:
    global _task
    if _task:
        _task.cancel()
        _task = None
