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
) -> tuple[bool, AISetupDecision, str]:
    """Validate confidence, price geometry, deterministic R:R ratio, and OPEN duplication."""
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

    if ai_decision.entry_type == "NONE":
        normalized = ai_decision.model_copy(update={"entry_type": "LIMIT", "risk_reward_ratio": actual_rr})
    else:
        normalized = ai_decision.model_copy(update={"risk_reward_ratio": actual_rr})

    if db is not None:
        existing_open = (
            db.query(TradeSetup)
            .filter(
                TradeSetup.symbol == normalized.symbol,
                TradeSetup.decision == normalized.decision,
                TradeSetup.strategy_used == normalized.strategy_used,
                TradeSetup.status.in_(["OPEN", "ENTRY_HIT", "MANUAL_TAKEN"]),
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

    return True, normalized, "APPROVED"
