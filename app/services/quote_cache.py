import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

REDIS_QUOTES_KEY = "biga:quotes"
REDIS_INDICES_KEY = "biga:indices"
REDIS_GLOBAL_INDICES_KEY = "biga:global_indices"
REDIS_BOND_YIELDS_KEY = "biga:bond_yields"
REDIS_STATUS_KEY = "biga:market:status"


@dataclass
class QuoteSnapshot:
    symbol: str
    name: str
    asset_type: str
    price: float
    change_pct: float
    change_amount: float | None = None
    volume: float | None = None
    amount: float | None = None
    open_price: float | None = None
    high: float | None = None
    low: float | None = None
    prev_close: float | None = None
    data_source: str | None = None
    updated_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "name": self.name,
            "asset_type": self.asset_type,
            "price": self.price,
            "change_pct": self.change_pct,
            "change_amount": self.change_amount,
            "volume": self.volume,
            "amount": self.amount,
            "open_price": self.open_price,
            "high": self.high,
            "low": self.low,
            "prev_close": self.prev_close,
            "data_source": self.data_source,
            "updated_at": self.updated_at.isoformat() + "Z",
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "QuoteSnapshot":
        updated = data.get("updated_at", "")
        if isinstance(updated, str) and updated.endswith("Z"):
            updated = updated[:-1]
        try:
            updated_at = datetime.fromisoformat(updated) if updated else datetime.utcnow()
        except ValueError:
            updated_at = datetime.utcnow()
        return cls(
            symbol=data["symbol"],
            name=data.get("name", data["symbol"]),
            asset_type=data["asset_type"],
            price=float(data["price"]),
            change_pct=float(data["change_pct"]),
            change_amount=data.get("change_amount"),
            volume=data.get("volume"),
            amount=data.get("amount"),
            open_price=data.get("open_price"),
            high=data.get("high"),
            low=data.get("low"),
            prev_close=data.get("prev_close"),
            data_source=data.get("data_source"),
            updated_at=updated_at,
        )


