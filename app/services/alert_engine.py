from datetime import datetime

from sqlalchemy.orm import Session

from app.models import AlertEvent, PriceAlert
from app.services.quote_cache import QuoteSnapshot, quote_cache
from app.services.types import AlertCondition


def _matches(alert: PriceAlert, quote: QuoteSnapshot) -> bool:
    if alert.symbol != quote.symbol or alert.asset_type != quote.asset_type:
        return False
    cond = alert.condition_type
    if cond == AlertCondition.PRICE_ABOVE.value:
        return quote.price >= alert.threshold
    if cond == AlertCondition.PRICE_BELOW.value:
        return quote.price <= alert.threshold
    if cond == AlertCondition.CHANGE_PCT_ABOVE.value:
        return quote.change_pct >= alert.threshold
    if cond == AlertCondition.CHANGE_PCT_BELOW.value:
        return quote.change_pct <= alert.threshold
    return False


def _message(alert: PriceAlert, quote: QuoteSnapshot) -> str:
    cond = alert.condition_type
    labels = {
        AlertCondition.PRICE_ABOVE.value: f"价格突破 {alert.threshold}",
        AlertCondition.PRICE_BELOW.value: f"价格跌破 {alert.threshold}",
        AlertCondition.CHANGE_PCT_ABOVE.value: f"涨幅达到 {alert.threshold}%",
        AlertCondition.CHANGE_PCT_BELOW.value: f"跌幅达到 {alert.threshold}%",
    }
    return f"{quote.name}({quote.symbol}) {labels.get(cond, '触发提醒')}，当前价 {quote.price}，涨跌幅 {quote.change_pct}%"


def evaluate_alerts(db: Session) -> list[AlertEvent]:
    alerts = db.query(PriceAlert).filter(PriceAlert.is_active == 1).all()
    events: list[AlertEvent] = []
    for alert in alerts:
        quote = quote_cache.get_quote(alert.symbol, alert.asset_type)
        if not quote or not _matches(alert, quote):
            continue
        event = AlertEvent(
            alert_id=alert.id,
            user_id=alert.user_id,
            symbol=alert.symbol,
            asset_type=alert.asset_type,
            message=_message(alert, quote),
            price=quote.price,
            change_pct=quote.change_pct,
        )
        db.add(event)
        alert.triggered_at = datetime.utcnow()
        alert.is_active = 0
        events.append(event)
    if events:
        db.commit()
    return events
