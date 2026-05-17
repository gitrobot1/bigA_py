import logging
from datetime import datetime

from sqlalchemy.dialects.mysql import insert
from sqlalchemy.orm import Session

from app.models import MarketQuote
from app.services.quote_cache import QuoteSnapshot

logger = logging.getLogger(__name__)


def snapshot_to_row(quote: QuoteSnapshot) -> MarketQuote:
    return MarketQuote(
        symbol=quote.symbol,
        asset_type=quote.asset_type,
        name=quote.name,
        price=quote.price,
        change_pct=quote.change_pct,
        change_amount=quote.change_amount,
        volume=quote.volume,
        amount=quote.amount,
        open_price=quote.open_price,
        high=quote.high,
        low=quote.low,
        prev_close=quote.prev_close,
        data_source=quote.data_source,
        updated_at=quote.updated_at or datetime.utcnow(),
    )


def row_to_snapshot(row: MarketQuote) -> QuoteSnapshot:
    return QuoteSnapshot(
        symbol=row.symbol,
        name=row.name,
        asset_type=row.asset_type,
        price=row.price,
        change_pct=row.change_pct,
        change_amount=row.change_amount,
        volume=row.volume,
        amount=row.amount,
        open_price=row.open_price,
        high=row.high,
        low=row.low,
        prev_close=row.prev_close,
        data_source=row.data_source,
        updated_at=row.updated_at or datetime.utcnow(),
    )


def _quote_values(quote: QuoteSnapshot) -> dict:
    return {
        "symbol": quote.symbol,
        "asset_type": quote.asset_type,
        "name": quote.name,
        "price": quote.price,
        "change_pct": quote.change_pct,
        "change_amount": quote.change_amount,
        "volume": quote.volume,
        "amount": quote.amount,
        "open_price": quote.open_price,
        "high": quote.high,
        "low": quote.low,
        "prev_close": quote.prev_close,
        "data_source": quote.data_source,
        "updated_at": quote.updated_at or datetime.utcnow(),
    }


def save_quotes(db: Session, quotes: list[QuoteSnapshot]) -> int:
    if not quotes:
        return 0
    for quote in quotes:
        values = _quote_values(quote)
        stmt = insert(MarketQuote).values(**values)
        stmt = stmt.on_duplicate_key_update(
            name=stmt.inserted.name,
            price=stmt.inserted.price,
            change_pct=stmt.inserted.change_pct,
            change_amount=stmt.inserted.change_amount,
            volume=stmt.inserted.volume,
            amount=stmt.inserted.amount,
            open_price=stmt.inserted.open_price,
            high=stmt.inserted.high,
            low=stmt.inserted.low,
            prev_close=stmt.inserted.prev_close,
            data_source=stmt.inserted.data_source,
            updated_at=stmt.inserted.updated_at,
        )
        db.execute(stmt)
    db.commit()
    logger.info("已持久化 %d 条行情到 MySQL", len(quotes))
    return len(quotes)


def load_all_quotes(db: Session) -> list[QuoteSnapshot]:
    rows = (
        db.query(MarketQuote)
        .filter(MarketQuote.asset_type.in_(["stock", "fund", "gold"]))
        .all()
    )
    return [row_to_snapshot(r) for r in rows]


def indices_to_snapshots(indices: list[dict]) -> list[QuoteSnapshot]:
    snapshots = []
    for item in indices:
        snapshots.append(
            QuoteSnapshot(
                symbol=str(item["symbol"]),
                name=str(item["name"]),
                asset_type="index",
                price=float(item["price"]),
                change_pct=float(item.get("change_pct", 0)),
                change_amount=item.get("change_amount"),
                volume=item.get("volume"),
                amount=item.get("amount"),
                data_source=item.get("data_source"),
                updated_at=datetime.utcnow(),
            )
        )
    return snapshots


def save_indices(db: Session, indices: list[dict]) -> int:
    if not indices:
        return 0
    return save_quotes(db, indices_to_snapshots(indices))


def load_indices(db: Session) -> list[dict]:
    rows = db.query(MarketQuote).filter(MarketQuote.asset_type == "index").all()
    return [
        {
            "symbol": r.symbol,
            "name": r.name,
            "price": r.price,
            "change_pct": r.change_pct,
            "change_amount": r.change_amount,
            "volume": r.volume,
            "amount": r.amount,
            "data_source": r.data_source,
        }
        for r in rows
    ]


def global_to_snapshots(items: list[dict]) -> list[QuoteSnapshot]:
    return [
        QuoteSnapshot(
            symbol=str(x["symbol"]),
            name=str(x["name"]),
            asset_type="global_index",
            price=float(x["price"]),
            change_pct=float(x.get("change_pct", 0)),
            change_amount=x.get("change_amount"),
            data_source=x.get("data_source"),
            updated_at=datetime.utcnow(),
        )
        for x in items
    ]


def bond_to_snapshots(items: list[dict]) -> list[QuoteSnapshot]:
    return [
        QuoteSnapshot(
            symbol=str(x["symbol"]),
            name=str(x["name"]),
            asset_type="bond_yield",
            price=float(x["yield"]),
            change_pct=float(x.get("change_pct", 0)),
            change_amount=x.get("change"),
            data_source=x.get("data_source"),
            updated_at=datetime.utcnow(),
        )
        for x in items
    ]


def save_global_indices(db: Session, items: list[dict]) -> int:
    if not items:
        return 0
    return save_quotes(db, global_to_snapshots(items))


def save_bond_yields(db: Session, items: list[dict]) -> int:
    if not items:
        return 0
    return save_quotes(db, bond_to_snapshots(items))


def load_global_indices(db: Session) -> list[dict]:
    rows = db.query(MarketQuote).filter(MarketQuote.asset_type == "global_index").all()
    return [
        {
            "symbol": r.symbol,
            "name": r.name,
            "price": r.price,
            "change_pct": r.change_pct,
            "change_amount": r.change_amount,
            "data_source": r.data_source,
            "region": _region_for_global(r.symbol),
        }
        for r in rows
    ]


def load_bond_yields(db: Session) -> list[dict]:
    rows = db.query(MarketQuote).filter(MarketQuote.asset_type == "bond_yield").all()
    return [
        {
            "symbol": r.symbol,
            "name": r.name,
            "yield": r.price,
            "change": r.change_amount,
            "change_pct": r.change_pct,
            "data_source": r.data_source,
            "market": "cn" if "中国" in r.name else "us",
            "term": "",
        }
        for r in rows
    ]


def _region_for_global(symbol: str) -> str:
    from app.services.market_catalog import GLOBAL_INDEX_BY_SYMBOL

    item = GLOBAL_INDEX_BY_SYMBOL.get(symbol)
    return item["region"] if item else "other"
