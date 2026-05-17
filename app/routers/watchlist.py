from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.deps import get_current_user
from app.models import User as UserModel
from app.models import WatchlistItem as WatchlistModel
from app.schemas import WatchlistItem, WatchlistItemCreate

router = APIRouter()


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
