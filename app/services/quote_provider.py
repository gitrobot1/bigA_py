import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from typing import Callable

import akshare as ak
import pandas as pd

from app.services.quote_cache import QuoteSnapshot
from app.services.types import AssetType

logger = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=3)
_estimate_executor = ThreadPoolExecutor(max_workers=8)
_MAX_RETRIES = 2
_RETRY_DELAY = 2.0

_NO_PROXY_ENV = {
    "HTTP_PROXY": "",
    "HTTPS_PROXY": "",
    "http_proxy": "",
    "https_proxy": "",
    "ALL_PROXY": "",
    "all_proxy": "",
    "NO_PROXY": "*",
    "no_proxy": "*",
}
for _k, _v in _NO_PROXY_ENV.items():
    os.environ[_k] = _v

GOLD_SYMBOLS = {
    "Au99.99": "黄金9999",
    "Au(T+D)": "黄金T+D",
    "Ag(T+D)": "白银T+D",
}

_sina_spot_cache: pd.DataFrame | None = None
_tx_spot_cache: pd.DataFrame | None = None


def _safe_float(value, default: float = 0.0) -> float:
    try:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _run_sync(fn, *args, **kwargs):
    def _call():
        saved = {k: os.environ.get(k) for k in _NO_PROXY_ENV}
        os.environ.update(_NO_PROXY_ENV)
        try:
            return fn(*args, **kwargs)
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    return _executor.submit(_call).result()


def _run_sync_timeout(fn, *args, timeout: float = 20.0, **kwargs):
    """带超时的同步调用，避免外部数据源无响应时阻塞接口。"""

    def _call():
        saved = {k: os.environ.get(k) for k in _NO_PROXY_ENV}
        os.environ.update(_NO_PROXY_ENV)
        try:
            return fn(*args, **kwargs)
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    fut = _estimate_executor.submit(_call)
    try:
        return fut.result(timeout=timeout)
    except TimeoutError as e:
        raise TimeoutError(f"数据源请求超时({timeout}s)") from e


def _with_retry(label: str, fn: Callable, *args, **kwargs):
    last_err: Exception | None = None
    for attempt in range(_MAX_RETRIES + 1):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            last_err = e
            if attempt < _MAX_RETRIES:
                logger.debug("%s 失败，%ss 后重试(%s/%s): %s", label, _RETRY_DELAY, attempt + 1, _MAX_RETRIES, e)
                time.sleep(_RETRY_DELAY)
    raise last_err  # type: ignore[misc]


def normalize_stock_symbol(symbol: str) -> str:
    """统一为 6 位数字代码"""
    s = symbol.strip().lower()
    s = re.sub(r"^(sh|sz|bj)", "", s)
    return s.zfill(6) if s.isdigit() else symbol


def stock_symbol_variants(symbol: str) -> list[str]:
    code = normalize_stock_symbol(symbol)
    if not code.isdigit() or len(code) != 6:
        return [symbol]
    prefix = "sh" if code.startswith("6") else "sz"
    if code.startswith(("4", "8")):
        prefix = "bj"
    return [code, f"{prefix}{code}", f"{prefix.upper()}{code}"]


def _match_code(series: pd.Series, symbol: str) -> pd.Series:
    variants = set(stock_symbol_variants(symbol))
    normalized = series.astype(str).str.lower().str.replace(r"^(sh|sz|bj)", "", regex=True)
    return series.astype(str).str.lower().isin({v.lower() for v in variants}) | (normalized == normalize_stock_symbol(symbol))


# ---------- 指数 ----------

INDEX_NAMES = ("上证指数", "深证成指", "创业板指", "沪深300", "中证500", "科创50")


