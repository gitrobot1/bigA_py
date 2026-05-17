import logging
from datetime import datetime

import akshare as ak
import pandas as pd

from app.services.chart_provider import ChartRange, trading_days_for_range
from app.services.market_catalog import GLOBAL_INDEX_CATALOG, GLOBAL_INDEX_BY_EM_NAME, GLOBAL_INDEX_BY_SYMBOL
from app.services.quote_provider import _run_sync, _safe_float, _with_retry

logger = logging.getLogger(__name__)

_US_SINA_MAP = {
    "SPX": ".INX",
    "NDX": ".IXIC",
    "DJIA": ".DJI",
}


def _row_to_quote(row: pd.Series, item: dict, source: str) -> dict:
    price = _safe_float(row.get("最新价"))
    change_pct = _safe_float(row.get("涨跌幅"))
    return {
        "symbol": item["symbol"],
        "name": item["name"],
        "region": item["region"],
        "price": price,
        "change_pct": change_pct,
        "change_amount": _safe_float(row.get("涨跌额")),
        "data_source": source,
        "em_name": item["em_name"],
    }


def _fetch_from_hist_fallback(item: dict) -> dict | None:
    sina_name = item.get("sina_hist")
    if sina_name:
        try:
            hist = _run_sync(ak.index_global_hist_sina, symbol=sina_name)
            if hist is not None and len(hist) >= 2:
                last, prev = hist.iloc[-1], hist.iloc[-2]
                price = _safe_float(last.get("close"))
                prev_p = _safe_float(prev.get("close"))
                chg = ((price - prev_p) / prev_p * 100) if prev_p else 0.0
                return {
                    "symbol": item["symbol"],
                    "name": item["name"],
                    "region": item["region"],
                    "price": price,
                    "change_pct": round(chg, 2),
                    "change_amount": round(price - prev_p, 4) if prev_p else None,
                    "data_source": "sina_global",
                    "em_name": item["em_name"],
                }
        except Exception as e:
            logger.debug("新浪全球 %s 失败: %s", sina_name, e)

    try:
        hist = _run_sync(ak.index_global_hist_em, symbol=item["em_name"])
        if hist is not None and len(hist) >= 1:
            last = hist.iloc[-1]
            price = _safe_float(last.get("最新价"))
            open_p = _safe_float(last.get("今开"))
            chg = ((price - open_p) / open_p * 100) if open_p else 0.0
            return {
                "symbol": item["symbol"],
                "name": item["name"],
                "region": item["region"],
                "price": price,
                "change_pct": round(chg, 2),
                "change_amount": None,
                "data_source": "em_global_hist",
                "em_name": item["em_name"],
            }
    except Exception as e:
        logger.debug("东财全球历史 %s 失败: %s", item["em_name"], e)
    return None


def fetch_global_indices_spot() -> list[dict]:
    names = {x["em_name"] for x in GLOBAL_INDEX_CATALOG}
    result: dict[str, dict] = {}

    try:
        df = _with_retry("东财全球指数", _run_sync, ak.index_global_spot_em)
        for _, row in df.iterrows():
            em_name = str(row.get("名称", ""))
            if em_name not in names:
                continue
            item = GLOBAL_INDEX_BY_EM_NAME[em_name]
            result[item["symbol"]] = _row_to_quote(row, item, "em_global")
    except Exception as e:
        logger.warning("东财全球指数失败: %s", e)

    for item in GLOBAL_INDEX_CATALOG:
        if item["symbol"] in result:
            continue
        sym = item["symbol"]
        if sym in _US_SINA_MAP:
            try:
                df = _run_sync(ak.index_us_stock_sina, symbol=_US_SINA_MAP[sym])
                if df is not None and not df.empty:
                    last = df.iloc[-1]
                    prev = df.iloc[-2] if len(df) > 1 else last
                    price = _safe_float(last.get("close"))
                    prev_p = _safe_float(prev.get("close"))
                    chg = ((price - prev_p) / prev_p * 100) if prev_p else 0.0
                    result[sym] = {
                        "symbol": sym,
                        "name": item["name"],
                        "region": item["region"],
                        "price": price,
                        "change_pct": round(chg, 2),
                        "change_amount": round(price - prev_p, 4) if prev_p else None,
                        "data_source": "sina_us",
                        "em_name": item["em_name"],
                    }
            except Exception as e:
                logger.debug("美股指数 %s 失败: %s", sym, e)

        if sym not in result:
            quote = _fetch_from_hist_fallback(item)
            if quote:
                result[sym] = quote

    return [result[s] for s in sorted(result.keys())]


def fetch_global_index_chart(symbol: str, chart_range: ChartRange) -> dict:
    item = GLOBAL_INDEX_BY_SYMBOL.get(symbol) or GLOBAL_INDEX_BY_EM_NAME.get(symbol)
    if not item:
        raise ValueError(f"未知全球指数: {symbol}")

    days = trading_days_for_range(chart_range)
    points: list[dict] = []

    if item.get("sina_hist"):
        try:
            df = _run_sync(ak.index_global_hist_sina, symbol=item["sina_hist"])
            if df is not None and not df.empty:
                df = df.tail(days)
                for _, row in df.iterrows():
                    d = row.get("date")
                    t = d.isoformat() if hasattr(d, "isoformat") else str(d)[:10]
                    close = _safe_float(row.get("close"))
                    points.append(
                        {
                            "time": t,
                            "price": close,
                            "open": _safe_float(row.get("open")),
                            "close": close,
                            "high": _safe_float(row.get("high")),
                            "low": _safe_float(row.get("low")),
                        }
                    )
        except Exception as e:
            logger.warning("新浪全球K线 %s 失败: %s", item.get("sina_hist"), e)

    if not points and item["symbol"] in _US_SINA_MAP:
        df = _run_sync(ak.index_us_stock_sina, symbol=_US_SINA_MAP[item["symbol"]])
        if df is not None and not df.empty:
            df = df.tail(days)
            for _, row in df.iterrows():
                points.append(
                    {
                        "time": str(row.get("date", ""))[:10],
                        "price": _safe_float(row.get("close")),
                        "open": _safe_float(row.get("open")),
                        "close": _safe_float(row.get("close")),
                        "high": _safe_float(row.get("high")),
                        "low": _safe_float(row.get("low")),
                    }
                )

    if not points:
        try:
            df = _run_sync(ak.index_global_hist_em, symbol=item["em_name"])
            if df is not None and not df.empty:
                df = df.tail(days)
                for _, row in df.iterrows():
                    d = row.get("日期")
                    t = d.isoformat() if hasattr(d, "isoformat") else str(d)[:10]
                    close = _safe_float(row.get("最新价"))
                    points.append(
                        {
                            "time": t,
                            "price": close,
                            "open": _safe_float(row.get("今开")),
                            "close": close,
                            "high": _safe_float(row.get("最高")),
                            "low": _safe_float(row.get("最低")),
                        }
                    )
        except Exception as e:
            logger.warning("全球指数K线 %s 失败: %s", item["em_name"], e)

    return {
        "symbol": item["symbol"],
        "name": item["name"],
        "asset_type": "global_index",
        "region": item["region"],
        "range": chart_range.value,
        "interval": "daily",
        "unit": "index",
        "note": "全球指数日线；非 A 股交易时段为上一收盘",
        "points": points,
    }
