"""Unit tests for deterministic technical features and MEXC kline parsing."""

import math

from app.scanner.features import compute_indicators_df, prefilter_and_build_snapshot
from app.scanner.mexc_public import parse_mexc_kline_payload


def _make_candles(n: int = 120, start_price: float = 100.0, step: float = 0.4) -> list[dict]:
    candles = []
    price = start_price
    for i in range(n):
        open_p = price
        close_p = price + step + (0.2 if i % 3 == 0 else -0.1)
        high_p = max(open_p, close_p) + 0.8
        low_p = min(open_p, close_p) - 0.7
        candles.append(
            {
                "time": 1_700_000_000 + i * 900,
                "open": open_p,
                "high": high_p,
                "low": low_p,
                "close": close_p,
                "volume": 1000.0 + (i % 5) * 200.0,
            }
        )
        price = close_p
    return candles


def test_parse_mexc_kline_payload_normalizes_ms_and_sorts():
    raw = {
        "time": [1700000900000, 1700000000000],
        "open": [101.0, 100.0],
        "high": [103.0, 102.0],
        "low": [100.5, 99.0],
        "close": [102.0, 101.0],
        "vol": [500.0, 400.0],
    }
    parsed = parse_mexc_kline_payload(raw)
    assert len(parsed) == 2
    assert parsed[0]["time"] == 1700000000
    assert parsed[1]["time"] == 1700000900
    assert parsed[0]["close"] == 101.0


def test_compute_indicators_df_outputs_valid_values():
    candles = _make_candles(120)
    df = compute_indicators_df(candles)
    last = df.iloc[-1]
    assert not math.isnan(last["ema21"])
    assert not math.isnan(last["ema50"])
    assert not math.isnan(last["ema200"])
    assert 0.0 <= last["rsi14"] <= 100.0
    assert last["atr14"] > 0.0
    assert last["volume_ratio"] > 0.0
    assert 0.0 <= last["dss"] <= 100.0
    assert 0.0 <= last["dss_signal"] <= 100.0


def test_prefilter_rejects_low_volatility_and_accepts_healthy_pair():
    htf = _make_candles(80, start_price=100.0, step=0.5)
    ltf = _make_candles(80, start_price=100.0, step=0.5)
    ticker = {"lastPrice": 135.0, "amount24": 25_000_000, "fundingRate": 0.0001, "holdVol": 100000}

    ok, reason, snap = prefilter_and_build_snapshot(
        symbol="BTC_USDT",
        ticker=ticker,
        htf_candles=htf,
        ltf_candles=ltf,
        min_atr_pct=0.1,
        max_atr_pct=10.0,
    )
    assert ok is True
    assert reason == "OK"
    assert snap is not None
    assert snap["symbol"] == "BTC_USDT"
    assert snap["ltf_15m"]["nearest_support"] < snap["ltf_15m"]["close"]
    assert 0.0 <= snap["htf_1h"]["dss"] <= 100.0
    assert 0.0 <= snap["ltf_15m"]["dss_signal"] <= 100.0
    assert "prev_dss" in snap["ltf_15m"]
    last_candle = snap["ltf_15m"]["recent_candles"][-1]
    assert last_candle["volume"] > 0.0
    assert isinstance(last_candle["is_bullish"], bool)
    assert last_candle["direction"] in ("BULLISH", "BEARISH")

    # Force dead market rejection
    dead_ok, dead_reason, _ = prefilter_and_build_snapshot(
        symbol="DEAD_USDT",
        ticker=ticker,
        htf_candles=htf,
        ltf_candles=ltf,
        min_atr_pct=99.0,
    )
    assert dead_ok is False
    assert "Low volatility" in dead_reason


