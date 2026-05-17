from typing import Optional

from pydantic import BaseModel, Field


class ChartPoint(BaseModel):
    time: str = Field(..., description="时间：分钟线 yyyy-MM-dd HH:mm:ss，日线 yyyy-MM-dd")
    price: float = Field(..., description="收盘价/最新价，折线图 Y 轴")
    open: Optional[float] = None
    close: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    volume: Optional[float] = None
    change_pct: Optional[float] = Field(None, description="涨跌幅(%)， mainly 日线")


class ChartSeriesResponse(BaseModel):
    symbol: str
    name: Optional[str] = None
    asset_type: str
    range: str = Field(..., description="today | 1m | 2m | 3m | 1y | 3y | 5y")
    interval: str = Field(..., description="1m 分钟 | daily 日线")
    trading_day: Optional[str] = Field(None, description="分时图对应的交易日")
    note: Optional[str] = None
    points: list[ChartPoint] = Field(default_factory=list, description="直接用于 ECharts 等图表库")
