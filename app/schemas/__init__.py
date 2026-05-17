from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.services.types import AlertCondition, AssetType


class UserBase(BaseModel):
    username: str = Field(..., description="登录用户名", examples=["admin"])
    email: str = Field(..., description="邮箱", examples=["admin@example.com"])
    full_name: Optional[str] = Field(None, description="昵称/姓名")


class UserCreate(UserBase):
    password: str = Field(..., min_length=6, description="登录密码", examples=["admin123"])


class User(UserBase):
    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="用户 ID")
    is_active: int = Field(..., description="是否启用，1=启用")
    created_at: datetime = Field(..., description="注册时间")


class TokenResponse(BaseModel):
    access_token: str = Field(..., description="JWT 访问令牌")
    token_type: str = Field(default="bearer", description="令牌类型，固定 bearer")


class WatchlistItemCreate(BaseModel):
    symbol: str = Field(..., description="标的代码", examples=["000001"])
    asset_type: AssetType = Field(..., description="资产类型：stock / fund / gold")
    name: Optional[str] = Field(None, description="显示名称", examples=["平安银行"])
    note: Optional[str] = Field(None, description="备注")


class WatchlistItem(WatchlistItemCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    created_at: datetime


class PriceAlertCreate(BaseModel):
    symbol: str = Field(..., examples=["600519"])
    asset_type: AssetType
    name: Optional[str] = Field(None, examples=["贵州茅台"])
    condition_type: AlertCondition = Field(..., description="触发条件类型")
    threshold: float = Field(..., description="阈值（价格或涨跌幅百分比）", examples=[-3.0])


class PriceAlert(PriceAlertCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    is_active: int = Field(..., description="1=监控中，0=已触发或停用")
    triggered_at: Optional[datetime] = None
    created_at: datetime


class AlertEvent(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    alert_id: Optional[int] = None
    user_id: int
    symbol: str
    asset_type: str
    message: str = Field(..., description="触发时的可读说明")
    price: Optional[float] = None
    change_pct: Optional[float] = None
    created_at: datetime


class QuoteResponse(BaseModel):
    symbol: str
    name: str
    asset_type: str
    price: float = Field(..., description="最新价")
    change_pct: float = Field(..., description="涨跌幅(%)")
    change_amount: Optional[float] = None
    volume: Optional[float] = None
    amount: Optional[float] = None
    open_price: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    prev_close: Optional[float] = None
    data_source: Optional[str] = Field(None, description="数据来源：em_daily/sina/tencent 等")
    updated_at: str = Field(..., description="缓存更新时间(UTC ISO8601)")


class IndexQuote(BaseModel):
    symbol: str
    name: str
    price: float
    change_pct: float
    change_amount: Optional[float] = None
    volume: Optional[float] = None
    amount: Optional[float] = None


class SymbolSearchResult(BaseModel):
    symbol: str
    name: str
    asset_type: str


class MarketStatus(BaseModel):
    poll_interval_seconds: int = Field(..., description="后台轮询间隔(秒)")
    cache: dict[str, Any] = Field(..., description="含 last_refresh、quote_count、redis_connected 等")


class RefreshResponse(BaseModel):
    message: str
    cache: dict[str, Any] | None = None


class RefreshTriggerResponse(BaseModel):
    message: str = Field(..., description="提示信息")
    status: str = Field(..., description="accepted=已提交 | running=进行中")
    poll_url: str = Field(default="/api/v1/market/refresh/status", description="轮询状态地址")


class RefreshStatusResponse(BaseModel):
    status: str = Field(..., description="idle | running | done | failed")
    started_at: str | None = None
    finished_at: str | None = None
    error: str | None = None
    cache: dict[str, Any] = Field(default_factory=dict)
