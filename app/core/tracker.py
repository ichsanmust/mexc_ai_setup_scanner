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


def _from_utc_ts(ts: int) -> datetime:
    """Convert integer UTC epoch seconds to naive UTC datetime matching DB columns."""
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).replace(tzinfo=None)


def ensure_created_history(setup: TradeSetup) -> list[dict[str, Any]]:
    """Ensure setup.status_history starts with initial system-created Entry/SL/TP baseline."""
    hist = list(setup.status_history or [])
    if any(isinstance(h, dict) and h.get("event") == "CREATED" for h in hist):
        return hist
    ai_pay = setup.ai_payload if isinstance(setup.ai_payload, dict) else {}
    init_entry = float(ai_pay.get("entry_price") or setup.entry_price)
    init_sl = float(ai_pay.get("stop_loss") or setup.stop_loss)
    init_tp = float(ai_pay.get("take_profit") or setup.take_profit)
    created_dt = setup.created_at or utcnow()
    created_item: dict[str, Any] = {
        "at": created_dt.isoformat(),
        "event": "CREATED",
        "status": "OPEN",
        "price": round(init_entry, 8),
        "stop_loss": round(init_sl, 8),
        "take_profit": round(init_tp, 8),
        "note": (
            f"Setup dibuat oleh sistem (AI {setup.entry_type}) — "
            f"Entry: {init_entry:g}, SL: {init_sl:g}, TP: {init_tp:g}"
        ),
    }
    return [created_item, *hist]


def _append_setup_history(
    setup: TradeSetup,
    *,
    event: str,
    status: str,
    price: float | None = None,
    note: str = "",
    at_dt: datetime | None = None,
) -> None:
    """Append an event entry onto setup.status_history with copy reassignment for ORM tracking."""
    dt = at_dt or utcnow()
    entry: dict[str, Any] = {
        "at": dt.isoformat(),
        "event": event,
        "status": status,
        "price": round(float(price), 8) if price is not None else None,
        "stop_loss": float(setup.stop_loss),
        "take_profit": float(setup.take_profit),
        "note": note,
    }
    setup.status_history = [*ensure_created_history(setup), entry]


def _get_tracking_since_dt(setup: TradeSetup) -> tuple[datetime, bool]:
    """Return (since_dt, is_reactivated) so extended/reset setups aren't killed by stale candles."""
    if setup.status == "MANUAL_TAKEN" and setup.manual_action_at:
        return setup.manual_action_at, True
    if setup.status in ("EXTENDED", "OPEN") and isinstance(setup.status_history, list):
        for h in reversed(setup.status_history):
            if isinstance(h, dict) and h.get("event") in ("EXTENDED", "RESET_OPEN") and h.get("at"):
                try:
                    ev_dt = datetime.fromisoformat(str(h["at"]).replace("Z", "+00:00"))
                    if ev_dt.tzinfo is not None:
                        ev_dt = ev_dt.astimezone(timezone.utc).replace(tzinfo=None)
                    return ev_dt, True
                except ValueError:
                    break
    return setup.created_at, False


