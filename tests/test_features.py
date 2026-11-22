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
