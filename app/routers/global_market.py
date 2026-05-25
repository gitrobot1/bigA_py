from fastapi import APIRouter, HTTPException, Query

from app.schemas.chart import ChartPoint
from app.schemas.global_bond import CatalogItem, GlobalBondChartResponse, GlobalIndexQuote
from app.services.chart_provider import ChartRange
from app.services.global_index_provider import fetch_global_index_chart, fetch_global_indices_spot
from app.services.market_catalog import GLOBAL_INDEX_CATALOG
from app.services.quote_cache import quote_cache
from app.services.refresh_job import trigger_refresh_background

router = APIRouter()


@router.get("/catalog", response_model=list[CatalogItem], summary="全球指数品种目录")
def global_catalog():
    return [
        CatalogItem(symbol=x["symbol"], name=x["name"], region=x["region"])
        for x in GLOBAL_INDEX_CATALOG
    ]


@router.get("/indices", response_model=list[GlobalIndexQuote], summary="全球股指快照")
def list_global_indices(
    refresh: bool = Query(False, description="true 时先提交后台刷新"),
    region: str | None = Query(None, description="按地区过滤：us | europe | asia"),
):
    if refresh:
        trigger_refresh_background(fast=True)
    items = quote_cache.get_global_indices()
    if not items:
        items = fetch_global_indices_spot()
        if items:
            quote_cache.set_global_indices(items)
    if region:
        items = [x for x in items if x.get("region") == region]
    return [GlobalIndexQuote(**x) for x in items]


@router.get(
    "/chart/{symbol}",
    response_model=GlobalBondChartResponse,
    summary="全球指数走势图",
    description="symbol 用目录代码如 SPX、N225，或东财中文名如 标普500。range 同 A 股图表。",
)
def global_chart(
    symbol: str,
    range: ChartRange = Query(ChartRange.ONE_MONTH, description="today|1m|2m|3m|1y|3y|5y"),
):
    try:
        data = fetch_global_index_chart(symbol, range)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    raw_points = data.pop("points", [])
    if not raw_points:
        raise HTTPException(status_code=404, detail="暂无图表数据")
    return GlobalBondChartResponse(
        **data,
        points=[ChartPoint(**p) for p in raw_points],
    )
