from typing import Optional

from pydantic import BaseModel, Field

from app.schemas.chart import ChartPoint, ChartSeriesResponse


class GlobalIndexQuote(BaseModel):
    symbol: str
    name: str
    region: str = Field(..., description="us | europe | asia")
    price: float
    change_pct: float
    change_amount: Optional[float] = None
    data_source: Optional[str] = None
    em_name: Optional[str] = None


class BondYieldQuote(BaseModel):
    symbol: str
    name: str
    market: str = Field(..., description="cn | us")
    term: str = Field(..., description="如 10Y")
    yield_: float = Field(..., alias="yield", description="收益率(%)")
    change: Optional[float] = None
    change_pct: Optional[float] = None
    unit: str = "percent"
    data_source: Optional[str] = None
    updated_at: Optional[str] = None

    class Config:
        populate_by_name = True


class CatalogItem(BaseModel):
    symbol: str
    name: str
    region: Optional[str] = None
    market: Optional[str] = None
    term: Optional[str] = None


class GlobalBondChartResponse(ChartSeriesResponse):
    region: Optional[str] = None
    market: Optional[str] = None
    unit: Optional[str] = Field(None, description="index | percent")
