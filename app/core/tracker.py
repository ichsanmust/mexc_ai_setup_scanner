"""Outcome tracker checking live MEXC prices & candles for OPEN setups."""

from datetime import datetime, timezone
from decimal import Decimal
import logging
from typing import Any

from sqlalchemy.orm import Session

from ..models import TradeSetup, utcnow
from ..scanner.mexc_public import MexcPublicClient

log = logging.getLogger(__name__)


def _to_utc_ts(dt: datetime) -> int:
    """Convert naive (UTC) or aware datetime to integer epoch seconds."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


def evaluate_setup_against_market(
    setup: TradeSetup,
    last_price: float | None,
    candles_since_open: list[dict[str, Any]],
    now: datetime | None = None,
) -> tuple[str | None, float | None]:
    """Determine if an active setup reached ENTRY_HIT, HIT_TP, HIT_SL, or EXPIRED.

    Returns (new_status, resolved_price) or (None, None) if unchanged.
    """
    current_time = now or utcnow()
    entry = float(setup.entry_price)
    sl = float(setup.stop_loss)
    tp = float(setup.take_profit)
    direction = setup.decision
    entry_touched = setup.status in ("ENTRY_HIT", "MANUAL_TAKEN") or setup.entry_type == "MARKET"

    # For MANUAL_TAKEN, evaluate candles only from when the user marked it taken;
    # otherwise evaluate from setup creation (with 60s alignment for Min1 candle bucket).
    since_dt = (
        setup.manual_action_at
        if setup.status == "MANUAL_TAKEN" and setup.manual_action_at
        else setup.created_at
    )
    since_ts = _to_utc_ts(since_dt)

    # Check historical candles since creation/action in chronological order so first touch wins
    for candle in sorted(candles_since_open, key=lambda c: int(c["time"])):
        if int(candle["time"]) < since_ts - 60:
            continue
        high = float(candle["high"])
        low = float(candle["low"])
        if direction == "LONG":
            if low <= entry:
                entry_touched = True
            hit_sl = low <= sl
            hit_tp = high >= tp and entry_touched
            if hit_sl and hit_tp:
                return "HIT_SL", sl
            if hit_sl:
                return "HIT_SL", sl
            if hit_tp:
                return "HIT_TP", tp
        elif direction == "SHORT":
            if high >= entry:
                entry_touched = True
            hit_sl = high >= sl
            hit_tp = low <= tp and entry_touched
            if hit_sl and hit_tp:
                return "HIT_SL", sl
            if hit_sl:
                return "HIT_SL", sl
            if hit_tp:
                return "HIT_TP", tp

    # Also check live ticker lastPrice (catches price already at or past entry/SL/TP between ticks)
    if last_price is not None and last_price > 0:
        if direction == "LONG":
            if last_price <= entry:
                entry_touched = True
            if last_price <= sl:
                return "HIT_SL", last_price
            if last_price >= tp and entry_touched:
                return "HIT_TP", last_price
        elif direction == "SHORT":
            if last_price >= entry:
                entry_touched = True
            if last_price >= sl:
                return "HIT_SL", last_price
            if last_price <= tp and entry_touched:
                return "HIT_TP", last_price

    if setup.expires_at:
        exp_ts = _to_utc_ts(setup.expires_at)
        now_ts = _to_utc_ts(current_time)
        if now_ts >= exp_ts:
            return "EXPIRED", last_price

    if setup.status == "OPEN" and entry_touched:
        return "ENTRY_HIT", None

    return None, None


def _select_kline_params(oldest_since: datetime, now: datetime) -> tuple[str, int]:
    """Pick the finest candle resolution covering oldest active setup since-timestamp."""
    age_seconds = max(0, _to_utc_ts(now) - _to_utc_ts(oldest_since))
    age_mins = age_seconds // 60 + 2
    if age_mins <= 480:
        return "Min1", min(500, max(60, age_mins + 5))
    if age_mins <= 2400:
        return "Min5", min(500, max(60, age_mins // 5 + 5))
    return "Min15", min(750, max(60, age_mins // 15 + 5))


async def check_open_setups(db: Session, mexc_client: MexcPublicClient) -> dict[str, int]:
    """Evaluate all OPEN, ENTRY_HIT, and MANUAL_TAKEN setups against live MEXC market data."""
    open_setups = (
        db.query(TradeSetup)
        .filter(TradeSetup.status.in_(["OPEN", "ENTRY_HIT", "MANUAL_TAKEN"]))
        .all()
    )
    if not open_setups:
        return {"checked": 0, "entry_hit": 0, "hit_tp": 0, "hit_sl": 0, "expired": 0}

    tickers = await mexc_client.get_all_tickers()
    now = utcnow()

    oldest_by_symbol: dict[str, datetime] = {}
    for setup in open_setups:
        since_dt = (
            setup.manual_action_at
            if setup.status == "MANUAL_TAKEN" and setup.manual_action_at
            else setup.created_at
        )
        prev = oldest_by_symbol.get(setup.symbol)
        if prev is None or _to_utc_ts(since_dt) < _to_utc_ts(prev):
            oldest_by_symbol[setup.symbol] = since_dt

    kline_map: dict[str, list[dict[str, Any]]] = {}
    for sym in sorted(oldest_by_symbol):
        interval, limit = _select_kline_params(oldest_by_symbol[sym], now)
        try:
            kline_map[sym] = await mexc_client.get_kline(sym, interval=interval, limit=limit)
        except Exception as exc:
            log.warning("Tracker failed to fetch kline for %s: %s", sym, exc)
            kline_map[sym] = []

    stats = {"checked": len(open_setups), "entry_hit": 0, "hit_tp": 0, "hit_sl": 0, "expired": 0}

    for setup in open_setups:
        ticker = tickers.get(setup.symbol, {})
        last_price = float(ticker["lastPrice"]) if ticker.get("lastPrice") else None
        candles = kline_map.get(setup.symbol, [])

        new_status, resolved_price = evaluate_setup_against_market(
            setup=setup,
            last_price=last_price,
            candles_since_open=candles,
            now=now,
        )
        if new_status:
            setup.status = new_status
            if new_status == "ENTRY_HIT":
                stats["entry_hit"] += 1
            else:
                setup.resolved_at = now
                setup.resolved_price = (
                    Decimal(f"{resolved_price:.8f}") if resolved_price is not None else None
                )
                if new_status == "HIT_TP":
                    stats["hit_tp"] += 1
                elif new_status == "HIT_SL":
                    stats["hit_sl"] += 1
                elif new_status == "EXPIRED":
                    stats["expired"] += 1

    db.commit()
    return stats
