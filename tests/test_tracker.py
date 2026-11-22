"""Unit tests for Outcome Tracker (HIT_TP, HIT_SL, EXPIRED)."""

from datetime import timedelta, timezone
from decimal import Decimal

import pytest

from app.core.tracker import check_open_setups, evaluate_setup_against_market
from app.models import TradeSetup, utcnow


def _build_setup(decision: str = "LONG", expired: bool = False) -> TradeSetup:
    now = utcnow()
    return TradeSetup(
        symbol="SOL_USDT",
        strategy_used="BREAKOUT_MOMENTUM",
        decision=decision,
        market_regime="TRENDING_UP" if decision == "LONG" else "TRENDING_DOWN",
        entry_type="MARKET",
        entry_price=Decimal("100.0"),
        stop_loss=Decimal("95.0" if decision == "LONG" else "105.0"),
        take_profit=Decimal("110.0" if decision == "LONG" else "90.0"),
        risk_reward_ratio=Decimal("2.0"),
        confidence=85,
        invalidation_reason="test",
        rationale="test",
        status="OPEN",
        created_at=now - timedelta(hours=1),
        expires_at=now - timedelta(minutes=5) if expired else now + timedelta(hours=8),
        features_snapshot={},
        ai_payload={},
    )


def test_tracker_marks_hit_tp_and_hit_sl_from_candles():
    setup_long = _build_setup("LONG")
    open_ts = int(setup_long.created_at.replace(tzinfo=timezone.utc).timestamp())
    candles_tp = [{"time": open_ts + 900, "open": 102, "high": 111.0, "low": 100.0, "close": 109.5}]
    st, price = evaluate_setup_against_market(setup_long, last_price=109.5, candles_since_open=candles_tp)
    assert st == "HIT_TP"
    assert price == 110.0

    setup_short = _build_setup("SHORT")
    candles_sl = [{"time": open_ts + 900, "open": 101, "high": 106.0, "low": 99.0, "close": 104.0}]
    st_s, price_s = evaluate_setup_against_market(setup_short, last_price=104.0, candles_since_open=candles_sl)
    assert st_s == "HIT_SL"
    assert price_s == 105.0


def test_tracker_marks_expired_when_past_expiry():
    setup_exp = _build_setup("LONG", expired=True)
    st, price = evaluate_setup_against_market(setup_exp, last_price=101.0, candles_since_open=[])
    assert st == "EXPIRED"
    assert price == 101.0


@pytest.mark.asyncio
async def test_check_open_setups_tracks_manual_taken_and_skips_manual_skipped(db_session):
    db, _, _ = db_session
    now = utcnow()

    s_open = _build_setup("LONG")
    s_open.symbol = "BTC_USDT"
    s_open.status = "OPEN"

    s_taken = _build_setup("LONG")
    s_taken.symbol = "ETH_USDT"
    s_taken.status = "MANUAL_TAKEN"
    s_taken.manual_action_at = now

    s_skipped = _build_setup("LONG")
    s_skipped.symbol = "XRP_USDT"
    s_skipped.status = "MANUAL_SKIPPED"

    db.add_all([s_open, s_taken, s_skipped])
    db.commit()

    class FakeMexc:
        async def get_all_tickers(self):
            return {
                "BTC_USDT": {"lastPrice": 112.0},
                "ETH_USDT": {"lastPrice": 94.0},
                "XRP_USDT": {"lastPrice": 115.0},
            }

        async def get_kline(self, symbol, interval="Min15", limit=60):
            return []

    stats = await check_open_setups(db, FakeMexc())
    assert stats["checked"] == 2
    assert stats["hit_tp"] == 1
    assert stats["hit_sl"] == 1

    db.refresh(s_open)
    db.refresh(s_taken)
    db.refresh(s_skipped)
    assert s_open.status == "HIT_TP"
    assert s_taken.status == "HIT_SL"
    assert s_skipped.status == "MANUAL_SKIPPED"


