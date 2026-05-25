import asyncio
from functools import partial

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.config import get_settings
from app.deps import get_current_user
from app.models import User as UserModel
from app.models import WatchlistItem as WatchlistModel
from app.schemas import WatchlistItem, WatchlistItemCreate, WatchlistItemWithQuote, QuoteResponse
from app.schemas.fund_estimate import FundEstimateResponse
from app.services.types import AssetType

router = APIRouter()

_ESTIMATE_TIMEOUT_SECONDS = 90


@router.get(
    "",
    response_model=list[WatchlistItem],
    summary="自选列表",
    description="返回当前用户全部自选；这些标的会被后台定时拉取行情。",
)
def list_watchlist(
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return db.query(WatchlistModel).filter(WatchlistModel.user_id == current_user.id).all()


@router.get(
    "/with-quotes",
    response_model=list[WatchlistItemWithQuote],
    summary="自选列表（含缓存行情）",
    description="一次返回自选及对应最新缓存报价，便于个人看板展示。quote_stale=true 时建议刷新行情。",
)
def list_watchlist_with_quotes(
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.services.quote_cache import quote_cache

    rows = db.query(WatchlistModel).filter(WatchlistModel.user_id == current_user.id).all()
    settings = get_settings()
    stale_after = float(settings.POLL_INTERVAL_SECONDS) * 1.5
    out: list[WatchlistItemWithQuote] = []
    for row in rows:
        snap = quote_cache.resolve_snapshot(row.symbol, row.asset_type)
        quote_resp = QuoteResponse(**snap.to_dict()) if snap else None
        out.append(
            WatchlistItemWithQuote(
                id=row.id,
                user_id=row.user_id,
                symbol=row.symbol,
                asset_type=AssetType(row.asset_type),
                name=row.name,
                note=row.note,
                created_at=row.created_at,
                quote=quote_resp,
                quote_missing=snap is None,
                quote_stale=quote_cache.is_quote_stale(
                    row.symbol, row.asset_type, max_age_seconds=stale_after
                ),
            )
        )
    return out


@router.post(
    "",
    response_model=WatchlistItem,
    status_code=status.HTTP_201_CREATED,
    summary="添加自选",
    responses={400: {"description": "该标的已在自选列表中"}},
)
def add_watchlist(
    item: WatchlistItemCreate,
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    exists = (
        db.query(WatchlistModel)
        .filter(
            WatchlistModel.user_id == current_user.id,
            WatchlistModel.symbol == item.symbol,
            WatchlistModel.asset_type == item.asset_type.value,
        )
        .first()
    )
    if exists:
        raise HTTPException(status_code=400, detail="已在自选列表中")

    row = WatchlistModel(
        user_id=current_user.id,
        symbol=item.symbol,
        asset_type=item.asset_type.value,
        name=item.name,
        note=item.note,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.delete(
    "/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除自选",
    responses={404: {"description": "自选不存在"}},
)
def remove_watchlist(
    item_id: int,
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = (
        db.query(WatchlistModel)
        .filter(WatchlistModel.id == item_id, WatchlistModel.user_id == current_user.id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="自选不存在")
    db.delete(row)
    db.commit()


@router.get(
    "/fund-estimates",
    response_model=list[FundEstimateResponse],
    summary="自选基金今日预估涨跌",
    description=(
        "对当前用户自选列表中 asset_type=fund 的标的，"
        "根据最近一期披露的股票重仓与当日 A 股涨跌幅加权估算今日涨跌幅。"
        "若场内 ETF 已有缓存行情，会附带 actual_change_pct 便于对比。"
        "单次请求会访问外部数据源，自选基金较多时可能较慢。"
    ),
)
async def list_watchlist_fund_estimates(
    top_n: int = Query(10, ge=5, le=30, description="每只基金纳入计算的重仓股数量上限"),
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(WatchlistModel)
        .filter(
            WatchlistModel.user_id == current_user.id,
            WatchlistModel.asset_type == AssetType.FUND.value,
        )
        .all()
    )
    if not rows:
        return []
    pairs = [(r.symbol, r.name) for r in rows]
    loop = asyncio.get_running_loop()
    try:
        data = await asyncio.wait_for(
            loop.run_in_executor(
                None,
                partial(estimate_watchlist_funds, pairs, top_n=top_n),
            ),
            timeout=_ESTIMATE_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError as e:
        raise HTTPException(
            status_code=504,
            detail=f"预估计算超时（>{_ESTIMATE_TIMEOUT_SECONDS}s），请减少自选基金数量或调小 top_n 后重试",
        ) from e
    return [FundEstimateResponse(**item) for item in data]