def _extract_indices_from_df(df: pd.DataFrame, source: str) -> list[dict]:
    if df is None or df.empty or "名称" not in df.columns:
        return []
    result = []
    for name in INDEX_NAMES:
        subset = df[df["名称"].astype(str) == name]
        if subset.empty:
            continue
        row = subset.iloc[0]
        result.append(
            {
                "symbol": str(row.get("代码", "")),
                "name": name,
                "price": _safe_float(row.get("最新价")),
                "change_pct": _safe_float(row.get("涨跌幅")),
                "change_amount": _safe_float(row.get("涨跌额")),
                "volume": _safe_float(row.get("成交量")),
                "amount": _safe_float(row.get("成交额")),
                "data_source": source,
            }
        )
    return result


def _fetch_indices_em() -> list[dict]:
    # 沪深重要指数含上证/深证/创业板/沪深300 等
    df = _run_sync(ak.stock_zh_index_spot_em, symbol="沪深重要指数")
    return _extract_indices_from_df(df, "em_spot")


def _fetch_indices_sina() -> list[dict]:
    df = _run_sync(ak.stock_zh_index_spot_sina)
    return _extract_indices_from_df(df, "sina")


def fetch_indices() -> list[dict]:
    """多源拉取指数；周末东财常失败，新浪通常仍可返回上一交易日收盘。"""
    for label, fetcher in [("东财", _fetch_indices_em), ("新浪", _fetch_indices_sina)]:
        try:
            items = _with_retry(f"指数@{label}", fetcher)
            if items:
                logger.info("指数行情来自 %s，共 %d 条", label, len(items))
                return items
        except Exception as e:
            logger.warning("指数源 %s 失败: %s", label, e)
    return []


# ---------- A 股多源降级 ----------


def _quote_from_em_hist(symbol: str) -> QuoteSnapshot | None:
    code = normalize_stock_symbol(symbol)
    end = datetime.now().strftime("%Y%m%d")
    start = (datetime.now() - timedelta(days=10)).strftime("%Y%m%d")
    df = _run_sync(ak.stock_zh_a_hist, symbol=code, period="daily", start_date=start, end_date=end, adjust="")
    if df is None or df.empty:
        return None
    row = df.iloc[-1]
    price = _safe_float(row.get("收盘"))
    change_pct = _safe_float(row.get("涨跌幅"))
    return QuoteSnapshot(
        symbol=code,
        name=str(row.get("股票代码", code)),
        asset_type=AssetType.STOCK.value,
        price=price,
        change_pct=change_pct,
        change_amount=_safe_float(row.get("涨跌额")),
        volume=_safe_float(row.get("成交量")),
        amount=_safe_float(row.get("成交额")),
        open_price=_safe_float(row.get("开盘")),
        high=_safe_float(row.get("最高")),
        low=_safe_float(row.get("最低")),
        prev_close=price - _safe_float(row.get("涨跌额")),
        data_source="em_daily",
        updated_at=datetime.utcnow(),
    )


def _get_sina_spot_table() -> pd.DataFrame:
    global _sina_spot_cache
    if _sina_spot_cache is None:
        _sina_spot_cache = _run_sync(ak.stock_zh_a_spot)
    return _sina_spot_cache


def _quote_from_sina_spot(symbol: str) -> QuoteSnapshot | None:
    df = _get_sina_spot_table()
    subset = df[_match_code(df["代码"], symbol)]
    if subset.empty:
        return None
    row = subset.iloc[0]
    code = normalize_stock_symbol(str(row["代码"]))
    price = _safe_float(row.get("最新价"))
    change_pct = _safe_float(row.get("涨跌幅"))
    return QuoteSnapshot(
        symbol=code,
        name=str(row.get("名称", code)),
        asset_type=AssetType.STOCK.value,
        price=price,
        change_pct=change_pct,
        change_amount=_safe_float(row.get("涨跌额")),
        volume=_safe_float(row.get("成交量")),
        amount=_safe_float(row.get("成交额")),
        open_price=_safe_float(row.get("今开")),
        high=_safe_float(row.get("最高")),
        low=_safe_float(row.get("最低")),
        prev_close=_safe_float(row.get("昨收")),
        data_source="sina",
        updated_at=datetime.utcnow(),
    )