def test_tracker_marks_entry_hit_on_limit_setup_before_tp_or_sl():
    setup_limit = _build_setup("LONG")
    setup_limit.entry_type = "LIMIT"
    setup_limit.entry_price = Decimal("100.0")
    setup_limit.stop_loss = Decimal("95.0")
    setup_limit.take_profit = Decimal("110.0")
    open_ts = int(setup_limit.created_at.replace(tzinfo=timezone.utc).timestamp())

    # Price dips to 99.5 (touches entry=100) without hitting SL=95 or TP=110 -> ENTRY_HIT
    candles_entry = [{"time": open_ts + 900, "open": 103.0, "high": 104.0, "low": 99.5, "close": 101.0}]
    st, resolved = evaluate_setup_against_market(setup_limit, last_price=101.0, candles_since_open=candles_entry)
    assert st == "ENTRY_HIT"
    assert resolved is None

    # Once ENTRY_HIT, hitting TP=110 transitions to HIT_TP
    setup_limit.status = "ENTRY_HIT"
    candles_tp = [{"time": open_ts + 1800, "open": 101.0, "high": 110.5, "low": 100.5, "close": 110.0}]
    st2, resolved2 = evaluate_setup_against_market(setup_limit, last_price=110.0, candles_since_open=candles_tp)
    assert st2 == "HIT_TP"
    assert resolved2 == 110.0


def _make_custom_setup(
    *,
    symbol: str = "BTC_USDT",
    decision: str = "LONG",
    status: str = "OPEN",
    entry_type: str = "LIMIT",
    entry: float = 100.0,
    sl: float = 95.0,
    tp: float = 110.0,
    created_at=None,
    expires_at=None,
    manual_action_at=None,
):
    from datetime import datetime, timedelta, timezone
    from decimal import Decimal
    from app.models import TradeSetup

    base = created_at or datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc).replace(tzinfo=None)
    return TradeSetup(
        symbol=symbol,
        strategy_used="PULLBACK_EMA",
        decision=decision,
        market_regime="TRENDING_UP" if decision == "LONG" else "TRENDING_DOWN",
        entry_type=entry_type,
        entry_price=Decimal(str(entry)),
        stop_loss=Decimal(str(sl)),
        take_profit=Decimal(str(tp)),
        risk_reward_ratio=Decimal("2.0"),
        confidence=80,
        invalidation_reason="test",
        rationale="test",
        status=status,
        manual_action_at=manual_action_at,
        expires_at=expires_at or (base + timedelta(hours=24)),
        features_snapshot={},
        ai_payload={},
        created_at=base,
    )


def test_tracker_long_and_short_entry_hit_when_price_already_past_entry():
    from datetime import datetime, timezone

    t0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc).replace(tzinfo=None)
    t0_ts = int(t0.replace(tzinfo=timezone.utc).timestamp())

    # LONG: last_price already below entry (above SL) -> ENTRY_HIT
    long_setup = _make_custom_setup(decision="LONG", status="OPEN", entry=100.0, sl=95.0, tp=110.0, created_at=t0)
    assert evaluate_setup_against_market(long_setup, last_price=98.5, candles_since_open=[], now=t0) == ("ENTRY_HIT", None)

    # LONG: candle completely below entry (above SL) -> ENTRY_HIT
    assert evaluate_setup_against_market(
        long_setup,
        last_price=101.0,
        candles_since_open=[{"time": t0_ts + 60, "high": 99.5, "low": 97.0}],
        now=t0,
    ) == ("ENTRY_HIT", None)

    # SHORT: last_price already above entry (below SL) -> ENTRY_HIT
    short_setup = _make_custom_setup(decision="SHORT", status="OPEN", entry=100.0, sl=105.0, tp=90.0, created_at=t0)
    assert evaluate_setup_against_market(short_setup, last_price=102.0, candles_since_open=[], now=t0) == ("ENTRY_HIT", None)

    # SHORT: candle completely above entry (below SL) -> ENTRY_HIT
    assert evaluate_setup_against_market(
        short_setup,
        last_price=99.0,
        candles_since_open=[{"time": t0_ts + 60, "high": 103.5, "low": 101.0}],
        now=t0,
    ) == ("ENTRY_HIT", None)


