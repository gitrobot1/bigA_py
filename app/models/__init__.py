from datetime import datetime

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from app.core.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, nullable=False)
    email = Column(String(100), unique=True, nullable=False)
    hashed_password = Column(String(200), nullable=False)
    full_name = Column(String(100))
    is_active = Column(Integer, default=1)
    created_at = Column(DateTime, default=datetime.utcnow)

    watchlist = relationship("WatchlistItem", back_populates="user", cascade="all, delete-orphan")
    alerts = relationship("PriceAlert", back_populates="user", cascade="all, delete-orphan")


class WatchlistItem(Base):
    __tablename__ = "watchlist_items"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    symbol = Column(String(32), nullable=False)
    asset_type = Column(String(16), nullable=False)
    name = Column(String(128))
    note = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="watchlist")


class PriceAlert(Base):
    __tablename__ = "price_alerts"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    symbol = Column(String(32), nullable=False)
    asset_type = Column(String(16), nullable=False)
    name = Column(String(128))
    condition_type = Column(String(32), nullable=False)
    threshold = Column(Float, nullable=False)
    is_active = Column(Integer, default=1)
    triggered_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="alerts")
    events = relationship("AlertEvent", back_populates="alert")


class AlertEvent(Base):
    __tablename__ = "alert_events"

    id = Column(Integer, primary_key=True, index=True)
    alert_id = Column(Integer, ForeignKey("price_alerts.id"))
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    symbol = Column(String(32), nullable=False)
    asset_type = Column(String(16), nullable=False)
    message = Column(Text, nullable=False)
    price = Column(Float)
    change_pct = Column(Float)
    created_at = Column(DateTime, default=datetime.utcnow)

    alert = relationship("PriceAlert", back_populates="events")


class MarketQuote(Base):
    """行情快照持久化（Redis 失效时可从 MySQL 恢复）"""

    __tablename__ = "market_quotes"
    __table_args__ = (UniqueConstraint("symbol", "asset_type", name="uq_market_quote_symbol_type"),)

    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String(32), nullable=False, index=True)
    asset_type = Column(String(16), nullable=False, index=True)
    name = Column(String(128), nullable=False)
    price = Column(Float, nullable=False)
    change_pct = Column(Float, nullable=False, default=0.0)
    change_amount = Column(Float)
    volume = Column(Float)
    amount = Column(Float)
    open_price = Column(Float)
    high = Column(Float)
    low = Column(Float)
    prev_close = Column(Float)
    data_source = Column(String(32), comment="数据来源：em_daily/sina/tx/xq/em_spot 等")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
