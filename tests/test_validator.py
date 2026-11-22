"""Unit tests for deterministic Risk & Math Guard."""

from datetime import timedelta
from decimal import Decimal

from app.core.validator import validate_and_guard_setup
from app.models import TradeSetup, utcnow
from app.schemas import AISetupDecision


def _make_decision(**overrides) -> AISetupDecision:
    base = {
        "symbol": "ETH_USDT",
        "strategy_used": "TREND_PULLBACK",
        "decision": "LONG",
        "market_regime": "TRENDING_UP",
        "entry_type": "LIMIT",
        "entry_price": 3000.0,
        "stop_loss": 2950.0,
        "take_profit": 3100.0,
        "risk_reward_ratio": 2.0,
        "confidence": 82,
        "invalidation_reason": "Break below 2950 swing low",
        "rationale": "HTF uptrend + pullback to EMA21",
    }
    base.update(overrides)
    return AISetupDecision(**base)


def test_validator_rejects_low_confidence_and_clears_prices():
    d = _make_decision(confidence=74)
    ok, normalized, reason = validate_and_guard_setup(d)
    assert ok is False
    assert "74 < threshold 75" in reason
    assert normalized.decision == "NO_TRADE"
    assert normalized.entry_type == "NONE"
    assert normalized.entry_price is None
    assert normalized.stop_loss is None
    assert normalized.take_profit is None


def test_validator_rejects_invalid_long_and_short_geometry():
    bad_long = _make_decision(decision="LONG", entry_price=3000.0, stop_loss=3010.0, take_profit=3100.0)
    ok_l, _, reason_l = validate_and_guard_setup(bad_long)
    assert ok_l is False
    assert "Invalid LONG geometry" in reason_l

    bad_short = _make_decision(decision="SHORT", entry_price=3000.0, stop_loss=3050.0, take_profit=3020.0)
    ok_s, _, reason_s = validate_and_guard_setup(bad_short)
    assert ok_s is False
    assert "Invalid SHORT geometry" in reason_s


def test_validator_recomputes_rr_and_enforces_strategy_minimum():
    # AI claims RR 2.5, but actual is (3080-3000)/(3000-2950) = 1.6 < 1.8 for TREND_PULLBACK
    d = _make_decision(
        strategy_used="TREND_PULLBACK",
        entry_price=3000.0,
        stop_loss=2950.0,
        take_profit=3080.0,
        risk_reward_ratio=2.5,
    )
    ok, _, reason = validate_and_guard_setup(d)
    assert ok is False
    assert "1.60 < minimum 1.80" in reason

    # MEAN_REVERSION_SCALP allows 1.5
    d_mr = _make_decision(
        strategy_used="MEAN_REVERSION_SCALP",
        market_regime="RANGING",
        entry_price=3000.0,
        stop_loss=2950.0,
        take_profit=3080.0,
    )
    ok_mr, norm_mr, _ = validate_and_guard_setup(d_mr)
    assert ok_mr is True
    assert norm_mr.risk_reward_ratio == 1.6


def test_validator_blocks_duplicate_open_setup(db_session):
    db, _, _ = db_session
    now = utcnow()
    existing = TradeSetup(
        symbol="ETH_USDT",
        strategy_used="TREND_PULLBACK",
        decision="LONG",
        market_regime="TRENDING_UP",
        entry_type="LIMIT",
        entry_price=Decimal("3000.0"),
        stop_loss=Decimal("2950.0"),
        take_profit=Decimal("3100.0"),
        risk_reward_ratio=Decimal("2.0"),
        confidence=85,
        invalidation_reason="test",
        rationale="test",
        status="OPEN",
        expires_at=now + timedelta(hours=12),
        features_snapshot={},
        ai_payload={},
    )
    db.add(existing)
    db.commit()

    dup = _make_decision(symbol="ETH_USDT", decision="LONG", strategy_used="TREND_PULLBACK")
    ok, _, reason = validate_and_guard_setup(dup, db=db)
    assert ok is False
    assert "Duplicate OPEN setup" in reason

    # Same symbol + decision on a DIFFERENT strategy is allowed for multi-strategy confluence & analytics
    other_strat = _make_decision(
        symbol="ETH_USDT",
        decision="LONG",
        strategy_used="BREAKOUT_MOMENTUM",
        entry_price=3000.0,
        stop_loss=2950.0,
        take_profit=3100.0,
    )
    ok_other, norm_other, reason_other = validate_and_guard_setup(other_strat, db=db)
    assert ok_other is True
    assert reason_other == "APPROVED"
    assert norm_other.strategy_used == "BREAKOUT_MOMENTUM"
