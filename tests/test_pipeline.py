"""End-to-end pipeline test with mocked MEXC public endpoints and mocked LLM engine."""

import pytest

from app.core.pipeline import ScanPipeline
from app.models import AppSetting, ScanEvaluation, ScanRun, TradeSetup
from app.schemas import AISetupDecision


def _make_sample_candles(n: int = 80, base: float = 100.0) -> list[dict]:
    out = []
    price = base
    for i in range(n):
        c = price + 0.4
        out.append(
            {
                "time": 1_700_000_000 + i * 900,
                "open": price,
                "high": c + 0.6,
                "low": price - 0.4,
                "close": c,
                "volume": 2500.0,
            }
        )
        price = c
    return out


@pytest.mark.asyncio
async def test_pipeline_run_once_persists_valid_setup_and_logs_rejections(db_session, monkeypatch):
    db, TestingSessionLocal, _ = db_session

    # Configure commandcode key in DB
    key_row = db.query(AppSetting).filter(AppSetting.key == "commandcode_api_key").first()
    key_row.value = "test-cmd-key"
    db.commit()

    from app.core import pipeline as pipeline_mod

    monkeypatch.setattr(pipeline_mod, "SessionLocal", TestingSessionLocal)

    async def fake_get_top_pairs(self, top_n=None, min_quote_volume=None):
        return 100, [
            {
                "symbol": "BTC_USDT",
                "contract": {"symbol": "BTC_USDT"},
                "ticker": {"lastPrice": 132.0, "amount24": 50_000_000, "fundingRate": 0.0001, "holdVol": 9999},
                "amount24": 50_000_000,
            }
        ]

    async def fake_get_kline(self, symbol, interval="Min15", limit=250, start_ts=None, end_ts=None):
        return _make_sample_candles(80)

    monkeypatch.setattr(pipeline_mod.MexcPublicClient, "get_top_pairs", fake_get_top_pairs)
    monkeypatch.setattr(pipeline_mod.MexcPublicClient, "get_kline", fake_get_kline)

    async def fake_analyze(snapshot, strategy, llm_config, client=None, timeout_seconds=None):
        if strategy == "TREND_PULLBACK":
            return (
                AISetupDecision(
                    symbol=snapshot["symbol"],
                    strategy_used="TREND_PULLBACK",
                    decision="LONG",
                    market_regime="TRENDING_UP",
                    entry_type="LIMIT",
                    entry_price=131.5,
                    stop_loss=129.5,
                    take_profit=136.0,
                    risk_reward_ratio=2.25,
                    confidence=86,
                    invalidation_reason="Break below 129.5",
                    rationale="Valid HTF uptrend & LTF pullback",
                ),
                {"mock": True},
            )
        return (
            AISetupDecision(
                symbol=snapshot["symbol"],
                strategy_used=strategy,
                decision="NO_TRADE",
                market_regime="TRENDING_UP",
                entry_type="NONE",
                confidence=40,
                invalidation_reason="N/A",
                rationale="Not applicable",
            ),
            {"mock": True},
        )

    monkeypatch.setattr(pipeline_mod, "analyze_market_snapshot", fake_analyze)

    pipe = ScanPipeline()
    summary = await pipe.run_once(strategies=["TREND_PULLBACK", "MEAN_REVERSION_SCALP"], top_n=5)

    assert summary["status"] == "COMPLETED"
    assert summary["setups_created"] == 1
    assert summary["ai_analyzed"] == 2

    verify_db = TestingSessionLocal()
    try:
        setups = verify_db.query(TradeSetup).all()
        evals = verify_db.query(ScanEvaluation).all()
        runs = verify_db.query(ScanRun).all()
        assert len(setups) == 1
        assert setups[0].symbol == "BTC_USDT"
        assert setups[0].status == "OPEN"
        assert len(evals) == 1
        assert evals[0].raw_decision == "NO_TRADE"
        assert runs[-1].status == "COMPLETED"
        assert runs[-1].settings_snapshot is not None
        assert runs[-1].settings_snapshot["active_strategies"] == ["TREND_PULLBACK", "MEAN_REVERSION_SCALP"]
        assert runs[-1].settings_snapshot["top_n_pairs"] == 5
        assert "htf_interval" in runs[-1].settings_snapshot
        assert "ltf_interval" in runs[-1].settings_snapshot
    finally:
        verify_db.close()


@pytest.mark.asyncio
async def test_pipeline_marks_run_failed_when_all_ai_calls_error(db_session, monkeypatch):
    db, TestingSessionLocal, _ = db_session
    key_row = db.query(AppSetting).filter(AppSetting.key == "commandcode_api_key").first()
    key_row.value = "test-cmd-key"
    db.commit()

    from app.core import pipeline as pipeline_mod

    monkeypatch.setattr(pipeline_mod, "SessionLocal", TestingSessionLocal)

    async def fake_get_top_pairs(self, top_n=None, min_quote_volume=None):
        return 10, [
            {
                "symbol": "BTC_USDT",
                "contract": {"symbol": "BTC_USDT"},
                "ticker": {"lastPrice": 132.0, "amount24": 50_000_000},
                "amount24": 50_000_000,
            }
        ]

    async def fake_get_kline(self, symbol, interval="Min15", limit=250, start_ts=None, end_ts=None):
        return _make_sample_candles(80)

    async def failing_ai(snapshot, strategy, llm_config, client=None, timeout_seconds=None):
        raise RuntimeError("HTTP 401 Invalid API Key")

    monkeypatch.setattr(pipeline_mod.MexcPublicClient, "get_top_pairs", fake_get_top_pairs)
    monkeypatch.setattr(pipeline_mod.MexcPublicClient, "get_kline", fake_get_kline)
    monkeypatch.setattr(pipeline_mod, "analyze_market_snapshot", failing_ai)

    pipe = ScanPipeline()
    summary = await pipe.run_once(strategies=["TREND_PULLBACK"], top_n=5)
    assert summary["status"] == "FAILED"
    assert "Invalid API Key" in summary["error"]