def _get_tx_spot_table() -> pd.DataFrame:
    global _tx_spot_cache
    if _tx_spot_cache is None:
        _tx_spot_cache = _run_sync(ak.stock_zh_a_spot_tx)
    return _tx_spot_cache


def _quote_from_tx_spot(symbol: str) -> QuoteSnapshot | None:
    df = _get_tx_spot_table()
    code_col = "代码" if "代码" in df.columns else df.columns[0]
    subset = df[_match_code(df[code_col], symbol)]
    if subset.empty:
        return None
    row = subset.iloc[0]
    code = normalize_stock_symbol(str(row.get(code_col, symbol)))
    price = _safe_float(row.get("最新价") or row.get("price"))
    change_pct = _safe_float(row.get("涨跌幅") or row.get("涨跌幅(%)"))
    return QuoteSnapshot(
        symbol=code,
        name=str(row.get("名称", code)),
        asset_type=AssetType.STOCK.value,
        price=price,
        change_pct=change_pct,
        change_amount=_safe_float(row.get("涨跌额")),
        open_price=_safe_float(row.get("今开")),
        high=_safe_float(row.get("最高")),
        low=_safe_float(row.get("最低")),
        prev_close=_safe_float(row.get("昨收")),
        data_source="tencent",
        updated_at=datetime.utcnow(),
    )


def _xq_symbol(symbol: str) -> str:
    code = normalize_stock_symbol(symbol)
    return f"SH{code}" if code.startswith("6") else f"SZ{code}"


def _quote_from_xueqiu(symbol: str) -> QuoteSnapshot | None:
    df = _run_sync(ak.stock_individual_spot_xq, symbol=_xq_symbol(symbol))
    if df is None or df.empty:
        return None
    data = {str(row["item"]): row["value"] for _, row in df.iterrows()}
    code = normalize_stock_symbol(symbol)
    price = _safe_float(data.get("现价") or data.get("最新价"))
    change_pct = _safe_float(data.get("涨幅") or data.get("涨跌幅"))
    return QuoteSnapshot(
        symbol=code,
        name=str(data.get("名称", code)),
        asset_type=AssetType.STOCK.value,
        price=price,
        change_pct=change_pct,
        data_source="xueqiu",
        updated_at=datetime.utcnow(),
    )


def _quote_from_em_bid(symbol: str) -> QuoteSnapshot | None:
    code = normalize_stock_symbol(symbol)
    df = _run_sync(ak.stock_bid_ask_em, symbol=code)
    if df is None or df.empty:
        return None
    data = {str(row["item"]): row["value"] for _, row in df.iterrows()}
    price = _safe_float(data.get("最新") or data.get("最新价"))
    if price <= 0:
        return None
    return QuoteSnapshot(
        symbol=code,
        name=str(data.get("名称", code)),
        asset_type=AssetType.STOCK.value,
        price=price,
        change_pct=_safe_float(data.get("涨幅") or data.get("涨跌幅")),
        data_source="em_bid",
        updated_at=datetime.utcnow(),
    )


def _quote_from_em_spot_batch(symbol: str) -> QuoteSnapshot | None:
    df = _run_sync(ak.stock_zh_a_spot_em)
    subset = df[df["代码"].astype(str).str.zfill(6) == normalize_stock_symbol(symbol)]
    if subset.empty:
        return None
    row = subset.iloc[0]
    price = _safe_float(row.get("最新价"))
    change_pct = _safe_float(row.get("涨跌幅"))
    prev = _safe_float(row.get("昨收")) or (price / (1 + change_pct / 100) if change_pct else price)
    return QuoteSnapshot(
        symbol=normalize_stock_symbol(str(row["代码"])),
        name=str(row.get("名称", symbol)),
        asset_type=AssetType.STOCK.value,
        price=price,
        change_pct=change_pct,
        change_amount=_safe_float(row.get("涨跌额")),
        volume=_safe_float(row.get("成交量")),
        amount=_safe_float(row.get("成交额")),
        open_price=_safe_float(row.get("今开")),
        high=_safe_float(row.get("最高")),
        low=_safe_float(row.get("最低")),
        prev_close=prev,
        data_source="em_spot",
        updated_at=datetime.utcnow(),
    )