def test_get_top_pairs_filters_by_min_and_max_volume():
    import asyncio
    from app.scanner.mexc_public import MexcPublicClient

    client = MexcPublicClient()

    async def fake_contracts():
        return [
            {"symbol": "BTC_USDT"},
            {"symbol": "ETH_USDT"},
            {"symbol": "SUI_USDT"},
            {"symbol": "ARB_USDT"},
            {"symbol": "LOW_USDT"},
        ]

    async def fake_tickers():
        return {
            "BTC_USDT": {"lastPrice": 90000.0, "amount24": 900_000_000},
            "ETH_USDT": {"lastPrice": 3000.0, "amount24": 400_000_000},
            "SUI_USDT": {"lastPrice": 3.2, "amount24": 60_000_000},
            "ARB_USDT": {"lastPrice": 1.1, "amount24": 25_000_000},
            "LOW_USDT": {"lastPrice": 0.5, "amount24": 500_000},
        }

    client.get_active_usdt_contracts = fake_contracts
    client.get_all_tickers = fake_tickers

    total, alts = asyncio.run(
        client.get_top_pairs(top_n=5, min_quote_volume=5_000_000, max_quote_volume=100_000_000)
    )
    assert total == 5
    assert [p["symbol"] for p in alts] == ["SUI_USDT", "ARB_USDT"]

    # 0 = unlimited max volume includes BTC/ETH again
    _, all_pairs = asyncio.run(
        client.get_top_pairs(top_n=3, min_quote_volume=5_000_000, max_quote_volume=0)
    )
    assert [p["symbol"] for p in all_pairs] == ["BTC_USDT", "ETH_USDT", "SUI_USDT"]


def test_prefilter_drops_unclosed_forming_candle():
    htf = _make_candles(80, start_price=100.0, step=0.5)
    ltf = _make_candles(80, start_price=100.0, step=0.5)
    # Last LTF candle starts at t_last; set now_ts = t_last + 180s (only 3m into a 15m candle -> unclosed)
    t_last = ltf[-1]["time"]
    ltf[-1]["volume"] = 50.0  # artificially tiny volume while forming
    now_ts = t_last + 180
    ticker = {"lastPrice": ltf[-1]["close"], "amount24": 25_000_000, "fundingRate": 0.0001, "holdVol": 100000}

    ok, reason, snap = prefilter_and_build_snapshot(
        symbol="ETH_USDT",
        ticker=ticker,
        htf_candles=htf,
        ltf_candles=ltf,
        min_atr_pct=0.1,
        max_atr_pct=10.0,
        htf_interval="Min15",
        ltf_interval="Min15",
        now_ts=now_ts,
    )
    assert ok is True
    assert reason == "OK"
    assert snap is not None
    ltf_snap = snap["ltf_15m"]
    assert ltf_snap["bars_count"] == 79
    assert ltf_snap["recent_candles"][-1]["volume"] != 50.0
    assert ltf_snap["forming_candle"]["is_closed"] is False
    assert ltf_snap["forming_candle"]["volume"] == 50.0


