from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.deps import get_current_user
from app.models import AlertEvent as AlertEventModel
from app.models import PriceAlert as PriceAlertModel
from app.models import User as UserModel
from app.schemas import AlertEvent, PriceAlert, PriceAlertCreate

router = APIRouter()


@router.get(
    "",
    response_model=list[PriceAlert],
    summary="提醒列表",
    description="查询当前用户的涨跌提醒，可选仅返回监控中的提醒。",
)
def list_alerts(
    active_only: bool = Query(False, description="仅返回 is_active=1 的提醒"),
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    q = db.query(PriceAlertModel).filter(PriceAlertModel.user_id == current_user.id)
    if active_only:
        q = q.filter(PriceAlertModel.is_active == 1)
    return q.order_by(PriceAlertModel.created_at.desc()).all()


@router.post(
    "",
    response_model=PriceAlert,
    status_code=status.HTTP_201_CREATED,
    summary="创建提醒",
    description="创建后将在每次行情刷新时检测；触发一次后自动停用。",
)
def create_alert(
    body: PriceAlertCreate,
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = PriceAlertModel(
        user_id=current_user.id,
        symbol=body.symbol,
        asset_type=body.asset_type.value,
        name=body.name,
        condition_type=body.condition_type.value,
        threshold=body.threshold,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.delete(
    "/{alert_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除提醒",
    responses={404: {"description": "提醒不存在"}},
)
def delete_alert(
    alert_id: int,
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = (
        db.query(PriceAlertModel)
        .filter(PriceAlertModel.id == alert_id, PriceAlertModel.user_id == current_user.id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="提醒不存在")
    db.delete(row)
    db.commit()


@router.get(
    "/events",
    response_model=list[AlertEvent],
    summary="提醒触发记录",
    description="已触发的提醒事件历史，按时间倒序。",
)
def list_alert_events(
    limit: int = Query(50, ge=1, le=200, description="返回条数"),
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return (
        db.query(AlertEventModel)
        .filter(AlertEventModel.user_id == current_user.id)
        .order_by(AlertEventModel.created_at.desc())
        .limit(limit)
        .all()
    )
