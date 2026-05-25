from typing import Optional

from pydantic import BaseModel, Field


class HoldingContribution(BaseModel):
    stock_code: str
    stock_name: str
    weight_pct: float = Field(..., description="占基金净值比例(%)")
    change_pct: Optional[float] = Field(None, description="该股今日涨跌幅(%)")
    contribution_pct: Optional[float] = Field(None, description="对基金预估涨跌的贡献(%)")
    price: Optional[float] = None
    data_source: Optional[str] = None


class FundEstimateResponse(BaseModel):
    symbol: str
    name: str
    estimated_change_pct: Optional[float] = Field(None, description="基于重仓股加权的预估今日涨跌幅(%)")
    actual_change_pct: Optional[float] = Field(
        None, description="ETF/场内基金缓存中的实际涨跌幅(%)，无缓存则为空"
    )
    estimate_vs_actual_pct: Optional[float] = Field(
        None, description="实际涨跌幅 - 预估涨跌幅(%)，用于对比偏差"
    )
    covered_weight_pct: Optional[float] = Field(None, description="已纳入计算的重仓占净值合计(%)")
    report_period: Optional[str] = Field(None, description="持仓数据所属报告期")
    stock_weight_pct: Optional[float] = Field(None, description="该期披露的股票仓位合计(%)")
    holding_count: Optional[int] = None
    missing_stock_count: Optional[int] = Field(None, description="未能取到行情的重仓股数量")
    missing_stocks: list[str] = Field(default_factory=list)
    contributions: list[HoldingContribution] = Field(default_factory=list)
    disclaimer: str
    computed_at: str
    error: Optional[str] = Field(None, description="估算失败时的原因")


class FundHoldingsResponse(BaseModel):
    symbol: str
    report_period: str
    report_year: int
    holding_count: int
    stock_weight_pct: float
    holdings: list[dict]
    data_source: str
    disclaimer: str = (
        "来自基金定期报告披露的股票投资明细，非实时持仓。"
    )
