"""基于最近披露重仓股与当日 A 股涨跌幅，估算基金今日涨跌（仅供参考）。"""

import logging
import re
import time
from datetime import datetime

import akshare as ak
import pandas as pd

from app.services.quote_cache import QuoteSnapshot, quote_cache
from app.services.quote_provider import (
    _run_sync_timeout,
    fetch_stock_quotes_for_estimate,
    normalize_stock_symbol,
)
from app.services.types import AssetType

logger = logging.getLogger(__name__)

DISCLAIMER = (
    "基于基金最近一期季报/半年报披露的股票重仓与占净值比例加权估算，"
    "未包含债券、现金及披露后调仓影响，与官方净值可能存在偏差，仅供参考。"
)

_HOLDINGS_CACHE: dict[str, tuple[float, dict]] = {}
_HOLDINGS_TTL_SECONDS = 6 * 3600


def _normalize_hold_year(year: int | None) -> list[int]:
    y = year or datetime.now().year
    return [y, y - 1]


def _parse_quarter_key(label: str) -> tuple[int, int]:
    """2026年1季度股票投资明细 -> (2026, 1)"""
    m = re.search(r"(\d{4})年(\d)季度", str(label))
    if m:
        return int(m.group(1)), int(m.group(2))
    return (0, 0)


def _load_holdings_from_api(symbol: str, *, top_n: int) -> dict:
    sym = str(symbol).strip()
    last_err: Exception | None = None

    for year in _normalize_hold_year(None):
        try:
            df = _run_sync_timeout(ak.fund_portfolio_hold_em, symbol=sym, date=str(year), timeout=25)
        except TimeoutError as e:
            last_err = e
            logger.warning("基金 %s %s 年持仓超时: %s", sym, year, e)
            continue
        except Exception as e:
            last_err = e
            logger.debug("基金 %s %s 年持仓失败: %s", sym, year, e)
            continue
        if df is None or df.empty:
            continue

        periods = df["季度"].astype(str).unique().tolist()
        latest_label = max(periods, key=_parse_quarter_key)
        sub = df[df["季度"].astype(str) == latest_label].copy()
        sub["占净值比例"] = pd.to_numeric(sub["占净值比例"], errors="coerce").fillna(0)
        sub = sub[sub["占净值比例"] > 0].sort_values("占净值比例", ascending=False)

        holdings: list[dict] = []
        for _, row in sub.head(top_n).iterrows():
            code = normalize_stock_symbol(str(row.get("股票代码", "")))
            if not code.isdigit() or len(code) != 6:
                continue
            holdings.append(
                {
                    "stock_code": code,
                    "stock_name": str(row.get("股票名称", "")),
                    "weight_pct": float(row["占净值比例"]),
                }
            )

        if not holdings:
            continue

        stock_weight_pct = float(sub["占净值比例"].sum())
        return {
            "symbol": sym,
            "report_period": latest_label,
            "report_year": year,
            "holdings": holdings,
            "holding_count": len(holdings),
            "stock_weight_pct": round(min(stock_weight_pct, 100.0), 2),
            "data_source": "em_portfolio",
        }

    raise ValueError(f"无法获取基金 {sym} 的股票持仓（可能为非股票型基金或数据源暂不可用）") from last_err


def fetch_latest_stock_holdings(symbol: str, *, top_n: int = 20) -> dict:
    """拉取基金最近一期披露的股票重仓（带内存缓存）。"""
    sym = str(symbol).strip()
    cache_key = f"{sym}:{top_n}"
    now = time.time()
    cached = _HOLDINGS_CACHE.get(cache_key)
    if cached and now - cached[0] < _HOLDINGS_TTL_SECONDS:
        return cached[1]

    data = _load_holdings_from_api(sym, top_n=top_n)
    _HOLDINGS_CACHE[cache_key] = (now, data)
    return data