_STOCK_FETCHERS: list[tuple[str, Callable[[str], QuoteSnapshot | None]]] = [
    ("em_daily", _quote_from_em_hist),
    ("sina", _quote_from_sina_spot),
    ("tencent", _quote_from_tx_spot),
    ("xueqiu", _quote_from_xueqiu),
    ("em_bid", _quote_from_em_bid),
    ("em_spot", _quote_from_em_spot_batch),
]

# 快速模式：单只接口，不拉新浪/腾讯全市场表
_FAST_STOCK_FETCHERS: list[tuple[str, Callable[[str], QuoteSnapshot | None]]] = [
    ("em_daily", _quote_from_em_hist),
    ("em_bid", _quote_from_em_bid),
    ("xueqiu", _quote_from_xueqiu),
]


def fetch_single_stock(symbol: str, *, fast: bool = False) -> QuoteSnapshot | None:
    """按优先级依次尝试各数据源，成功即返回。"""
    code = normalize_stock_symbol(symbol)
    chain = _FAST_STOCK_FETCHERS if fast else _STOCK_FETCHERS
    for source_name, fetcher in chain:
        try:
            quote = _with_retry(f"A股{code}@{source_name}", fetcher, code)
            if quote and quote.price > 0:
                logger.info("A股 %s 行情来自 %s", code, source_name)
                return quote
        except Exception as e:
            logger.debug("A股 %s 源 %s 失败: %s", code, source_name, e)
    logger.warning("A股 %s 所有数据源均失败", code)
    return None


def _fetch_stocks_fast(codes: list[str]) -> list[QuoteSnapshot]:
    """快速拉取：先单只轻量接口，仍失败则最多拉一次新浪全表补全。"""
    quotes: dict[str, QuoteSnapshot] = {}
    for code in codes:
        q = fetch_single_stock(code, fast=True)
        if q:
            quotes[code] = q
    missing = [c for c in codes if c not in quotes]
    if missing:
        try:
            df = _get_sina_spot_table()
            for code in missing:
                subset = df[_match_code(df["代码"], code)]
                if subset.empty:
                    continue
                row = subset.iloc[0]
                quotes[code] = QuoteSnapshot(
                    symbol=code,
                    name=str(row.get("名称", code)),
                    asset_type=AssetType.STOCK.value,
                    price=_safe_float(row.get("最新价")),
                    change_pct=_safe_float(row.get("涨跌幅")),
                    change_amount=_safe_float(row.get("涨跌额")),
                    volume=_safe_float(row.get("成交量")),
                    amount=_safe_float(row.get("成交额")),
                    open_price=_safe_float(row.get("今开")),
                    high=_safe_float(row.get("最高")),
                    low=_safe_float(row.get("最低")),
                    prev_close=_safe_float(row.get("昨收")),
                    data_source="sina",
                    updated_at=datetime.utcnow(),
                )
        except Exception as e:
            logger.warning("快速模式新浪补全失败: %s", e)
    return list(quotes.values())


def _quote_from_em_spot_df(df: pd.DataFrame, code: str) -> QuoteSnapshot | None:
    subset = df[df["代码"].astype(str).str.zfill(6) == code]
    if subset.empty:
        return None
    row = subset.iloc[0]
    price = _safe_float(row.get("最新价"))
    change_pct = _safe_float(row.get("涨跌幅"))
    prev = _safe_float(row.get("昨收")) or (price / (1 + change_pct / 100) if change_pct else price)
    return QuoteSnapshot(
        symbol=code,
        name=str(row.get("名称", code)),
        asset_type=AssetType.STOCK.value,
        price=price,
        change_pct=change_pct,
        change_amount=_safe_float(row.get("涨跌额")),
        volume=_safe_float(row.get("成交量")),
        amount=_safe_float(row.get("成交额")),
        open_price=_safe_float(row.get("今开")),
        high=_safe_float(row.get("最高")),
        low=_safe_float(row.get("最低")),
        prev_close=prev,
        data_source="em_spot_batch",
        updated_at=datetime.utcnow(),
    )


