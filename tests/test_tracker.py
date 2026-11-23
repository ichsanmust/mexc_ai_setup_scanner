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
    assert setup_short.entry_hit_at is not None


@pytest.mark.asyncio
async def test_check_open_setups_records_history_and_distinguishes_before_vs_after_entry(db_session):
    from datetime import timedelta
    from app.models import utcnow

    db, _, _ = db_session
    now = utcnow()
    base_ts = int((now - timedelta(minutes=10)).replace(tzinfo=timezone.utc).timestamp())

    # 1. LIMIT LONG: touches Entry (100) -> then hits SL (95) => HIT_SL + entry_hit_at recorded
    s_sl_after = _make_custom_setup(
        symbol="AAVE_USDT", decision="LONG", status="OPEN", entry=100.0, sl=95.0, tp=110.0,
        created_at=now - timedelta(minutes=10),
    )
    # 2. LIMIT LONG: never touches Entry (100), drops straight below SL (95) => HIT_SL + entry_hit_at is None
    s_sl_before = _make_custom_setup(
        symbol="UNI_USDT", decision="LONG", status="OPEN", entry=100.0, sl=95.0, tp=110.0,
        created_at=now - timedelta(minutes=10),
    )
    # 3. LIMIT LONG: never touches Entry (100), pumps straight to TP (110) => OPEN + missed_tp_at/price recorded
    s_tp_before = _make_custom_setup(
        symbol="AVAX_USDT", decision="LONG", status="OPEN", entry=100.0, sl=95.0, tp=110.0,
        created_at=now - timedelta(minutes=10),
    )
    db.add_all([s_sl_after, s_sl_before, s_tp_before])
    db.commit()

    class FakeMexcHistory:
        async def get_all_tickers(self):
            return {
                "AAVE_USDT": {"lastPrice": "94.0"},
                "UNI_USDT": {"lastPrice": "94.0"},
                "AVAX_USDT": {"lastPrice": "111.0"},
            }

        async def get_kline(self, symbol, interval="Min15", limit=60):
            if symbol == "AAVE_USDT":
                return [
                    {"time": base_ts + 60, "open": 103.0, "high": 104.0, "low": 99.5, "close": 101.0},  # hit entry
                    {"time": base_ts + 120, "open": 101.0, "high": 102.0, "low": 94.5, "close": 95.0},  # hit SL
                ]
            if symbol == "UNI_USDT":
                return [
                    {"time": base_ts + 60, "open": 103.0, "high": 104.0, "low": 101.0, "close": 102.0},  # never hit 100
                ]
            if symbol == "AVAX_USDT":
                return [
                    {"time": base_ts + 60, "open": 103.0, "high": 110.5, "low": 102.0, "close": 110.0},  # hit TP without 100
                ]
            return []

    await check_open_setups(db, FakeMexcHistory())
    db.refresh(s_sl_after)
    db.refresh(s_sl_before)
    db.refresh(s_tp_before)

    assert s_sl_after.status == "HIT_SL"
    assert s_sl_after.entry_hit_at is not None
    assert [e["event"] for e in (s_sl_after.status_history or [])] == ["CREATED", "ENTRY_HIT", "HIT_SL"]
    assert s_sl_after.status_history[0]["price"] == 100.0
    assert s_sl_after.status_history[0]["stop_loss"] == 95.0
    assert s_sl_after.status_history[0]["take_profit"] == 110.0

    assert s_sl_before.status == "HIT_SL"
    assert s_sl_before.entry_hit_at is None
    assert [e["event"] for e in (s_sl_before.status_history or [])] == ["CREATED", "SL_BEFORE_ENTRY"]

    assert s_tp_before.status == "OPEN"
    assert s_tp_before.entry_hit_at is None
    assert s_tp_before.missed_tp_at is not None
    assert float(s_tp_before.missed_tp_price) == 110.0
    assert [e["event"] for e in (s_tp_before.status_history or [])] == ["CREATED", "TP_BEFORE_ENTRY"]