def _build_estimate(
    meta: dict,
    quotes_by_code: dict[str, QuoteSnapshot],
    *,
    name: str | None = None,
) -> dict:
    holdings = meta["holdings"]
    estimated_change_pct = 0.0
    covered_weight = 0.0
    contributions: list[dict] = []
    missing: list[str] = []

    for h in holdings:
        q = quotes_by_code.get(h["stock_code"])
        if not q:
            missing.append(h["stock_code"])
            contributions.append(
                {
                    "stock_code": h["stock_code"],
                    "stock_name": h["stock_name"],
                    "weight_pct": h["weight_pct"],
                    "change_pct": None,
                    "contribution_pct": None,
                    "price": None,
                    "data_source": None,
                }
            )
            continue

        change_pct = float(q.change_pct)
        contribution = h["weight_pct"] * change_pct / 100.0
        estimated_change_pct += contribution
        covered_weight += h["weight_pct"]
        contributions.append(
            {
                "stock_code": h["stock_code"],
                "stock_name": h["stock_name"],
                "weight_pct": h["weight_pct"],
                "change_pct": round(change_pct, 4),
                "contribution_pct": round(contribution, 4),
                "price": float(q.price),
                "data_source": q.data_source,
            }
        )

    actual = quote_cache.get_quote(meta["symbol"], AssetType.FUND.value)
    actual_change_pct = float(actual.change_pct) if actual else None
    diff_pct = None
    if actual_change_pct is not None:
        diff_pct = round(actual_change_pct - estimated_change_pct, 4)

    error = None
    if missing and covered_weight <= 0:
        error = (
            f"重仓股行情暂不可用（{len(missing)}/{len(holdings)} 只未取到），"
            "请检查网络/代理或稍后重试；可先执行 POST /market/refresh 刷新行情缓存。"
        )
    elif missing:
        error = f"部分重仓股行情缺失（{len(missing)}/{len(holdings)}），预估结果可能偏低。"

    return {
        "symbol": meta["symbol"],
        "name": name or (actual.name if actual else meta["symbol"]),
        "estimated_change_pct": round(estimated_change_pct, 4) if covered_weight > 0 else None,
        "actual_change_pct": round(actual_change_pct, 4) if actual_change_pct is not None else None,
        "estimate_vs_actual_pct": diff_pct,
        "covered_weight_pct": round(covered_weight, 2),
        "report_period": meta["report_period"],
        "stock_weight_pct": meta["stock_weight_pct"],
        "holding_count": meta["holding_count"],
        "missing_stock_count": len(missing),
        "missing_stocks": missing[:10],
        "contributions": contributions,
        "disclaimer": DISCLAIMER,
        "computed_at": datetime.utcnow().isoformat() + "Z",
        "error": error,
    }


def estimate_fund_today(
    symbol: str,
    *,
    top_n: int = 20,
    name: str | None = None,
    quotes_by_code: dict[str, QuoteSnapshot] | None = None,
) -> dict:
    """用最近披露重仓 × 当日个股涨跌幅，估算基金今日涨跌幅(%)。"""
    meta = fetch_latest_stock_holdings(symbol, top_n=top_n)
    codes = [h["stock_code"] for h in meta["holdings"]]
    if quotes_by_code is None:
        quotes_by_code = fetch_stock_quotes_for_estimate(codes)
    else:
        quotes_by_code = {k: v for k, v in quotes_by_code.items() if k in codes}
    return _build_estimate(meta, quotes_by_code, name=name)


def estimate_watchlist_funds(
    symbols: list[tuple[str, str | None]],
    *,
    top_n: int = 20,
) -> list[dict]:
    """批量估算自选基金；合并重仓股后一次性拉行情，避免逐只基金长时间阻塞。"""
    metas: list[tuple[str | None, dict]] = []
    all_codes: list[str] = []

    for symbol, name in symbols:
        try:
            meta = fetch_latest_stock_holdings(symbol, top_n=top_n)
            metas.append((name, meta))
            all_codes.extend(h["stock_code"] for h in meta["holdings"])
        except ValueError as e:
            metas.append(
                (
                    name,
                    {
                        "error_only": True,
                        "symbol": symbol,
                        "name": name or symbol,
                        "message": str(e),
                    },
                )
            )

    quotes_by_code = fetch_stock_quotes_for_estimate(all_codes) if all_codes else {}

    results: list[dict] = []
    for name, meta in metas:
        if meta.get("error_only"):
            results.append(
                {
                    "symbol": meta["symbol"],
                    "name": meta["name"],
                    "error": meta["message"],
                    "disclaimer": DISCLAIMER,
                    "computed_at": datetime.utcnow().isoformat() + "Z",
                }
            )
            continue
        try:
            results.append(_build_estimate(meta, quotes_by_code, name=name))
        except Exception as e:
            logger.warning("基金 %s 预估失败: %s", meta.get("symbol"), e)
            results.append(
                {
                    "symbol": meta["symbol"],
                    "name": name or meta["symbol"],
                    "error": f"估算失败: {e}",
                    "disclaimer": DISCLAIMER,
                    "computed_at": datetime.utcnow().isoformat() + "Z",
                }
            )
    return results