def test_tracker_long_and_short_sl_tp_via_last_price_and_unfilled_guard():
    from datetime import datetime, timezone

    t0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc).replace(tzinfo=None)
    t0_ts = int(t0.replace(tzinfo=timezone.utc).timestamp())

    # Active ENTRY_HIT LONG reacts immediately to last_price past SL or TP
    long_active = _make_custom_setup(decision="LONG", status="ENTRY_HIT", entry=100.0, sl=95.0, tp=110.0, created_at=t0)
    assert evaluate_setup_against_market(long_active, last_price=94.0, candles_since_open=[], now=t0) == ("HIT_SL", 94.0)
    assert evaluate_setup_against_market(long_active, last_price=112.0, candles_since_open=[], now=t0) == ("HIT_TP", 112.0)

    # Active ENTRY_HIT SHORT reacts immediately to last_price past SL or TP
    short_active = _make_custom_setup(decision="SHORT", status="ENTRY_HIT", entry=100.0, sl=105.0, tp=90.0, created_at=t0)
    assert evaluate_setup_against_market(short_active, last_price=106.5, candles_since_open=[], now=t0) == ("HIT_SL", 106.5)
    assert evaluate_setup_against_market(short_active, last_price=88.0, candles_since_open=[], now=t0) == ("HIT_TP", 88.0)

    # Unfilled OPEN LIMIT setup must NOT mark HIT_TP if entry was never touched
    long_open = _make_custom_setup(decision="LONG", status="OPEN", entry=100.0, sl=95.0, tp=110.0, created_at=t0)
    assert evaluate_setup_against_market(
        long_open,
        last_price=112.0,
        candles_since_open=[{"time": t0_ts + 60, "high": 108.0, "low": 101.0}],
        now=t0,
    ) == (None, None)

    short_open = _make_custom_setup(decision="SHORT", status="OPEN", entry=100.0, sl=105.0, tp=90.0, created_at=t0)
    assert evaluate_setup_against_market(
        short_open,
        last_price=88.0,
        candles_since_open=[{"time": t0_ts + 60, "high": 99.0, "low": 91.0}],
        now=t0,
    ) == (None, None)


def test_tracker_ignores_candles_before_creation_and_before_manual_action():
    from datetime import datetime, timedelta, timezone

    t0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc).replace(tzinfo=None)
    t0_ts = int(t0.replace(tzinfo=timezone.utc).timestamp())

    # Candle 3 minutes before setup creation hitting SL must be ignored
    setup_open = _make_custom_setup(decision="LONG", status="OPEN", entry=100.0, sl=95.0, tp=110.0, created_at=t0)
    assert evaluate_setup_against_market(
        setup_open,
        last_price=102.0,
        candles_since_open=[
            {"time": t0_ts - 180, "high": 103.0, "low": 90.0},
            {"time": t0_ts + 60, "high": 103.0, "low": 101.0},
        ],
        now=t0 + timedelta(minutes=2),
    ) == (None, None)

    # MANUAL_TAKEN SHORT only evaluates candles from manual_action_at onward
    taken_at = t0 + timedelta(minutes=10)
    setup_taken = _make_custom_setup(
        decision="SHORT",
        status="MANUAL_TAKEN",
        entry=100.0,
        sl=105.0,
        tp=90.0,
        created_at=t0,
        manual_action_at=taken_at,
    )
    assert evaluate_setup_against_market(
        setup_taken,
        last_price=95.0,
        candles_since_open=[
            {"time": t0_ts + 300, "high": 108.0, "low": 99.0},   # before manual_action_at -> ignored
            {"time": t0_ts + 660, "high": 98.0, "low": 89.5},    # after manual_action_at -> HIT_TP
        ],
        now=taken_at + timedelta(minutes=2),
    ) == ("HIT_TP", 90.0)


@pytest.mark.asyncio
async def test_check_open_setups_uses_min1_and_marks_short_entry_hit(db_session):
    from datetime import timedelta
    from app.models import utcnow

    db, _, _ = db_session
    now = utcnow()
    setup_short = _make_custom_setup(
        symbol="ETH_USDT",
        decision="SHORT",
        status="OPEN",
        entry=2000.0,
        sl=2050.0,
        tp=1900.0,
        created_at=now - timedelta(minutes=5),
    )
    db.add(setup_short)
    db.commit()

    seen_calls = []

    class FakeMexcMin1:
        async def get_all_tickers(self):
            return {"ETH_USDT": {"lastPrice": "2010.0"}}

        async def get_kline(self, symbol, interval="Min15", limit=60):
            seen_calls.append((symbol, interval, limit))
            return []

    stats = await check_open_setups(db, FakeMexcMin1())
    db.refresh(setup_short)

    assert seen_calls and seen_calls[0][1] == "Min1"
    assert stats == {"checked": 1, "entry_hit": 1, "hit_tp": 0, "hit_sl": 0, "expired": 0}
    assert setup_short.status == "ENTRY_HIT"