def _quote_from_sina_df(df: pd.DataFrame, code: str) -> QuoteSnapshot | None:
    subset = df[_match_code(df["代码"], code)]
    if subset.empty:
        return None
    row = subset.iloc[0]
    return QuoteSnapshot(
        symbol=code,
        name=str(row.get("名称", code)),
        asset_type=AssetType.STOCK.value,
        price=_safe_float(row.get("最新价")),
        change_pct=_safe_float(row.get("涨跌幅")),
        change_amount=_safe_float(row.get("涨跌额")),
        volume=_safe_float(row.get("成交量")),
        amount=_safe_float(row.get("成交额")),
        open_price=_safe_float(row.get("今开")),
        high=_safe_float(row.get("最高")),
        low=_safe_float(row.get("最低")),
        prev_close=_safe_float(row.get("昨收")),
        data_source="sina",
        updated_at=datetime.utcnow(),
    )


def _quote_from_em_hist_once(code: str) -> QuoteSnapshot | None:
    end = datetime.now().strftime("%Y%m%d")
    start = (datetime.now() - timedelta(days=10)).strftime("%Y%m%d")
    try:
        df = _run_sync_timeout(
            ak.stock_zh_a_hist,
            symbol=code,
            period="daily",
            start_date=start,
            end_date=end,
            adjust="",
            timeout=8,
        )
    except TimeoutError:
        return None
    if df is None or df.empty:
        return None
    row = df.iloc[-1]
    price = _safe_float(row.get("收盘"))
    change_pct = _safe_float(row.get("涨跌幅"))
    return QuoteSnapshot(
        symbol=code,
        name=str(row.get("股票代码", code)),
        asset_type=AssetType.STOCK.value,
        price=price,
        change_pct=change_pct,
        change_amount=_safe_float(row.get("涨跌额")),
        volume=_safe_float(row.get("成交量")),
        amount=_safe_float(row.get("成交额")),
        open_price=_safe_float(row.get("开盘")),
        high=_safe_float(row.get("最高")),
        low=_safe_float(row.get("最低")),
        prev_close=price - _safe_float(row.get("涨跌额")),
        data_source="em_daily",
        updated_at=datetime.utcnow(),
    )


def fetch_stock_quotes_for_estimate(symbols: list[str]) -> dict[str, QuoteSnapshot]:
    """
    基金预估专用：优先缓存与全表批量匹配，缺失项并发单次拉取，不做逐只多源重试。
    """
    from app.services.quote_cache import quote_cache

    codes = list(dict.fromkeys(normalize_stock_symbol(s) for s in symbols if s))
    result: dict[str, QuoteSnapshot] = {}

    for code in codes:
        cached = quote_cache.get_quote(code, AssetType.STOCK.value)
        if cached:
            result[code] = cached

    missing = [c for c in codes if c not in result]
    if not missing:
        return result

    for label, fetch_table, mapper in [
        ("东财全市场", lambda: _run_sync_timeout(ak.stock_zh_a_spot_em, timeout=12), _quote_from_em_spot_df),
    ]:
        if not missing:
            break
        try:
            df = fetch_table()
            before = len(result)
            still: list[str] = []
            for code in missing:
                q = mapper(df, code)
                if q:
                    result[code] = q
                else:
                    still.append(code)
            missing = still
            if len(result) > before:
                logger.info("预估行情 %s 补全 %d 只", label, len(result) - before)
        except Exception as e:
            logger.warning("预估行情 %s 失败: %s", label, e)

    if missing and _sina_spot_cache is not None:
        try:
            before = len(result)
            still: list[str] = []
            for code in missing:
                q = _quote_from_sina_df(_sina_spot_cache, code)
                if q:
                    result[code] = q
                else:
                    still.append(code)
            missing = still
            if len(result) > before:
                logger.info("预估行情 新浪缓存 补全 %d 只", len(result) - before)
        except Exception as e:
            logger.warning("预估行情 新浪缓存 失败: %s", e)

    if not missing:
        return result

    def _fetch_one(code: str) -> QuoteSnapshot | None:
        return _quote_from_em_hist_once(code)

    pool = ThreadPoolExecutor(max_workers=min(6, len(missing)))
    futures = {pool.submit(_fetch_one, code): code for code in missing}
    try:
        for fut in as_completed(futures, timeout=18):
            code = futures[fut]
            try:
                q = fut.result()
                if q:
                    result[code] = q
            except Exception as e:
                logger.debug("预估单股 %s 失败: %s", code, e)
    except TimeoutError:
        logger.warning("预估并发拉取超时，已返回部分重仓股行情")
    finally:
        pool.shutdown(wait=False, cancel_futures=True)

    return result