@pytest.mark.asyncio
async def test_extended_status_preserved_when_entry_touched_and_ignores_stale_candles(db_session):
    from datetime import timedelta
    from app.models import utcnow

    db, _, _ = db_session
    now = utcnow()
    ext_at = now - timedelta(minutes=2)

    # 1. Setup extended AFTER entry_hit_at was already set -> stays EXTENDED until TP/SL/Expire
    s_ext_entered = _make_custom_setup(
        symbol="SOL_USDT",
        decision="LONG",
        status="EXTENDED",
        entry=100.0,
        sl=95.0,
        tp=110.0,
        created_at=now - timedelta(hours=5),
        expires_at=now + timedelta(hours=10),
    )
    s_ext_entered.entry_hit_at = now - timedelta(hours=4)
    s_ext_entered.status_history = [
        {"at": (now - timedelta(hours=5)).isoformat(), "event": "CREATED", "status": "OPEN", "price": 100.0},
        {"at": (now - timedelta(hours=4)).isoformat(), "event": "ENTRY_HIT", "status": "ENTRY_HIT", "price": 100.0},
        {"at": ext_at.isoformat(), "event": "EXTENDED", "status": "EXTENDED", "price": 100.0},
    ]

    # 2. Setup extended BEFORE entry -> touches Entry after ext_at -> records entry_hit_at & stays EXTENDED
    s_ext_fresh = _make_custom_setup(
        symbol="ARB_USDT",
        decision="LONG",
        status="EXTENDED",
        entry=1.00,
        sl=0.95,
        tp=1.10,
        created_at=now - timedelta(hours=5),
        expires_at=now + timedelta(hours=10),
    )
    s_ext_fresh.status_history = [
        {"at": (now - timedelta(hours=5)).isoformat(), "event": "CREATED", "status": "OPEN", "price": 1.00},
        {"at": ext_at.isoformat(), "event": "EXTENDED", "status": "EXTENDED", "price": 1.00},
    ]
    db.add_all([s_ext_entered, s_ext_fresh])
    db.commit()

    stale_ts = int((now - timedelta(hours=3)).replace(tzinfo=timezone.utc).timestamp())
    fresh_ts = int((now - timedelta(minutes=1)).replace(tzinfo=timezone.utc).timestamp())

    class FakeMexcExtended:
        async def get_all_tickers(self):
            return {
                "SOL_USDT": {"lastPrice": "102.0"},
                "ARB_USDT": {"lastPrice": "1.02"},
            }

        async def get_kline(self, symbol, interval="Min1", limit=60):
            if symbol == "SOL_USDT":
                # Stale candle before EXTENDED hit SL 94.0, recent candle is safe at 101..103
                return [
                    {"time": stale_ts, "open": 96.0, "high": 97.0, "low": 94.0, "close": 95.0},
                    {"time": fresh_ts, "open": 101.0, "high": 103.0, "low": 100.5, "close": 102.0},
                ]
            if symbol == "ARB_USDT":
                return [
                    {"time": fresh_ts, "open": 1.02, "high": 1.03, "low": 0.995, "close": 1.02},
                ]
            return []

    stats = await check_open_setups(db, FakeMexcExtended())
    db.refresh(s_ext_entered)
    db.refresh(s_ext_fresh)

    assert stats["entry_hit"] == 0
    assert s_ext_entered.status == "EXTENDED"
    assert s_ext_fresh.status == "EXTENDED"
    assert s_ext_fresh.entry_hit_at is not None
    assert s_ext_fresh.status_history[-1]["event"] == "ENTRY_HIT"


def test_tracker_coarse_candle_defers_same_bar_limit_tp_and_keeps_overlapping_bucket():
    from datetime import datetime, timedelta, timezone

    # Setup created at 12:07 UTC inside a Min15 bucket that started at 12:00 UTC
    t_open = datetime(2026, 1, 1, 12, 7, 0, tzinfo=timezone.utc).replace(tzinfo=None)
    bucket_1200 = int(datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc).timestamp())
    bucket_1215 = bucket_1200 + 900

    setup_limit = _make_custom_setup(
        decision="LONG",
        status="OPEN",
        entry_type="LIMIT",
        entry=100.0,
        sl=95.0,
        tp=110.0,
        created_at=t_open,
    )

    # 1. Overlapping Min15 candle (12:00..12:15) hits BOTH entry (99.5) and TP (110.5) -> conservative ENTRY_HIT, not HIT_TP
    st, resolved = evaluate_setup_against_market(
        setup_limit,
        last_price=105.0,
        candles_since_open=[{"time": bucket_1200, "open": 102.0, "high": 110.5, "low": 99.5}],
        now=t_open + timedelta(minutes=8),
        candle_interval="Min15",
    )
    assert st == "ENTRY_HIT"
    assert resolved is None

    # 2. Once ENTRY_HIT, subsequent candle hitting TP transitions to HIT_TP
    setup_limit.status = "ENTRY_HIT"
    st2, resolved2 = evaluate_setup_against_market(
        setup_limit,
        last_price=111.0,
        candles_since_open=[{"time": bucket_1215, "open": 105.0, "high": 111.5, "low": 104.0}],
        now=t_open + timedelta(minutes=25),
        candle_interval="Min15",
    )
    assert st2 == "HIT_TP"
    assert resolved2 == 110.0

