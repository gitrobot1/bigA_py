from fastapi import APIRouter, HTTPException, Query

from app.schemas.chart import ChartPoint
from app.schemas.global_bond import BondYieldQuote, CatalogItem, GlobalBondChartResponse
from app.services.bond_provider import fetch_bond_yield_chart, fetch_bond_yields_spot
from app.services.chart_provider import ChartRange
from app.services.market_catalog import BOND_YIELD_CATALOG
from app.services.quote_cache import quote_cache
from app.services.refresh_job import trigger_refresh_background

router = APIRouter()


@router.get("/catalog", response_model=list[CatalogItem], summary="债券收益率品种目录")
def bond_catalog():
    return [
        CatalogItem(symbol=x["symbol"], name=x["name"], market=x["market"], term=x["term"])
        for x in BOND_YIELD_CATALOG
    ]


@router.get("/yields", response_model=list[BondYieldQuote], summary="国债收益率快照")
def list_bond_yields(refresh: bool = Query(False, description="true 时先提交后台刷新")):
    if refresh:
        trigger_refresh_background(fast=True)
    items = quote_cache.get_bond_yields()
    if not items:
        items = fetch_bond_yields_spot()
        if items:
            quote_cache.set_bond_yields(items)
    return [BondYieldQuote(**x) for x in items]


@router.get(
    "/chart/{symbol}",
    response_model=GlobalBondChartResponse,
    summary="国债收益率走势图",
    description="symbol 如 US10YT、CN10YT，或中文名 美国10年期国债。Y 轴为收益率(%)",
)
def bond_chart(
    symbol: str,
    range: ChartRange = Query(ChartRange.ONE_MONTH, description="today|1m|2m|3m|1y|3y|5y"),
):
    try:
        data = fetch_bond_yield_chart(symbol, range)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    raw_points = data.pop("points", [])
    if not raw_points:
        raise HTTPException(status_code=404, detail="暂无图表数据")
    return GlobalBondChartResponse(
        **data,
        points=[ChartPoint(**p) for p in raw_points],
    )