def fetch_stock_quotes(symbols: list[str], *, fast: bool = True) -> list[QuoteSnapshot]:
    if not symbols:
        return []
    codes = [normalize_stock_symbol(s) for s in symbols]
    if fast:
        return _fetch_stocks_fast(codes)

    quotes: dict[str, QuoteSnapshot] = {}
    try:
        df = _with_retry("东财A股全市场", _run_sync, ak.stock_zh_a_spot_em)
        for code in codes:
            subset = df[df["代码"].astype(str).str.zfill(6) == code]
            if not subset.empty:
                row = subset.iloc[0]
                quotes[code] = QuoteSnapshot(
                    symbol=code,
                    name=str(row.get("名称", code)),
                    asset_type=AssetType.STOCK.value,
                    price=_safe_float(row.get("最新价")),
                    change_pct=_safe_float(row.get("涨跌幅")),
                    change_amount=_safe_float(row.get("涨跌额")),
                    volume=_safe_float(row.get("成交量")),
                    amount=_safe_float(row.get("成交额")),
                    open_price=_safe_float(row.get("今开")),
                    high=_safe_float(row.get("最高")),
                    low=_safe_float(row.get("最低")),
                    data_source="em_spot_batch",
                    updated_at=datetime.utcnow(),
                )
        if len(quotes) == len(codes):
            return list(quotes.values())
    except Exception as e:
        logger.warning("东财批量 A 股失败，改为逐只多源拉取: %s", e)

    for code in codes:
        if code in quotes:
            continue
        q = fetch_single_stock(code, fast=False)
        if q:
            quotes[code] = q
    return list(quotes.values())


# ---------- 基金 ETF ----------


def _quote_from_etf_row(row: pd.Series) -> QuoteSnapshot:
    price = _safe_float(row.get("最新价"))
    return QuoteSnapshot(
        symbol=str(row.get("代码", "")),
        name=str(row.get("名称", "")),
        asset_type=AssetType.FUND.value,
        price=price,
        change_pct=_safe_float(row.get("涨跌幅")),
        change_amount=_safe_float(row.get("涨跌额")),
        volume=_safe_float(row.get("成交量")),
        amount=_safe_float(row.get("成交额")),
        open_price=_safe_float(row.get("今开")),
        high=_safe_float(row.get("最高")),
        low=_safe_float(row.get("最低")),
        prev_close=_safe_float(row.get("昨收")),
        data_source="em_etf",
        updated_at=datetime.utcnow(),
    )


