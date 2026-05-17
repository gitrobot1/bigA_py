import logging

import akshare as ak
import pandas as pd

from app.services.chart_provider import ChartRange, trading_days_for_range
from app.services.market_catalog import BOND_SINA_NAME, BOND_YIELD_CATALOG
from app.services.quote_provider import _run_sync, _safe_float

logger = logging.getLogger(__name__)

_CATALOG_BY_SYMBOL = {x["symbol"]: x for x in BOND_YIELD_CATALOG}


def _fetch_yield_series(sina_name: str) -> pd.DataFrame | None:
    if sina_name.startswith("中国"):
        return _run_sync(ak.bond_gb_zh_sina, symbol=sina_name)
    return _run_sync(ak.bond_gb_us_sina, symbol=sina_name)


def fetch_bond_yields_spot() -> list[dict]:
    result = []
    for item in BOND_YIELD_CATALOG:
        sina_name = item["name"]
        try:
            df = _fetch_yield_series(sina_name)
            if df is None or df.empty:
                continue
            last = df.iloc[-1]
            prev = df.iloc[-2] if len(df) > 1 else last
            yield_now = _safe_float(last.get("close"))
            yield_prev = _safe_float(prev.get("close"))
            change = yield_now - yield_prev
            change_pct = (change / yield_prev * 100) if yield_prev else 0.0
            result.append(
                {
                    "symbol": item["symbol"],
                    "name": item["name"],
                    "market": item["market"],
                    "term": item["term"],
                    "yield": round(yield_now, 4),
                    "change": round(change, 4),
                    "change_pct": round(change_pct, 2),
                    "unit": "percent",
                    "data_source": "sina_bond",
                    "updated_at": str(last.get("date", ""))[:10],
                }
            )
        except Exception as e:
            logger.warning("债券收益率 %s 失败: %s", sina_name, e)
    return result


def fetch_bond_yield_chart(symbol: str, chart_range: ChartRange) -> dict:
    item = _CATALOG_BY_SYMBOL.get(symbol)
    if not item:
        name = BOND_SINA_NAME.get(symbol)
        if not name:
            raise ValueError(f"未知债券品种: {symbol}")
        item = {"symbol": symbol, "name": name, "market": "cn" if name.startswith("中国") else "us", "term": ""}
    else:
        name = item["name"]

    days = trading_days_for_range(chart_range)
    df = _fetch_yield_series(name)
    if df is None or df.empty:
        return {
            "symbol": item["symbol"],
            "name": name,
            "asset_type": "bond_yield",
            "market": item.get("market"),
            "range": chart_range.value,
            "interval": "daily",
            "unit": "percent",
            "note": "国债收益率(%)",
            "points": [],
        }

    df = df.tail(days)
    points = []
    for _, row in df.iterrows():
        t = str(row.get("date", ""))[:10]
        y = _safe_float(row.get("close"))
        points.append(
            {
                "time": t,
                "price": y,
                "open": _safe_float(row.get("open")),
                "close": y,
                "high": _safe_float(row.get("high")),
                "low": _safe_float(row.get("low")),
            }
        )

    return {
        "symbol": item["symbol"],
        "name": name,
        "asset_type": "bond_yield",
        "market": item.get("market"),
        "range": chart_range.value,
        "interval": "daily",
        "unit": "percent",
        "note": "Y 轴为收益率(%)，不是股票价格指数",
        "points": points,
    }
