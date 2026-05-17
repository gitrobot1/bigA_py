from enum import Enum


class AssetType(str, Enum):
    STOCK = "stock"
    FUND = "fund"
    GOLD = "gold"
    INDEX = "index"
    GLOBAL_INDEX = "global_index"
    BOND_YIELD = "bond_yield"


class AlertCondition(str, Enum):
    PRICE_ABOVE = "price_above"
    PRICE_BELOW = "price_below"
    CHANGE_PCT_ABOVE = "change_pct_above"
    CHANGE_PCT_BELOW = "change_pct_below"