def test_snapshot_includes_structure_dss_cross_and_oi_normalization():
    htf = _make_candles(80, start_price=100.0, step=0.4)
    ltf = _make_candles(80, start_price=100.0, step=0.4)
    # Create a clear prior pivot low at index 65 and sweep+reclaim it on the last closed bar
    for k in range(62, 69):
        ltf[k]["low"] = 120.0
    ltf[65]["low"] = 115.0  # pivot low at index 65 (< 77)
    ltf[-1]["low"] = 114.2  # sweep below 115.0
    ltf[-1]["close"] = 116.5  # reclaim above 115.0

    ticker = {"lastPrice": 116.5, "amount24": 10_000_000, "fundingRate": -0.0006, "holdVol": 50_000}
    contract = {"symbol": "SOL_USDT", "contractSize": 1.0}

    ok, reason, snap = prefilter_and_build_snapshot(
        symbol="SOL_USDT",
        ticker=ticker,
        htf_candles=htf,
        ltf_candles=ltf,
        min_atr_pct=0.1,
        max_atr_pct=15.0,
        contract=contract,
    )
    assert ok is True, reason
    assert snap is not None
    mt = snap["market_ticker"]
    assert mt["funding_rate_pct"] == -0.06
    assert mt["funding_extreme"] is True
    assert mt["open_interest_usdt"] == round(50_000 * 1.0 * 116.5, 2)
    assert mt["oi_to_volume_ratio"] > 0

    ltf_snap = snap["ltf_15m"]
    assert len(ltf_snap["compact_candles_15"]) == 15
    assert "prev_dss_signal" in ltf_snap
    assert isinstance(ltf_snap["dss_cross_up"], bool)
    assert isinstance(ltf_snap["dss_cross_down"], bool)
    assert "ema21_slope_pct" in ltf_snap
    assert ltf_snap["prior_swing_low"] == 115.0
    assert ltf_snap["swept_prior_low"] is True
    assert ltf_snap["structure_bias"] in ("HH_HL", "LH_LL", "MIXED_RANGE", "INSUFFICIENT")

    lc = snap["level_candidates"]
    assert lc["reference_price"] == 116.5
    assert "swing_tight" in lc["long"]["sl_candidates"]
    assert "swing_swing" in lc["long"]["sl_candidates"]
    assert "htf_res" in lc["long"]["tp_candidates"]
    assert "rr_from_market_vs_sl" in lc["short"]


def test_level_candidates_use_wider_sl_buffer_for_scalp():
    from app.scanner.features import _build_level_candidates

    htf = {"atr14": 2.0, "nearest_resistance": 120.0, "nearest_support": 100.0}
    ltf = {
        "atr14": 1.0,
        "close": 110.0,
        "ema21": 110.0,
        "recent_swing_low": 108.0,
        "recent_swing_high": 112.0,
        "nearest_resistance": 115.0,
        "nearest_support": 105.0,
    }
    normal = _build_level_candidates(htf, ltf, 110.0, is_scalp=False)
    scalp = _build_level_candidates(htf, ltf, 110.0, is_scalp=True)

    assert normal["long"]["sl_candidates"] == {"swing_tight": 107.5, "swing_swing": 107.0}
    assert scalp["long"]["sl_candidates"] == {"swing_tight": 107.2, "swing_swing": 106.8}
    assert normal["short"]["sl_candidates"] == {"swing_tight": 112.5, "swing_swing": 113.0}
    assert scalp["short"]["sl_candidates"] == {"swing_tight": 112.8, "swing_swing": 113.2}


def test_prescreen_for_strategy_rules():
    from app.scanner.features import prescreen_for_strategy

    flat = {"ema_bias": "FLAT_RANGING"}
    trend = {"ema_bias": "BULLISH_ALIGNED"}
    low_vol = {"volume_ratio": 0.9}
    mid_vol = {"volume_ratio": 1.0}
    hot_vol = {"volume_ratio": 2.0}

    assert prescreen_for_strategy("TREND_PULLBACK", flat, low_vol)[0] is False
    assert prescreen_for_strategy("TREND_PULLBACK", trend, low_vol)[0] is True

    assert prescreen_for_strategy("BREAKOUT_MOMENTUM", trend, mid_vol)[0] is False
    assert prescreen_for_strategy("BREAKOUT_MOMENTUM", trend, mid_vol, "MODERATE")[0] is True
    assert prescreen_for_strategy("BREAKOUT_MOMENTUM", trend, low_vol, "AGGRESSIVE")[0] is True
    assert prescreen_for_strategy("BREAKOUT_MOMENTUM", trend, hot_vol)[0] is True

    assert prescreen_for_strategy("MEAN_REVERSION_SCALP", trend, hot_vol)[0] is False
    assert prescreen_for_strategy("MEAN_REVERSION_SCALP", trend, mid_vol)[0] is True
    assert prescreen_for_strategy("UNKNOWN_CUSTOM", flat, low_vol)[0] is True
