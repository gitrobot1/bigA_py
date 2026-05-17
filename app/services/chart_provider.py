import logging
from datetime import datetime, timedelta
from enum import Enum

import akshare as ak
import pandas as pd

from app.services.quote_provider import _run_sync, _safe_float, normalize_stock_symbol

logger = logging.getLogger(__name__)


class ChartRange(str, Enum):
    TODAY = "today"
    ONE_MONTH = "1m"
    TWO_MONTHS = "2m"
    THREE_MONTHS = "3m"
    ONE_YEAR = "1y"
    THREE_YEARS = "3y"
    FIVE_YEARS = "5y"


# 按交易日估算 K 线条数（日线）
CHART_RANGE_TRADING_DAYS: dict[ChartRange, int] = {
    ChartRange.ONE_MONTH: 22,
    ChartRange.TWO_MONTHS: 44,
    ChartRange.THREE_MONTHS: 66,
    ChartRange.ONE_YEAR: 252,
    ChartRange.THREE_YEARS: 252 * 3,
    ChartRange.FIVE_YEARS: 252 * 5,
}


def trading_days_for_range(chart_range: ChartRange) -> int:
    if chart_range == ChartRange.TODAY:
        return 5
    return CHART_RANGE_TRADING_DAYS.get(chart_range, 66)


def _to_sina_prefix_symbol(symbol: str, asset_type: str) -> str:
    code = symbol.strip().lower()
    if code.startswith(("sh", "sz", "bj")):
        return code
    if asset_type == "fund":
        prefix = "sh" if code.startswith(("5", "6")) else "sz"
        return f"{prefix}{code}"
    # stock
    c = normalize_stock_symbol(symbol)
    prefix = "sh" if c.startswith("6") else "sz"
    if c.startswith(("4", "8")):
        prefix = "bj"
    return f"{prefix}{c}"


def _last_trading_date_from_minute(df: pd.DataFrame) -> str | None:
    if df is None or df.empty:
        return None
    col = "day" if "day" in df.columns else "时间" if "时间" in df.columns else None
    if not col:
        return None
    last = df[col].iloc[-1]
    if isinstance(last, str):
        return last[:10]
    return str(last)[:10]


def _df_to_intraday_points(df: pd.DataFrame) -> list[dict]:
    points = []
    time_col = "day" if "day" in df.columns else "时间"
    close_col = "close" if "close" in df.columns else "收盘"
    open_col = "open" if "open" in df.columns else "开盘"
    high_col = "high" if "high" in df.columns else "最高"
    low_col = "low" if "low" in df.columns else "最低"
    vol_col = "volume" if "volume" in df.columns else "成交量"

    for _, row in df.iterrows():
        t = str(row.get(time_col, ""))
        close = _safe_float(row.get(close_col))
        points.append(
            {
                "time": t,
                "price": close,
                "open": _safe_float(row.get(open_col)),
                "close": close,
                "high": _safe_float(row.get(high_col)),
                "low": _safe_float(row.get(low_col)),
                "volume": _safe_float(row.get(vol_col)),
            }
        )
    return points


def _df_to_daily_points(df: pd.DataFrame) -> list[dict]:
    points = []
    date_col = "date" if "date" in df.columns else "日期"
    for _, row in df.iterrows():
        d = row.get(date_col)
        if hasattr(d, "isoformat"):
            t = d.isoformat()
        else:
            t = str(d)[:10]
        close = _safe_float(row.get("close") or row.get("收盘"))
        open_p = _safe_float(row.get("open") or row.get("开盘"))
        prev = _safe_float(row.get("prev_close"))
        change_pct = None
        if prev and prev > 0:
            change_pct = round((close - prev) / prev * 100, 2)
        points.append(
            {
                "time": t,
                "price": close,
                "open": open_p,
                "close": close,
                "high": _safe_float(row.get("high") or row.get("最高")),
                "low": _safe_float(row.get("low") or row.get("最低")),
                "volume": _safe_float(row.get("volume") or row.get("成交量")),
                "change_pct": _safe_float(row.get("change_pct") or row.get("涨跌幅"), change_pct or 0.0)
                if (row.get("change_pct") is not None or row.get("涨跌幅") is not None)
                else change_pct,
            }
        )
    return points


def _fetch_stock_intraday(sina_symbol: str) -> tuple[list[dict], str | None]:
    df = _run_sync(ak.stock_zh_a_minute, symbol=sina_symbol, period="1", adjust="")
    if df is None or df.empty:
        try:
            code = normalize_stock_symbol(sina_symbol)
            end = datetime.now().strftime("%Y-%m-%d 15:00:00")
            start = datetime.now().strftime("%Y-%m-%d 09:30:00")
            df = _run_sync(
                ak.stock_zh_a_hist_min_em,
                symbol=code,
                start_date=start,
                end_date=end,
                period="1",
                adjust="",
            )
        except Exception as e:
            logger.warning("东财分钟线失败: %s", e)
            df = pd.DataFrame()

    if df is None or df.empty:
        return [], None

    trading_day = _last_trading_date_from_minute(df)
    if trading_day and "day" in df.columns:
        df = df[df["day"].astype(str).str.startswith(trading_day)]
    return _df_to_intraday_points(df), trading_day


