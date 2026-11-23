"""Deterministic Risk & Math Guard validating AI trading setups."""

import math
from typing import Optional

from sqlalchemy.orm import Session

from ..config import STRATEGY_MIN_RR, settings
from ..models import Strategy, TradeSetup
from ..schemas import AISetupDecision
from .runtime_settings import resolve_runtime_settings


def _clear_execution_levels(decision: AISetupDecision) -> AISetupDecision:
    """Return copy of decision normalized to NO_TRADE with null price levels."""
    return decision.model_copy(
        update={
            "decision": "NO_TRADE",
            "entry_type": "NONE",
            "entry_price": None,
            "stop_loss": None,
            "take_profit": None,
            "risk_reward_ratio": None,
        }
    )


def validate_and_guard_setup(
    ai_decision: AISetupDecision,
    db: Optional[Session] = None,
    min_confidence: Optional[int] = None,
    snapshot: Optional[dict] = None,
) -> tuple[bool, AISetupDecision, str]:
    """Validate confidence, price geometry, ATR/direction bounds, R:R ratio, and OPEN conflicts."""
    if min_confidence is not None:
        conf_threshold = min_confidence
    elif db is not None:
        conf_threshold = resolve_runtime_settings(db)["min_confidence"]
    else:
        conf_threshold = settings.min_confidence

    if ai_decision.decision == "NO_TRADE":
        return False, _clear_execution_levels(ai_decision), "AI returned NO_TRADE"

    if ai_decision.confidence < conf_threshold:
        return (
            False,
            _clear_execution_levels(ai_decision),
            f"Confidence {ai_decision.confidence} < threshold {conf_threshold}",
        )

    entry = ai_decision.entry_price
    sl = ai_decision.stop_loss
    tp = ai_decision.take_profit

    if entry is None or sl is None or tp is None:
        return False, _clear_execution_levels(ai_decision), "Missing entry_price, stop_loss, or take_profit"

    if not (math.isfinite(entry) and math.isfinite(sl) and math.isfinite(tp)):
        return False, _clear_execution_levels(ai_decision), "Non-finite price level"

    if entry <= 0 or sl <= 0 or tp <= 0:
        return False, _clear_execution_levels(ai_decision), "Price levels must be strictly positive"

    # Snapshot-aware ATR & live price sanity checks
    snap_ltf = (snapshot or {}).get("ltf_15m") or {}
    snap_ticker = (snapshot or {}).get("market_ticker") or {}
    live_price = float(snap_ticker.get("last_price") or snap_ltf.get("close") or 0.0)
    atr14 = float(snap_ltf.get("atr14") or 0.0)

    # Cross-check AI checklist consistency when provided
    if ai_decision.checklist is not None:
        if not ai_decision.checklist.rr_ok:
            return (
                False,
                _clear_execution_levels(ai_decision),
                "Checklist inconsistent: rr_ok is false for trade setup",
            )
        if not ai_decision.checklist.trigger_candle_ok:
            return (
                False,
                _clear_execution_levels(ai_decision),
                "Checklist inconsistent: trigger_candle_ok is false for trade setup",
            )
        if snapshot is not None and ai_decision.checklist.volume_ok:
            vol_ratio = snap_ltf.get("volume_ratio")
            if vol_ratio is not None and float(vol_ratio) < 1.0:
                return (
                    False,
                    _clear_execution_levels(ai_decision),
                    f"Checklist inconsistent: volume_ok is true but LTF volume_ratio ({float(vol_ratio):.2f}) < 1.0",
                )

    if live_price > 0 and atr14 > 0:
        if ai_decision.entry_type == "MARKET":
            if abs(entry - live_price) > 0.75 * atr14:
                return (
                    False,
                    _clear_execution_levels(ai_decision),
                    f"MARKET entry ({entry}) too far from live price ({live_price}) relative to ATR ({atr14:.6g})",
                )
            # Re-anchor MARKET entry to actual live price
            entry = live_price
        elif ai_decision.entry_type == "LIMIT":
            if ai_decision.decision == "LONG":
                if entry > live_price + 0.25 * atr14:
                    return (
                        False,
                        _clear_execution_levels(ai_decision),
                        f"LIMIT LONG entry ({entry}) above live price ({live_price}) + 0.25x ATR",
                    )
                if live_price - entry > 2.5 * atr14:
                    return (
                        False,
                        _clear_execution_levels(ai_decision),
                        f"LIMIT LONG entry ({entry}) too far below live price ({live_price}) (> 2.5x ATR)",
                    )
            elif ai_decision.decision == "SHORT":
                if entry < live_price - 0.25 * atr14:
                    return (
                        False,
                        _clear_execution_levels(ai_decision),
                        f"LIMIT SHORT entry ({entry}) below live price ({live_price}) - 0.25x ATR",
                    )
                if entry - live_price > 2.5 * atr14:
                    return (
                        False,
                        _clear_execution_levels(ai_decision),
                        f"LIMIT SHORT entry ({entry}) too far above live price ({live_price}) (> 2.5x ATR)",
                    )

    if ai_decision.decision == "LONG":
        if not (sl < entry < tp):
            return (
                False,
                _clear_execution_levels(ai_decision),
                f"Invalid LONG geometry: expected SL({sl}) < Entry({entry}) < TP({tp})",
            )
    elif ai_decision.decision == "SHORT":
        if not (tp < entry < sl):
            return (
                False,
                _clear_execution_levels(ai_decision),
                f"Invalid SHORT geometry: expected TP({tp}) < Entry({entry}) < SL({sl})",
            )

    risk = abs(entry - sl)
    reward = abs(tp - entry)
    if risk <= 0:
        return False, _clear_execution_levels(ai_decision), "Zero risk distance between entry and stop_loss"

    if atr14 > 0:
        sl_atr_mult = risk / atr14
        if sl_atr_mult < 0.35:
            return (
                False,
                _clear_execution_levels(ai_decision),
                f"SL too tight ({sl_atr_mult:.2f}x ATR < 0.35x ATR)",
            )
        if sl_atr_mult > 5.0:
            return (
                False,
                _clear_execution_levels(ai_decision),
                f"SL too wide ({sl_atr_mult:.2f}x ATR > 5.0x ATR)",
            )

    if snapshot is not None:
        # Deduct conservative 0.04% round-trip fee buffer when market snapshot is present
        fee_buf = entry * 0.0004
        actual_rr = round(max(0.0, reward - fee_buf) / (risk + fee_buf), 4)
    else:
        actual_rr = round(reward / risk, 4)

    strat_key = ai_decision.strategy_used.strip().upper()
    min_rr = STRATEGY_MIN_RR.get(strat_key, 1.5)
    if db is not None:
        strat_row = db.query(Strategy).filter(Strategy.name == strat_key).first()
        if strat_row is not None and strat_row.min_rr is not None:
            min_rr = float(strat_row.min_rr)
    if actual_rr < min_rr:
        return (
            False,
            _clear_execution_levels(ai_decision),
            f"Calculated R:R {actual_rr:.2f} < minimum {min_rr:.2f} for {ai_decision.strategy_used}",
        )

    updates: dict = {"entry_price": entry, "risk_reward_ratio": actual_rr}
    if ai_decision.entry_type == "NONE":
        updates["entry_type"] = "LIMIT"
    normalized = ai_decision.model_copy(update=updates)

    if db is not None:
        existing_open = (
            db.query(TradeSetup)
            .filter(
                TradeSetup.symbol == normalized.symbol,
                TradeSetup.decision == normalized.decision,
                TradeSetup.strategy_used == normalized.strategy_used,
                TradeSetup.status.in_(["OPEN", "ENTRY_HIT", "MANUAL_TAKEN", "EXTENDED"]),
            )
            .first()
        )
        if existing_open:
            return (
                False,
                _clear_execution_levels(normalized),
                (
                    f"Duplicate OPEN setup already exists (#{existing_open.id}) "
                    f"for {normalized.symbol} {normalized.decision} ({normalized.strategy_used})"
                ),
            )

        opposite_decision = "SHORT" if normalized.decision == "LONG" else "LONG"
        conflicting_open = (
            db.query(TradeSetup)
            .filter(
                TradeSetup.symbol == normalized.symbol,
                TradeSetup.decision == opposite_decision,
                TradeSetup.status.in_(["OPEN", "ENTRY_HIT", "MANUAL_TAKEN", "EXTENDED"]),
            )
            .first()
        )
        if conflicting_open:
            return (
                False,
                _clear_execution_levels(normalized),
                (
                    f"Conflicting active {opposite_decision} setup (#{conflicting_open.id}, "
                    f"{conflicting_open.strategy_used}) already exists for {normalized.symbol}"
                ),
            )

    return True, normalized, "APPROVED"