def evaluate_setup_trace(
    setup: TradeSetup,
    last_price: float | None,
    candles_since_open: list[dict[str, Any]],
    now: datetime | None = None,
) -> dict[str, Any]:
    """Chronologically evaluate a setup against candles and live ticker, capturing entry/missed-TP trace."""
    current_time = now or utcnow()
    entry = float(setup.entry_price)
    sl = float(setup.stop_loss)
    tp = float(setup.take_profit)
    direction = setup.decision
    already_entered = (
        setup.status in ("ENTRY_HIT", "MANUAL_TAKEN")
        or setup.entry_hit_at is not None
        or setup.manual_action_at is not None
        or setup.entry_type == "MARKET"
    )
    entry_touched = already_entered

    detected_entry_dt: datetime | None = (
        current_time if (setup.status in ("OPEN", "EXTENDED") and setup.entry_type == "MARKET") else None
    )
    detected_missed_tp_dt: datetime | None = None
    detected_missed_tp_price: float | None = None

    since_dt, is_reactivated = _get_tracking_since_dt(setup)
    since_ts = _to_utc_ts(since_dt)

    for candle in sorted(candles_since_open, key=lambda c: int(c["time"])):
        c_ts = int(candle["time"])
        if c_ts < (since_ts if is_reactivated else since_ts - 60):
            continue
        c_dt = _from_utc_ts(c_ts)
        high = float(candle["high"])
        low = float(candle["low"])

        if direction == "LONG":
            if not entry_touched and low <= entry:
                entry_touched = True
                detected_entry_dt = c_dt
            if not entry_touched and high >= tp and detected_missed_tp_dt is None:
                detected_missed_tp_dt = c_dt
                detected_missed_tp_price = tp
            hit_sl = low <= sl
            hit_tp = high >= tp and entry_touched
            if hit_sl and hit_tp:
                return {
                    "new_status": "HIT_SL",
                    "resolved_price": sl,
                    "resolved_dt": c_dt,
                    "entry_hit_dt": detected_entry_dt,
                    "missed_tp_dt": detected_missed_tp_dt,
                    "missed_tp_price": detected_missed_tp_price,
                }
            if hit_sl:
                return {
                    "new_status": "HIT_SL",
                    "resolved_price": sl,
                    "resolved_dt": c_dt,
                    "entry_hit_dt": detected_entry_dt,
                    "missed_tp_dt": detected_missed_tp_dt,
                    "missed_tp_price": detected_missed_tp_price,
                }
            if hit_tp:
                return {
                    "new_status": "HIT_TP",
                    "resolved_price": tp,
                    "resolved_dt": c_dt,
                    "entry_hit_dt": detected_entry_dt,
                    "missed_tp_dt": detected_missed_tp_dt,
                    "missed_tp_price": detected_missed_tp_price,
                }
        elif direction == "SHORT":
            if not entry_touched and high >= entry:
                entry_touched = True
                detected_entry_dt = c_dt
            if not entry_touched and low <= tp and detected_missed_tp_dt is None:
                detected_missed_tp_dt = c_dt
                detected_missed_tp_price = tp
            hit_sl = high >= sl
            hit_tp = low <= tp and entry_touched
            if hit_sl and hit_tp:
                return {
                    "new_status": "HIT_SL",
                    "resolved_price": sl,
                    "resolved_dt": c_dt,
                    "entry_hit_dt": detected_entry_dt,
                    "missed_tp_dt": detected_missed_tp_dt,
                    "missed_tp_price": detected_missed_tp_price,
                }
            if hit_sl:
                return {
                    "new_status": "HIT_SL",
                    "resolved_price": sl,
                    "resolved_dt": c_dt,
                    "entry_hit_dt": detected_entry_dt,
                    "missed_tp_dt": detected_missed_tp_dt,
                    "missed_tp_price": detected_missed_tp_price,
                }
            if hit_tp:
                return {
                    "new_status": "HIT_TP",
                    "resolved_price": tp,
                    "resolved_dt": c_dt,
                    "entry_hit_dt": detected_entry_dt,
                    "missed_tp_dt": detected_missed_tp_dt,
                    "missed_tp_price": detected_missed_tp_price,
                }

    # Check live ticker lastPrice (catches movement between candle buckets)
    if last_price is not None and last_price > 0:
        if direction == "LONG":
            if last_price <= sl:
                return {
                    "new_status": "HIT_SL",
                    "resolved_price": last_price,
                    "resolved_dt": current_time,
                    "entry_hit_dt": detected_entry_dt,
                    "missed_tp_dt": detected_missed_tp_dt,
                    "missed_tp_price": detected_missed_tp_price,
                }
            if not entry_touched and last_price <= entry:
                entry_touched = True
                detected_entry_dt = detected_entry_dt or current_time
            if not entry_touched and last_price >= tp and detected_missed_tp_dt is None:
                detected_missed_tp_dt = current_time
                detected_missed_tp_price = last_price
            if last_price >= tp and entry_touched:
                return {
                    "new_status": "HIT_TP",
                    "resolved_price": last_price,
                    "resolved_dt": current_time,
                    "entry_hit_dt": detected_entry_dt,
                    "missed_tp_dt": detected_missed_tp_dt,
                    "missed_tp_price": detected_missed_tp_price,
                }
        elif direction == "SHORT":
            if last_price >= sl:
                return {
                    "new_status": "HIT_SL",
                    "resolved_price": last_price,
                    "resolved_dt": current_time,
                    "entry_hit_dt": detected_entry_dt,
                    "missed_tp_dt": detected_missed_tp_dt,
                    "missed_tp_price": detected_missed_tp_price,
                }
            if not entry_touched and last_price >= entry:
                entry_touched = True
                detected_entry_dt = detected_entry_dt or current_time
            if not entry_touched and last_price <= tp and detected_missed_tp_dt is None:
                detected_missed_tp_dt = current_time
                detected_missed_tp_price = last_price
            if last_price <= tp and entry_touched:
                return {
                    "new_status": "HIT_TP",
                    "resolved_price": last_price,
                    "resolved_dt": current_time,
                    "entry_hit_dt": detected_entry_dt,
                    "missed_tp_dt": detected_missed_tp_dt,
                    "missed_tp_price": detected_missed_tp_price,
                }

    if setup.expires_at:
        exp_ts = _to_utc_ts(setup.expires_at)
        now_ts = _to_utc_ts(current_time)
        if now_ts >= exp_ts:
            return {
                "new_status": "EXPIRED",
                "resolved_price": last_price,
                "resolved_dt": current_time,
                "entry_hit_dt": detected_entry_dt,
                "missed_tp_dt": detected_missed_tp_dt,
                "missed_tp_price": detected_missed_tp_price,
            }

    if setup.status == "OPEN" and entry_touched:
        return {
            "new_status": "ENTRY_HIT",
            "resolved_price": None,
            "resolved_dt": None,
            "entry_hit_dt": detected_entry_dt or current_time,
            "missed_tp_dt": detected_missed_tp_dt,
            "missed_tp_price": detected_missed_tp_price,
        }

    return {
        "new_status": None,
        "resolved_price": None,
        "resolved_dt": None,
        "entry_hit_dt": detected_entry_dt,
        "missed_tp_dt": detected_missed_tp_dt,
        "missed_tp_price": detected_missed_tp_price,
    }


