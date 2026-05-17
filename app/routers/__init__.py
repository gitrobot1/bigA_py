from fastapi import APIRouter

from app.routers import alerts, bond_market, global_market, market, users, watchlist

api_router = APIRouter()

api_router.include_router(users.router, prefix="/users", tags=["用户"])
api_router.include_router(market.router, prefix="/market", tags=["行情"])
api_router.include_router(global_market.router, prefix="/market/global", tags=["全球股指"])
api_router.include_router(bond_market.router, prefix="/market/bond", tags=["债券收益率"])
api_router.include_router(
    watchlist.router,
    prefix="/watchlist",
    tags=["自选"],
    dependencies=[],
)
api_router.include_router(alerts.router, prefix="/alerts", tags=["涨跌提醒"])