def _fetch_stock_daily(sina_symbol: str, days: int) -> list[dict]:
    try:
        df = _run_sync(ak.stock_zh_a_daily, symbol=sina_symbol, adjust="qfq")
        if df is not None and not df.empty:
            df = df.tail(days)
            return _df_to_daily_points(df)
    except Exception as e:
        logger.warning("新浪日线失败: %s", e)

    code = normalize_stock_symbol(sina_symbol)
    end = datetime.now().strftime("%Y%m%d")
    start = (datetime.now() - timedelta(days=days + 10)).strftime("%Y%m%d")
    try:
        df = _run_sync(
            ak.stock_zh_a_hist,
            symbol=code,
            period="daily",
            start_date=start,
            end_date=end,
            adjust="qfq",
        )
        if df is not None and not df.empty:
            df = df.rename(
                columns={
                    "日期": "date",
                    "开盘": "open",
                    "收盘": "close",
                    "最高": "high",
                    "最低": "low",
                    "成交量": "volume",
                    "涨跌幅": "change_pct",
                }
            )
            return _df_to_daily_points(df.tail(days))
    except Exception as e:
        logger.warning("东财日线失败: %s", e)
    return []


def _fetch_fund_intraday(sina_symbol: str) -> tuple[list[dict], str | None]:
    code = sina_symbol.replace("sh", "").replace("sz", "")
    try:
        end = datetime.now().strftime("%Y-%m-%d 15:00:00")
        start = datetime.now().strftime("%Y-%m-%d 09:30:00")
        df = _run_sync(
            ak.fund_etf_hist_min_em,
            symbol=code,
            start_date=start,
            end_date=end,
            period="1",
            adjust="",
        )
        if df is not None and not df.empty:
            trading_day = _last_trading_date_from_minute(df)
            return _df_to_intraday_points(df), trading_day
    except Exception as e:
        logger.warning("ETF 分钟线失败: %s", e)
    return [], None


def _fetch_fund_daily(sina_symbol: str, days: int) -> list[dict]:
    try:
        df = _run_sync(ak.fund_etf_hist_sina, symbol=sina_symbol)
        if df is not None and not df.empty:
            return _df_to_daily_points(df.tail(days))
    except Exception as e:
        logger.warning("ETF 新浪日线失败: %s", e)

    code = sina_symbol.replace("sh", "").replace("sz", "")
    end = datetime.now().strftime("%Y%m%d")
    start = (datetime.now() - timedelta(days=days + 10)).strftime("%Y%m%d")
    try:
        df = _run_sync(
            ak.fund_etf_hist_em,
            symbol=code,
            period="daily",
            start_date=start,
            end_date=end,
            adjust="",
        )
        if df is not None and not df.empty:
            df = df.rename(
                columns={
                    "日期": "date",
                    "开盘": "open",
                    "收盘": "close",
                    "最高": "high",
                    "最低": "low",
                    "成交量": "volume",
                    "涨跌幅": "change_pct",
                }
            )
            return _df_to_daily_points(df.tail(days))
    except Exception as e:
        logger.warning("ETF 东财日线失败: %s", e)
    return []


def _fetch_gold_daily(symbol: str, days: int) -> list[dict]:
    try:
        df = _run_sync(ak.spot_hist_sge, symbol=symbol)
        if df is None or df.empty:
            return []
        df = df.tail(days)
        points = []
        for _, row in df.iterrows():
            t = str(row.get("date", ""))[:10]
            close = _safe_float(row.get("close"))
            open_p = _safe_float(row.get("open"))
            change_pct = ((close - open_p) / open_p * 100) if open_p else 0.0
            points.append(
                {
                    "time": t,
                    "price": close,
                    "open": open_p,
                    "close": close,
                    "high": _safe_float(row.get("high")),
                    "low": _safe_float(row.get("low")),
                    "volume": None,
                    "change_pct": round(change_pct, 2),
                }
            )
        return points
    except Exception as e:
        logger.warning("黄金日线失败: %s", e)
        return []


def fetch_chart_series(asset_type: str, symbol: str, chart_range: ChartRange) -> dict:
    sina_symbol = _to_sina_prefix_symbol(symbol, asset_type)
    name = symbol

    if chart_range == ChartRange.TODAY:
        if asset_type == "stock":
            points, trading_day = _fetch_stock_intraday(sina_symbol)
            interval = "1m"
        elif asset_type == "fund":
            points, trading_day = _fetch_fund_intraday(sina_symbol)
            interval = "1m"
            if not points:
                # ETF 分钟线不可用时用最近一日日线单点说明
                daily = _fetch_fund_daily(sina_symbol, 1)
                points = daily
                trading_day = daily[-1]["time"] if daily else None
                interval = "daily"
        else:
            daily = _fetch_gold_daily(symbol, 5)
            points = daily[-1:] if daily else []
            trading_day = points[-1]["time"] if points else None
            interval = "daily"
        return {
            "symbol": normalize_stock_symbol(symbol) if asset_type == "stock" else symbol,
            "name": name,
            "asset_type": asset_type,
            "range": chart_range.value,
            "interval": interval,
            "trading_day": trading_day,
            "note": "非交易时段展示最近一个交易日走势；黄金为日线",
            "points": points,
        }

    days = trading_days_for_range(chart_range)
    if asset_type == "stock":
        points = _fetch_stock_daily(sina_symbol, days)
        interval = "daily"
    elif asset_type == "fund":
        points = _fetch_fund_daily(sina_symbol, days)
        interval = "daily"
    else:
        points = _fetch_gold_daily(symbol, days)
        interval = "daily"

    return {
        "symbol": normalize_stock_symbol(symbol) if asset_type == "stock" else symbol,
        "name": name,
        "asset_type": asset_type,
        "range": chart_range.value,
        "interval": interval,
        "trading_day": None,
        "note": None,
        "points": points,
    }
