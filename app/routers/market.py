from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.core.redis_client import check_redis
from app.schemas.chart import ChartSeriesResponse
from app.schemas import (
    IndexQuote,
    MarketStatus,
    QuoteResponse,
    RefreshResponse,
    RefreshStatusResponse,
    RefreshTriggerResponse,
    SymbolSearchResult,
)
from app.services.chart_provider import ChartRange, fetch_chart_series
from app.services import quote_provider
from app.services.quote_cache import quote_cache
from app.services.refresh_job import get_refresh_status, is_refresh_running, trigger_refresh_background
from app.services.scheduler import refresh_market_data
from app.services.types import AssetType

router = APIRouter()


@router.get(
    "/status",
    response_model=MarketStatus,
    summary="行情服务状态",
    description="返回轮询间隔、上次刷新时间、缓存条数、Redis/MySQL 连接信息等。",
)
def market_status():
    settings = get_settings()
    status = quote_cache.status()
    status["redis_connected"] = check_redis()
    status["database"] = settings.database.name
    status["global_index_count"] = len(quote_cache.get_global_indices())
    status["bond_yield_count"] = len(quote_cache.get_bond_yields())
    status["refresh"] = get_refresh_status()
    return MarketStatus(
        poll_interval_seconds=settings.POLL_INTERVAL_SECONDS,
        cache=status,
    )


@router.get(
    "/indices",
    response_model=list[IndexQuote],
    summary="主要指数",
    description="上证、深证、创业板、沪深300 等指数最新行情（来自最近一次后台刷新）。",
)
def list_indices():
    return quote_cache.get_indices()


@router.get(
    "/quotes",
    response_model=list[QuoteResponse],
    summary="行情列表",
    description="返回 Redis 内存缓存中的全部报价，可按资产类型或代码过滤。",
)
def list_quotes(
    asset_type: AssetType | None = Query(None, description="过滤：stock / fund / gold"),
    symbol: str | None = Query(None, description="过滤：标的代码"),
):
    quotes = quote_cache.get_all_quotes()
    if asset_type:
        quotes = [q for q in quotes if q.asset_type == asset_type.value]
    if symbol:
        quotes = [q for q in quotes if q.symbol == symbol]
    return [QuoteResponse(**q.to_dict()) for q in quotes]


@router.get(
    "/chart/{asset_type}/{symbol}",
    response_model=ChartSeriesResponse,
    summary="图表走势数据",
    description=(
        "返回 K 线/分时序列，供前端 ECharts、Chart.js 等渲染。"
        "`range=today` 为当日（或最近交易日）分钟走势；"
        "其余为日线：`1m`/`2m`/`3m`/`1y`/`3y`/`5y`。"
        "非交易时段 today 展示上一交易日分时。"
    ),
)
def get_chart(
    asset_type: AssetType,
    symbol: str,
    range: ChartRange = Query(
        ChartRange.ONE_MONTH,
        description="today | 1m | 2m | 3m | 1y | 3y | 5y（均为日线，除 today 为分时）",
    ),
):
    if asset_type == AssetType.INDEX:
        raise HTTPException(status_code=400, detail="指数请使用 /market/indices，暂不支持图表接口")
    data = fetch_chart_series(asset_type.value, symbol, range)
    if not data["points"]:
        raise HTTPException(status_code=404, detail="暂无图表数据，请稍后重试或换一个数据源时段")
    return ChartSeriesResponse(**data)


@router.get(
    "/quotes/{asset_type}/{symbol}",
    response_model=QuoteResponse,
    summary="单标的行情",
    responses={404: {"description": "缓存中无该标的，请先加入自选或等待刷新"}},
)
def get_quote(asset_type: AssetType, symbol: str):
    quote = quote_cache.get_quote(symbol, asset_type.value)
    if not quote:
        raise HTTPException(status_code=404, detail="暂无缓存行情，请加入自选或等待下次刷新")
    return QuoteResponse(**quote.to_dict())


@router.get(
    "/search",
    response_model=list[SymbolSearchResult],
    summary="搜索标的",
    description="按代码或名称关键词搜索 A 股、ETF、黄金品种（实时请求数据源，可能较慢）。",
)
def search_symbols(
    q: str = Query(..., min_length=1, description="代码或名称关键词", examples=["茅台"]),
    asset_type: AssetType | None = Query(None, description="限定资产类型"),
    limit: int = Query(20, ge=1, le=50, description="返回条数上限"),
):
    return quote_provider.search_symbols(q, asset_type, limit)


@router.post(
    "/refresh",
    response_model=RefreshTriggerResponse,
    summary="提交行情刷新（异步）",
    description=(
        "立即返回，后台执行拉取，避免前端超时。"
        "请轮询 GET /market/refresh/status 直到 status 为 done 或 failed。"
        "query 参数 full=true 时使用完整慢速模式（含东财全市场批量）。"
    ),
    status_code=202,
)
def trigger_refresh(full: bool = Query(False, description="true=完整慢速刷新；默认快速模式")):
    ok, message = trigger_refresh_background(fast=not full)
    if not ok:
        return JSONResponse(
            status_code=409,
            content=RefreshTriggerResponse(message=message, status="running").model_dump(),
        )
    return RefreshTriggerResponse(message=message, status="accepted")


@router.get(
    "/refresh/status",
    response_model=RefreshStatusResponse,
    summary="查询刷新任务状态",
)
def refresh_status():
    job = get_refresh_status()
    cache = quote_cache.status()
    if job["status"] == "done":
        message = "刷新完成"
    elif job["status"] == "running":
        message = "刷新进行中"
    elif job["status"] == "failed":
        message = "刷新失败"
    else:
        message = "暂无刷新任务"
    return RefreshStatusResponse(
        status=job["status"],
        started_at=job.get("started_at"),
        finished_at=job.get("finished_at"),
        error=job.get("error"),
        cache={**cache, "message": message, "quote_count": cache.get("quote_count", 0)},
    )


@router.post(
    "/refresh/sync",
    response_model=RefreshResponse,
    summary="同步刷新（慎用）",
    description="阻塞直到刷新结束，自选较多时可能超过 1 分钟，前端易超时。推荐使用 POST /refresh。",
    include_in_schema=True,
)
def trigger_refresh_sync(full: bool = Query(False)):
    if is_refresh_running():
        raise HTTPException(status_code=409, detail="已有后台刷新进行中")
    refresh_market_data(fast=not full)
    return RefreshResponse(message="刷新完成", cache=quote_cache.status())
