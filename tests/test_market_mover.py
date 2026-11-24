"""Tests for BTC_USDT Market Mover scanner, strategy advisor, and API endpoints."""

from fastapi.testclient import TestClient
import pytest

from app.core.market_mover import (
    BTC_SCAN_INTERVALS,
    analyze_btc_market_mover,
    build_btc_strategy_advisor,
)
from app.core.runtime_settings import resolve_runtime_settings
from app.models import Strategy
from app.scanner.mexc_public import INTERVAL_SECONDS_MAP
from app.web.dashboard import app


def _make_trend_candles(
    n: int = 80,
    interval: str = "Min15",
    start_price: float = 90000.0,
    step: float = 120.0,
) -> list[dict]:
    step_sec = INTERVAL_SECONDS_MAP.get(interval, 900)
    out = []
    price = start_price
    for i in range(n):
        c = price + step
        hi = max(price, c) + abs(step) * 0.4 + 40.0
        lo = min(price, c) - abs(step) * 0.4 - 40.0
        out.append(
            {
                "time": 1_700_000_000 + i * step_sec,
                "open": price,
                "high": hi,
                "low": lo,
                "close": c,
                "volume": 1200.0 + (i % 5) * 100.0,
            }
        )
        price = c
    return out


def _make_ranging_candles(
    n: int = 80,
    interval: str = "Min15",
    mid_price: float = 95000.0,
    amp: float = 150.0,
) -> list[dict]:
    step_sec = INTERVAL_SECONDS_MAP.get(interval, 900)
    out = []
    for i in range(n):
        offset = amp if (i % 2 == 0) else -amp
        o = mid_price - offset * 0.3
        c = mid_price + offset * 0.3
        out.append(
            {
                "time": 1_700_000_000 + i * step_sec,
                "open": o,
                "high": mid_price + amp,
                "low": mid_price - amp,
                "close": c,
                "volume": 1000.0,
            }
        )
    return out


def test_analyze_btc_market_mover_uptrend_and_advisor(db_session):
    db, _, _ = db_session
    candles_by_iv = {iv: _make_trend_candles(90, interval=iv, step=150.0) for iv, _ in BTC_SCAN_INTERVALS}
    ticker = {
        "lastPrice": 103500.0,
        "riseFallRate": 0.032,
        "amount24": 1_500_000_000.0,
        "fundingRate": 0.0001,
    }

    analysis = analyze_btc_market_mover(candles_by_iv, ticker=ticker, now_ts=1_700_000_000 + 95 * 86400)
    assert analysis["symbol"] == "BTC_USDT"
    assert analysis["overall_regime"] == "TRENDING_UP"
    assert analysis["overall_bias"] == "BULLISH"
    assert set(analysis["styles"].keys()) == {"SCALP", "INTRADAY", "SWING"}
    assert analysis["styles"]["INTRADAY"]["available"] is True

    rt_cfg = resolve_runtime_settings(db)
    strats = db.query(Strategy).order_by(Strategy.id.asc()).all()
    advisor = build_btc_strategy_advisor(analysis, rt_cfg, strats)

    assert "TREND_PULLBACK" in advisor["suggested_settings"]["active_strategies"]
    assert "MEAN_REVERSION_SCALP" not in advisor["suggested_settings"]["active_strategies"]
    assert advisor["current_summary"]["conclusion"]
    assert advisor["suggested_settings"]["patch_payload"]["active_strategies"]


def test_analyze_btc_market_mover_ranging_suggests_scalp(db_session):
    db, _, _ = db_session
    candles_by_iv = {iv: _make_ranging_candles(90, interval=iv) for iv, _ in BTC_SCAN_INTERVALS}
    ticker = {
        "lastPrice": 95020.0,
        "riseFallRate": 0.001,
        "amount24": 900_000_000.0,
        "fundingRate": 0.00005,
    }

    analysis = analyze_btc_market_mover(candles_by_iv, ticker=ticker, now_ts=1_700_000_000 + 95 * 86400)
    assert analysis["overall_regime"] == "RANGING"
    assert analysis["overall_bias"] == "NEUTRAL"

    rt_cfg = resolve_runtime_settings(db)
    strats = db.query(Strategy).order_by(Strategy.id.asc()).all()
    advisor = build_btc_strategy_advisor(analysis, rt_cfg, strats)

    assert "MEAN_REVERSION_SCALP" in advisor["suggested_settings"]["active_strategies"]
    assert "SCALP" in advisor["suggested_settings"]["recommended_styles"]


def test_btc_market_mover_api_scan_and_apply_suggestion(db_session, monkeypatch):
    _, TestingSessionLocal, _ = db_session
    from app.core import market_mover as mm_mod
    from app.database import get_db

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    async def fake_get_all_tickers(self):
        return {
            "BTC_USDT": {
                "symbol": "BTC_USDT",
                "lastPrice": 102000.0,
                "riseFallRate": 0.025,
                "amount24": 1_200_000_000.0,
                "fundingRate": 0.0001,
            }
        }

    async def fake_get_kline(self, symbol, interval="Min15", limit=250, start_ts=None, end_ts=None):
        return _make_trend_candles(90, interval=interval, step=140.0)

    monkeypatch.setattr(mm_mod.MexcPublicClient, "get_all_tickers", fake_get_all_tickers)
    monkeypatch.setattr(mm_mod.MexcPublicClient, "get_kline", fake_get_kline)

    try:
        client = TestClient(app)

        # Before any scan
        r0 = client.get("/api/market-mover/btc")
        assert r0.status_code == 200
        assert r0.json()["has_data"] is False

        # Trigger live BTC_USDT scan
        r1 = client.post("/api/market-mover/btc/scan")
        assert r1.status_code == 200
        body1 = r1.json()
        assert body1["has_data"] is True
        report = body1["report"]
        assert report["btc"]["symbol"] == "BTC_USDT"
        assert report["btc"]["overall_regime"] == "TRENDING_UP"

        patch_payload = report["advisor"]["suggested_settings"]["patch_payload"]
        assert len(report["advisor"]["suggested_settings"]["diffs"]) >= 1

        # Apply suggested settings via existing settings API
        r_apply = client.post("/api/scanner/settings", json=patch_payload)
        assert r_apply.status_code == 200

        # Re-fetch cached BTC report: advisor should now report SELARAS
        r2 = client.get("/api/market-mover/btc")
        assert r2.status_code == 200
        assert r2.json()["has_data"] is True
        assert r2.json()["report"]["advisor"]["alignment"] == "SELARAS"
        assert r2.json()["report"]["advisor"]["suggested_settings"]["diffs"] == []
    finally:
        app.dependency_overrides.clear()