class QuoteCache:
    def __init__(self) -> None:
        self._quotes: dict[str, QuoteSnapshot] = {}
        self._indices: list[dict[str, Any]] = []
        self._global_indices: list[dict[str, Any]] = []
        self._bond_yields: list[dict[str, Any]] = []
        self._last_refresh: datetime | None = None
        self._last_error: str | None = None

    def key(self, symbol: str, asset_type: str) -> str:
        return f"{asset_type}:{symbol}"

    def set_quote(self, quote: QuoteSnapshot) -> None:
        self._quotes[self.key(quote.symbol, quote.asset_type)] = quote

    def get_quote(self, symbol: str, asset_type: str) -> QuoteSnapshot | None:
        return self._quotes.get(self.key(symbol, asset_type))

    def get_all_quotes(self) -> list[QuoteSnapshot]:
        return list(self._quotes.values())

    def set_indices(self, indices: list[dict[str, Any]]) -> None:
        if indices:
            self._indices = indices

    def get_indices(self) -> list[dict[str, Any]]:
        return self._indices

    def set_global_indices(self, items: list[dict[str, Any]]) -> None:
        if items:
            self._global_indices = items

    def get_global_indices(self) -> list[dict[str, Any]]:
        return self._global_indices

    def set_bond_yields(self, items: list[dict[str, Any]]) -> None:
        if items:
            self._bond_yields = items

    def get_bond_yields(self) -> list[dict[str, Any]]:
        return self._bond_yields

    def mark_refreshed(self, error: str | None = None, db=None) -> None:
        self._last_refresh = datetime.utcnow()
        self._last_error = error
        self.persist_to_redis()
        if db is not None:
            self.persist_to_db(db)
            self.persist_indices_to_db(db)
            self.persist_global_and_bond_to_db(db)

    def persist_global_and_bond_to_db(self, db) -> None:
        try:
            from app.services.quote_store import save_bond_yields, save_global_indices

            if self._global_indices:
                save_global_indices(db, self._global_indices)
            if self._bond_yields:
                save_bond_yields(db, self._bond_yields)
        except Exception as e:
            logger.warning("全球/债券写入 MySQL 失败: %s", e)

    def persist_to_db(self, db) -> None:
        try:
            from app.services.quote_store import save_quotes

            save_quotes(db, self.get_all_quotes())
        except Exception as e:
            logger.warning("行情写入 MySQL 失败: %s", e)

    def persist_indices_to_db(self, db) -> None:
        if not self._indices:
            return
        try:
            from app.services.quote_store import save_indices

            save_indices(db, self._indices)
        except Exception as e:
            logger.warning("指数写入 MySQL 失败: %s", e)

    def load_from_db(self, db) -> None:
        try:
            from app.services.quote_store import load_all_quotes

            for quote in load_all_quotes(db):
                self.set_quote(quote)
            logger.info("已从 MySQL 恢复 %d 条行情", len(self._quotes))
        except Exception as e:
            logger.warning("从 MySQL 加载行情失败: %s", e)

    def load_all(self, db=None) -> None:
        """Redis 优先，MySQL 补全缺失项（含指数）"""
        self.load_from_redis()
        if db is None:
            return
        from app.services.quote_store import (
            load_all_quotes,
            load_bond_yields,
            load_global_indices,
            load_indices,
        )

        if not self._indices:
            self._indices = load_indices(db)
        if not self._global_indices:
            self._global_indices = load_global_indices(db)
        if not self._bond_yields:
            self._bond_yields = load_bond_yields(db)
        for quote in load_all_quotes(db):
            if self.key(quote.symbol, quote.asset_type) not in self._quotes:
                self.set_quote(quote)

    def status(self) -> dict[str, Any]:
        return {
            "last_refresh": self._last_refresh.isoformat() + "Z" if self._last_refresh else None,
            "quote_count": len(self._quotes),
            "index_count": len(self._indices),
            "global_index_count": len(self._global_indices),
            "bond_yield_count": len(self._bond_yields),
            "last_error": self._last_error,
        }

    def persist_to_redis(self) -> None:
        try:
            from app.core.redis_client import get_redis

            r = get_redis()
            r.set(REDIS_QUOTES_KEY, json.dumps({k: v.to_dict() for k, v in self._quotes.items()}, ensure_ascii=False))
            r.set(REDIS_INDICES_KEY, json.dumps(self._indices, ensure_ascii=False))
            r.set(REDIS_GLOBAL_INDICES_KEY, json.dumps(self._global_indices, ensure_ascii=False))
            r.set(REDIS_BOND_YIELDS_KEY, json.dumps(self._bond_yields, ensure_ascii=False))
            r.set(REDIS_STATUS_KEY, json.dumps(self.status(), ensure_ascii=False))
        except Exception as e:
            logger.warning("行情写入 Redis 失败: %s", e)

    def load_from_redis(self) -> None:
        try:
            from app.core.redis_client import get_redis

            r = get_redis()
            quotes_raw = r.get(REDIS_QUOTES_KEY)
            indices_raw = r.get(REDIS_INDICES_KEY)
            global_raw = r.get(REDIS_GLOBAL_INDICES_KEY)
            bond_raw = r.get(REDIS_BOND_YIELDS_KEY)
            status_raw = r.get(REDIS_STATUS_KEY)

            if quotes_raw:
                data = json.loads(quotes_raw)
                self._quotes = {k: QuoteSnapshot.from_dict(v) for k, v in data.items()}
            if indices_raw:
                self._indices = json.loads(indices_raw)
            if global_raw:
                self._global_indices = json.loads(global_raw)
            if bond_raw:
                self._bond_yields = json.loads(bond_raw)
            if status_raw:
                status = json.loads(status_raw)
                if status.get("last_refresh"):
                    self._last_refresh = datetime.fromisoformat(status["last_refresh"].replace("Z", ""))
                self._last_error = status.get("last_error")
            logger.info("已从 Redis 恢复 %d 条行情、%d 条指数", len(self._quotes), len(self._indices))
        except Exception as e:
            logger.warning("从 Redis 加载行情失败: %s", e)


quote_cache = QuoteCache()