def evaluate_setup_against_market(
    setup: TradeSetup,
    last_price: float | None,
    candles_since_open: list[dict[str, Any]],
    now: datetime | None = None,
) -> tuple[str | None, float | None]:
    """Determine if an active setup reached ENTRY_HIT, HIT_TP, HIT_SL, or EXPIRED.

    Returns (new_status, resolved_price) or (None, None) if unchanged.
    """
    trace = evaluate_setup_trace(setup, last_price=last_price, candles_since_open=candles_since_open, now=now)
    return trace["new_status"], trace["resolved_price"]


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
    """Evaluate all OPEN, ENTRY_HIT, EXTENDED, and MANUAL_TAKEN setups against live MEXC market data."""
    open_setups = (
        db.query(TradeSetup)
        .filter(TradeSetup.status.in_(["OPEN", "ENTRY_HIT", "MANUAL_TAKEN", "EXTENDED"]))
        .all()
    )
    if not open_setups:
        return {"checked": 0, "entry_hit": 0, "hit_tp": 0, "hit_sl": 0, "expired": 0}

    tickers = await mexc_client.get_all_tickers()
    now = utcnow()

    oldest_by_symbol: dict[str, datetime] = {}
    for setup in open_setups:
        since_dt, _ = _get_tracking_since_dt(setup)
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

        trace = evaluate_setup_trace(
            setup=setup,
            last_price=last_price,
            candles_since_open=candles,
            now=now,
        )

        # Record intermediate events even if overall status remains OPEN
        if trace["missed_tp_dt"] is not None and setup.missed_tp_at is None:
            setup.missed_tp_at = trace["missed_tp_dt"]
            setup.missed_tp_price = (
                Decimal(f"{trace['missed_tp_price']:.8f}")
                if trace["missed_tp_price"] is not None
                else setup.take_profit
            )
            _append_setup_history(
                setup,
                event="TP_BEFORE_ENTRY",
                status=setup.status,
                price=trace["missed_tp_price"],
                note="Harga menembus TP sebelum menyentuh Limit Entry",
                at_dt=trace["missed_tp_dt"],
            )
            setup.updated_at = now

        if setup.status in ("OPEN", "ENTRY_HIT", "EXTENDED") and trace["entry_hit_dt"] is not None and setup.entry_hit_at is None:
            setup.entry_hit_at = trace["entry_hit_dt"]
            _append_setup_history(
                setup,
                event="ENTRY_HIT",
                status="EXTENDED" if setup.status == "EXTENDED" else "ENTRY_HIT",
                price=float(setup.entry_price),
                note=f"Harga menyentuh Entry ({setup.entry_type})",
                at_dt=trace["entry_hit_dt"],
            )
            setup.updated_at = now

        new_status = trace["new_status"]
        resolved_price = trace["resolved_price"]
        if new_status:
            setup.status = new_status
            setup.updated_at = now
            if new_status == "ENTRY_HIT":
                stats["entry_hit"] += 1
            else:
                ev_dt = trace["resolved_dt"] or now
                setup.resolved_at = ev_dt
                setup.resolved_price = (
                    Decimal(f"{resolved_price:.8f}") if resolved_price is not None else None
                )
                if new_status == "HIT_TP":
                    stats["hit_tp"] += 1
                    _append_setup_history(
                        setup,
                        event="HIT_TP",
                        status="HIT_TP",
                        price=resolved_price,
                        note="Kena Take Profit (Manual Taken)" if setup.manual_action_at else "Kena Take Profit setelah Entry",
                        at_dt=ev_dt,
                    )
                elif new_status == "HIT_SL":
                    stats["hit_sl"] += 1
                    had_entry = bool(setup.entry_hit_at or setup.manual_action_at)
                    _append_setup_history(
                        setup,
                        event="HIT_SL" if had_entry else "SL_BEFORE_ENTRY",
                        status="HIT_SL",
                        price=resolved_price,
                        note="Kena Stop Loss setelah Entry" if had_entry else "Jebol Stop Loss sebelum menyentuh Entry",
                        at_dt=ev_dt,
                    )
                elif new_status == "EXPIRED":
                    stats["expired"] += 1
                    _append_setup_history(
                        setup,
                        event="EXPIRED",
                        status="EXPIRED",
                        price=resolved_price,
                        note="Setup expired (sempat kena TP tanpa Entry)" if setup.missed_tp_at and not setup.entry_hit_at else "Melewati batas Setup Expiry",
                        at_dt=ev_dt,
                    )

    db.commit()
    return stats
