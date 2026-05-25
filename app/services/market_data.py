"""行情拉取与缓存更新（供定时任务与手动刷新共用）。"""

import logging
from collections import defaultdict

from app.core.database import SessionLocal
from app.services import bond_provider, global_index_provider, quote_provider
from app.services.alert_engine import evaluate_alerts
from app.services.quote_cache import quote_cache
from app.services.types import AssetType

logger = logging.getLogger(__name__)


def _collect_symbols(db) -> dict[str, set[str]]:
    from app.models import PriceAlert, WatchlistItem

    groups: dict[str, set[str]] = defaultdict(set)
    for row in db.query(WatchlistItem).all():
        groups[row.asset_type].add(row.symbol)
    for row in db.query(PriceAlert).filter(PriceAlert.is_active == 1).all():
        groups[row.asset_type].add(row.symbol)
    return groups


def refresh_market_data(*, fast: bool = True, include_macro: bool = True) -> None:
    """
    fast=True：跳过东财全市场批量与新浪全表重复拉取。
    include_macro=False：仅刷新自选相关 A 股/基金/黄金与国内指数（定时任务常用）。
    """
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
                logger.warning("指数行情拉取为空，保留上次缓存")
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

        if include_macro:
            global_items = global_index_provider.fetch_global_indices_spot()
            if global_items:
                quote_cache.set_global_indices(global_items)
            bond_items = bond_provider.fetch_bond_yields_spot()
            if bond_items:
                quote_cache.set_bond_yields(bond_items)
        else:
            logger.debug("本轮跳过全球指数与债券收益率刷新")

        evaluate_alerts(db)
        quote_cache.mark_refreshed(error=error, db=db)
        logger.info(
            "行情刷新完成，共 %d 条报价%s",
            len(quote_cache.get_all_quotes()),
            "" if include_macro else "（未刷新宏观数据）",
        )
    except Exception as e:
        logger.exception("行情刷新失败")
        quote_cache.mark_refreshed(error=str(e), db=db)
        raise
    finally:
        db.close()