def fetch_fund_quotes(symbols: list[str]) -> list[QuoteSnapshot]:
    if not symbols:
        return []
    quotes: dict[str, QuoteSnapshot] = {}
    try:
        df = _with_retry("东财ETF", _run_sync, ak.fund_etf_spot_em)
        for sym in symbols:
            subset = df[df["代码"].astype(str) == str(sym)]
            if not subset.empty:
                quotes[sym] = _quote_from_etf_row(subset.iloc[0])
        if len(quotes) == len(symbols):
            return list(quotes.values())
    except Exception as e:
        logger.warning("东财 ETF 批量失败: %s", e)

    for sym in symbols:
        if sym in quotes:
            continue
        try:
            end = datetime.now().strftime("%Y%m%d")
            start = (datetime.now() - timedelta(days=10)).strftime("%Y%m%d")
            df = _run_sync(
                ak.fund_etf_hist_em,
                symbol=sym,
                period="daily",
                start_date=start,
                end_date=end,
                adjust="",
            )
            if df is not None and not df.empty:
                row = df.iloc[-1]
                quotes[sym] = QuoteSnapshot(
                    symbol=sym,
                    name=sym,
                    asset_type=AssetType.FUND.value,
                    price=_safe_float(row.get("收盘")),
                    change_pct=_safe_float(row.get("涨跌幅")),
                    data_source="em_etf_daily",
                    updated_at=datetime.utcnow(),
                )
        except Exception as e:
            logger.warning("基金 %s 日线降级失败: %s", sym, e)
    return list(quotes.values())


# ---------- 黄金 ----------


def fetch_gold_quotes(symbols: list[str]) -> list[QuoteSnapshot]:
    quotes = []
    for symbol in symbols:
        try:
            df = _with_retry(f"黄金{symbol}", _run_sync, ak.spot_hist_sge, symbol=symbol)
            if df is None or df.empty:
                continue
            last = df.iloc[-1]
            close = _safe_float(last.get("close"))
            open_p = _safe_float(last.get("open"))
            change_pct = ((close - open_p) / open_p * 100) if open_p else 0.0
            quotes.append(
                QuoteSnapshot(
                    symbol=symbol,
                    name=GOLD_SYMBOLS.get(symbol, symbol),
                    asset_type=AssetType.GOLD.value,
                    price=close,
                    change_pct=round(change_pct, 2),
                    open_price=open_p,
                    high=_safe_float(last.get("high")),
                    low=_safe_float(last.get("low")),
                    prev_close=open_p,
                    data_source="sge",
                    updated_at=datetime.utcnow(),
                )
            )
        except Exception as e:
            logger.warning("黄金 %s 拉取失败: %s", symbol, e)
    return quotes


# ---------- 搜索 ----------

_search_cache: dict[str, tuple[float, list[dict]]] = {}
_fund_name_table_cache: tuple[float, pd.DataFrame] | None = None
_FUND_NAME_CACHE_TTL = 86400  # 24h，基金名录变动不频繁


def _get_fund_name_table() -> pd.DataFrame | None:
    """东财全市场基金名录（含场外开放式、ETF 等），内存缓存。"""
    global _fund_name_table_cache
    now = time.time()
    if _fund_name_table_cache and now - _fund_name_table_cache[0] < _FUND_NAME_CACHE_TTL:
        return _fund_name_table_cache[1]
    try:
        df = _run_sync_timeout(ak.fund_name_em, timeout=45)
        if df is not None and not df.empty:
            _fund_name_table_cache = (now, df)
            logger.info("基金名录已加载，共 %d 条", len(df))
            return df
    except Exception as e:
        logger.warning("加载基金名录失败: %s", e)
    return _fund_name_table_cache[1] if _fund_name_table_cache else None


def warmup_fund_name_cache() -> None:
    """应用启动时可调用，避免首次搜索等待过久。"""
    _get_fund_name_table()


def _search_funds_from_name_table(keyword: str, limit: int) -> list[dict]:
    df = _get_fund_name_table()
    if df is None or df.empty:
        return []
    results: list[dict] = []
    code_col = "基金代码"
    name_col = "基金简称"
    if code_col not in df.columns or name_col not in df.columns:
        return []
    codes = df[code_col].astype(str)
    names = df[name_col].astype(str)
    mask = codes.str.contains(keyword, na=False, regex=False) | names.str.contains(keyword, na=False, regex=False)
    for _, row in df[mask].head(limit).iterrows():
        sym = str(row[code_col]).strip().zfill(6)
        results.append(
            {
                "symbol": sym,
                "name": str(row[name_col]),
                "asset_type": AssetType.FUND.value,
            }
        )
    return results


