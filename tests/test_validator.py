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

    # Opposite direction (SHORT) on the same symbol with active LONG setup must be blocked
    opp_strat = _make_decision(
        symbol="ETH_USDT",
        decision="SHORT",
        strategy_used="MEAN_REVERSION_SCALP",
        entry_price=3000.0,
        stop_loss=3050.0,
        take_profit=2900.0,
    )
    ok_opp, _, reason_opp = validate_and_guard_setup(opp_strat, db=db)
    assert ok_opp is False
    assert "Conflicting active LONG setup" in reason_opp


def test_validator_enforces_atr_bounds_and_market_limit_entry_sanity():
    snap = {
        "market_ticker": {"last_price": 100.0},
        "ltf_15m": {"close": 100.0, "atr14": 2.0},
    }
    # 1. SL too tight (< 0.35 * 2.0 = 0.70)
    tight_sl = _make_decision(
        entry_type="LIMIT", entry_price=100.0, stop_loss=99.6, take_profit=105.0, risk_reward_ratio=12.5
    )
    ok_t, _, reason_t = validate_and_guard_setup(tight_sl, snapshot=snap)
    assert ok_t is False
    assert "SL too tight" in reason_t

    # 2. LIMIT LONG placed way above live price (> 100 + 0.25*2 = 100.5)
    bad_limit = _make_decision(entry_type="LIMIT", entry_price=102.0, stop_loss=99.0, take_profit=110.0)
    ok_l, _, reason_l = validate_and_guard_setup(bad_limit, snapshot=snap)
    assert ok_l is False
    assert "above live price" in reason_l

    # 3. MARKET entry within 0.75x ATR (1.5) is re-anchored to live_price=100.0
    mkt = _make_decision(entry_type="MARKET", entry_price=100.8, stop_loss=98.0, take_profit=105.0)
    ok_m, norm_m, _ = validate_and_guard_setup(mkt, snapshot=snap)
    assert ok_m is True
    assert norm_m.entry_price == 100.0


def test_validator_crosschecks_checklist_when_present():
    from app.schemas import SetupChecklist

    # 1. rr_ok=False must be rejected
    bad_rr = _make_decision(
        checklist=SetupChecklist(
            htf_trend_ok=True,
            pullback_or_level_ok=True,
            trigger_candle_ok=True,
            volume_ok=True,
            momentum_ok=True,
            rr_ok=False,
        )
    )
    ok_rr, _, reason_rr = validate_and_guard_setup(bad_rr)
    assert ok_rr is False
    assert "Checklist inconsistent" in reason_rr

    # 2. volume_ok=True when actual LTF volume_ratio < 1.0 must be rejected
    snap_low_vol = {
        "market_ticker": {"last_price": 100.0},
        "ltf_15m": {"close": 100.0, "atr14": 2.0, "volume_ratio": 0.65},
    }
    bad_vol = _make_decision(
        entry_type="LIMIT",
        entry_price=100.0,
        stop_loss=97.0,
        take_profit=106.0,
        checklist=SetupChecklist(
            htf_trend_ok=True,
            pullback_or_level_ok=True,
            trigger_candle_ok=True,
            volume_ok=True,
            momentum_ok=True,
            rr_ok=True,
        ),
    )
    ok_vol, _, reason_vol = validate_and_guard_setup(bad_vol, snapshot=snap_low_vol)
    assert ok_vol is False
    assert "volume_ok is true" in reason_vol