def _search_funds_from_etf_spot(keyword: str, limit: int) -> list[dict]:
    results: list[dict] = []
    try:
        df = _run_sync_timeout(ak.fund_etf_spot_em, timeout=30)
        mask = df["代码"].astype(str).str.contains(keyword, na=False, regex=False) | df["名称"].astype(
            str
        ).str.contains(keyword, na=False, regex=False)
        for _, row in df[mask].head(limit).iterrows():
            sym = str(row["代码"]).strip()
            if any(r["symbol"] == sym for r in results):
                continue
            results.append(
                {"symbol": sym, "name": str(row["名称"]), "asset_type": AssetType.FUND.value}
            )
    except Exception as e:
        logger.warning("搜索场内 ETF 列表失败: %s", e)
    return results


def search_symbols(keyword: str, asset_type: AssetType | None = None, limit: int = 20) -> list[dict]:
    keyword = keyword.strip()
    if not keyword:
        return []

    from app.config import get_settings

    cache_key = f"{keyword.lower()}|{asset_type}|{limit}"
    ttl = get_settings().SEARCH_CACHE_SECONDS
    now = time.time()
    cached = _search_cache.get(cache_key)
    if cached and now - cached[0] < ttl:
        return list(cached[1])

    results: list[dict] = []
    types = [asset_type] if asset_type else [AssetType.STOCK, AssetType.FUND, AssetType.GOLD]

    # 基金：先查全市场名录（含场外开放式），再补充场内 ETF 行情表
    if AssetType.FUND in types and len(results) < limit:
        name_hits = _search_funds_from_name_table(keyword, limit)
        for item in name_hits:
            if not any(r["symbol"] == item["symbol"] for r in results):
                results.append(item)
            if len(results) >= limit:
                break
        # 名录无结果时再拉场内 ETF 全表（较慢）
        if not name_hits and len(results) < limit:
            for item in _search_funds_from_etf_spot(keyword, limit - len(results)):
                if not any(r["symbol"] == item["symbol"] for r in results):
                    results.append(item)
                if len(results) >= limit:
                    break

    # 仅在不限定为 fund 时搜 A 股（避免每次先拉全市场拖慢基金搜索）
    if AssetType.STOCK in types and asset_type != AssetType.FUND and len(results) < limit:
        for fetch_table, source in [
            (lambda: _run_sync_timeout(ak.stock_zh_a_spot_em, timeout=12), "em"),
        ]:
            if len(results) >= limit:
                break
            try:
                df = fetch_table()
                code_col = "代码"
                name_col = "名称"
                mask = df[code_col].astype(str).str.contains(keyword, na=False, regex=False) | df[
                    name_col
                ].astype(str).str.contains(keyword, na=False, regex=False)
                for _, row in df[mask].head(limit - len(results)).iterrows():
                    sym = normalize_stock_symbol(str(row[code_col]))
                    if any(r["symbol"] == sym for r in results):
                        continue
                    results.append(
                        {"symbol": sym, "name": str(row[name_col]), "asset_type": AssetType.STOCK.value}
                    )
            except Exception as e:
                logger.warning("搜索 A 股(%s)失败: %s", source, e)

    if AssetType.GOLD in types and len(results) < limit:
        for sym, name in GOLD_SYMBOLS.items():
            if keyword in sym or keyword in name:
                results.append({"symbol": sym, "name": name, "asset_type": AssetType.GOLD.value})
                if len(results) >= limit:
                    break
    final = results[:limit]
    _search_cache[cache_key] = (now, final)
    return final


def clear_spot_caches() -> None:
    """新一轮全量刷新前可清空表缓存"""
    global _sina_spot_cache, _tx_spot_cache
    _sina_spot_cache = None
    _tx_spot_cache = None
