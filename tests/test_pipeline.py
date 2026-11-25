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
        assert len(setups[0].ai_payload.get("prompt_version", "")) == 8
        assert len(evals) == 1
        assert evals[0].raw_decision == "NO_TRADE"
        assert runs[-1].status == "COMPLETED"
        assert runs[-1].settings_snapshot is not None
        assert runs[-1].settings_snapshot["active_strategies"] == ["TREND_PULLBACK", "MEAN_REVERSION_SCALP"]
        assert runs[-1].settings_snapshot["top_n_pairs"] == 5
        assert "strategy_timeframes" in runs[-1].settings_snapshot
        assert "htf_interval" not in runs[-1].settings_snapshot
        assert "ltf_interval" not in runs[-1].settings_snapshot
        assert "kline_limit" not in runs[-1].settings_snapshot
        assert "setup_expiry_hours" not in runs[-1].settings_snapshot
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


@pytest.mark.asyncio
async def test_pipeline_multi_strategy_resolves_per_strategy_timeframes_and_deduplicates_klines(db_session, monkeypatch):
    db, TestingSessionLocal, _ = db_session
    key_row = db.query(AppSetting).filter(AppSetting.key == "commandcode_api_key").first()
    key_row.value = "test-cmd-key"
    db.commit()

    from app.core import pipeline as pipeline_mod

    monkeypatch.setattr(pipeline_mod, "SessionLocal", TestingSessionLocal)

    fetched_intervals: list[tuple[str, str]] = []

    async def fake_get_top_pairs(self, top_n=None, min_quote_volume=None):
        return 20, [
            {
                "symbol": "ETH_USDT",
                "contract": {"symbol": "ETH_USDT"},
                "ticker": {"lastPrice": 132.0, "amount24": 50_000_000, "fundingRate": 0.0001, "holdVol": 5000},
                "amount24": 50_000_000,
            }
        ]

    async def fake_get_kline(self, symbol, interval="Min15", limit=250, start_ts=None, end_ts=None):
        fetched_intervals.append((symbol, interval))
        return _make_sample_candles(80)

    seen_intervals_by_strat: dict[str, tuple[str, str]] = {}

    async def fake_analyze(snapshot, strategy, llm_config, client=None, timeout_seconds=None):
        seen_intervals_by_strat[strategy] = (
            snapshot["htf_1h"]["interval"],
            snapshot["ltf_15m"]["interval"],
        )
        return (
            AISetupDecision(
                symbol=snapshot["symbol"],
                strategy_used=strategy,
                decision="NO_TRADE",
                market_regime="RANGING",
                entry_type="NONE",
                confidence=40,
                invalidation_reason="N/A",
                rationale="Dry check",
            ),
            {"mock": True},
        )

    monkeypatch.setattr(pipeline_mod.MexcPublicClient, "get_top_pairs", fake_get_top_pairs)
    monkeypatch.setattr(pipeline_mod.MexcPublicClient, "get_kline", fake_get_kline)
    monkeypatch.setattr(pipeline_mod, "analyze_market_snapshot", fake_analyze)

    pipe = ScanPipeline()
    # TREND_PULLBACK + BREAKOUT_MOMENTUM share Min60/Min15; MEAN_REVERSION_SCALP uses Min30/Min5
    summary = await pipe.run_once(
        strategies=["TREND_PULLBACK", "BREAKOUT_MOMENTUM", "MEAN_REVERSION_SCALP"],
        top_n=5,
    )
    assert summary["status"] == "COMPLETED"
    # Sample candles have constant volume (volume_ratio = 1.0 < 1.2), so the deterministic
    # prescreen rejects BREAKOUT_MOMENTUM before the AI call (mirrors its prompt rule).
    assert summary["ai_analyzed"] == 2
    assert summary["prescreen_skipped"] == 1
    assert "BREAKOUT_MOMENTUM" not in seen_intervals_by_strat
    # Min60 and Min15 must only be fetched ONCE per symbol even though two strategies use them
    eth_fetched = [x for x in fetched_intervals if x[0] == "ETH_USDT"]
    btc_fetched = [x for x in fetched_intervals if x[0] == "BTC_USDT"]
    assert len(eth_fetched) == 4
    assert len(btc_fetched) == 4
    assert set(eth_fetched) == {
        ("ETH_USDT", "Min60"),
        ("ETH_USDT", "Min15"),
        ("ETH_USDT", "Min30"),
        ("ETH_USDT", "Min5"),
    }
    assert seen_intervals_by_strat["TREND_PULLBACK"] == ("Min60", "Min15")
    assert seen_intervals_by_strat["MEAN_REVERSION_SCALP"] == ("Min30", "Min5")

    verify_db = TestingSessionLocal()
    try:
        latest_run = verify_db.query(ScanRun).order_by(ScanRun.id.desc()).first()
        tf_map = latest_run.settings_snapshot["strategy_timeframes"]
        assert tf_map["MEAN_REVERSION_SCALP"]["htf"] == "Min30"
        assert tf_map["MEAN_REVERSION_SCALP"]["ltf"] == "Min5"
    finally:
        verify_db.close()


@pytest.mark.asyncio
async def test_pipeline_single_strategy_also_uses_per_strategy_timeframe(db_session, monkeypatch):
    db, TestingSessionLocal, _ = db_session
    key_row = db.query(AppSetting).filter(AppSetting.key == "commandcode_api_key").first()
    key_row.value = "test-cmd-key"
    db.commit()

    from app.core import pipeline as pipeline_mod

    monkeypatch.setattr(pipeline_mod, "SessionLocal", TestingSessionLocal)

    async def fake_get_top_pairs(self, top_n=None, min_quote_volume=None):
        return 10, [
            {
                "symbol": "SOL_USDT",
                "contract": {"symbol": "SOL_USDT"},
                "ticker": {"lastPrice": 132.0, "amount24": 50_000_000, "fundingRate": 0.0001, "holdVol": 5000},
                "amount24": 50_000_000,
            }
        ]

    async def fake_get_kline(self, symbol, interval="Min15", limit=250, start_ts=None, end_ts=None):
        return _make_sample_candles(80)

    seen_single: list[tuple[str, str]] = []
    seen_contexts: list[dict] = []

    async def fake_analyze(snapshot, strategy, llm_config, client=None, timeout_seconds=None):
        seen_single.append((snapshot["htf_1h"]["interval"], snapshot["ltf_15m"]["interval"]))
        if snapshot.get("market_context"):
            seen_contexts.append(snapshot["market_context"])
        return (
            AISetupDecision(
                symbol=snapshot["symbol"],
                strategy_used=strategy,
                decision="NO_TRADE",
                market_regime="RANGING",
                entry_type="NONE",
                confidence=40,
                invalidation_reason="N/A",
                rationale="Dry check",
            ),
            {"mock": True},
        )

    monkeypatch.setattr(pipeline_mod.MexcPublicClient, "get_top_pairs", fake_get_top_pairs)
    monkeypatch.setattr(pipeline_mod.MexcPublicClient, "get_kline", fake_get_kline)
    monkeypatch.setattr(pipeline_mod, "analyze_market_snapshot", fake_analyze)

    pipe = ScanPipeline()
    # Even with global defaults at Min60/Min15, MEAN_REVERSION_SCALP uses its own Min30/Min5
    summary = await pipe.run_once(strategies=["MEAN_REVERSION_SCALP"], top_n=5)
    assert summary["status"] == "COMPLETED"
    assert seen_single == [("Min30", "Min5")]
    assert len(seen_contexts) == 1
    assert seen_contexts[0]["btc"]["htf"]["interval"] == "Min30"
    assert seen_contexts[0]["btc"]["ltf"]["interval"] == "Min5"


@pytest.mark.asyncio
async def test_pipeline_custom_pair_selection_mode_scans_only_selected_pairs(db_session, monkeypatch):
    db, TestingSessionLocal, _ = db_session
    key_row = db.query(AppSetting).filter(AppSetting.key == "commandcode_api_key").first()
    key_row.value = "test-cmd-key"
    db.add(AppSetting(key="pair_selection_mode", value="CUSTOM"))
    db.add(AppSetting(key="selected_pairs", value="ARB_USDT, SUI_USDT"))
    db.commit()

    from app.core import pipeline as pipeline_mod

    monkeypatch.setattr(pipeline_mod, "SessionLocal", TestingSessionLocal)

    async def fake_contracts(self):
        return [
            {"symbol": "BTC_USDT", "quoteCoin": "USDT", "state": 0},
            {"symbol": "ARB_USDT", "quoteCoin": "USDT", "state": 0},
            {"symbol": "SUI_USDT", "quoteCoin": "USDT", "state": 0},
        ]

    async def fake_tickers(self):
        return {
            "BTC_USDT": {"symbol": "BTC_USDT", "lastPrice": 90000.0, "amount24": 900_000_000, "fundingRate": 0.0001, "holdVol": 10000},
            "ARB_USDT": {"symbol": "ARB_USDT", "lastPrice": 1.1, "amount24": 100_000, "fundingRate": 0.0001, "holdVol": 1000},
            "SUI_USDT": {"symbol": "SUI_USDT", "lastPrice": 3.2, "amount24": 200_000, "fundingRate": 0.0001, "holdVol": 2000},
        }

    async def fake_get_kline(self, symbol, interval="Min15", limit=250, start_ts=None, end_ts=None):
        return _make_sample_candles(80)

    analyzed_symbols: list[str] = []

    async def fake_analyze(snapshot, strategy, llm_config, client=None, timeout_seconds=None):
        analyzed_symbols.append(snapshot["symbol"])
        return (
            AISetupDecision(
                symbol=snapshot["symbol"],
                strategy_used=strategy,
                decision="NO_TRADE",
                market_regime="RANGING",
                entry_type="NONE",
                confidence=40,
                invalidation_reason="N/A",
                rationale="Custom pair test",
            ),
            {"mock": True},
        )

    monkeypatch.setattr(pipeline_mod.MexcPublicClient, "get_active_usdt_contracts", fake_contracts)
    monkeypatch.setattr(pipeline_mod.MexcPublicClient, "get_all_tickers", fake_tickers)
    monkeypatch.setattr(pipeline_mod.MexcPublicClient, "get_kline", fake_get_kline)
    monkeypatch.setattr(pipeline_mod, "analyze_market_snapshot", fake_analyze)

    pipe = ScanPipeline()
    summary = await pipe.run_once(strategies=["TREND_PULLBACK"])
    assert summary["status"] == "COMPLETED"
    assert set(analyzed_symbols) == {"ARB_USDT", "SUI_USDT"}

    verify_db = TestingSessionLocal()
    try:
        latest_run = verify_db.query(ScanRun).order_by(ScanRun.id.desc()).first()
        assert latest_run.top_pairs_count == 2
        assert latest_run.settings_snapshot["pair_selection_mode"] == "CUSTOM"
        assert latest_run.settings_snapshot["selected_pairs"] == ["ARB_USDT", "SUI_USDT"]
    finally:
        verify_db.close()


@pytest.mark.asyncio
async def test_pipeline_custom_mode_skips_invalid_pairs_and_records_warning_and_timings(db_session, monkeypatch):
    db, TestingSessionLocal, _ = db_session
    key_row = db.query(AppSetting).filter(AppSetting.key == "commandcode_api_key").first()
    key_row.value = "test-cmd-key"
    db.add(AppSetting(key="pair_selection_mode", value="CUSTOM"))
    db.add(AppSetting(key="selected_pairs", value="ARB_USDT, DEAD_USDT"))
    db.commit()

    from app.core import pipeline as pipeline_mod

    monkeypatch.setattr(pipeline_mod, "SessionLocal", TestingSessionLocal)

    async def fake_contracts(self):
        return [{"symbol": "ARB_USDT", "quoteCoin": "USDT", "state": 0}]

    async def fake_tickers(self):
        return {"ARB_USDT": {"symbol": "ARB_USDT", "lastPrice": 1.1, "amount24": 100_000, "holdVol": 1000}}

    async def fake_get_kline(self, symbol, interval="Min15", limit=250, start_ts=None, end_ts=None):
        return _make_sample_candles(80)

    analyzed: list[str] = []

    async def fake_analyze(snapshot, strategy, llm_config, client=None, timeout_seconds=None):
        analyzed.append(snapshot["symbol"])
        return (
            AISetupDecision(
                symbol=snapshot["symbol"],
                strategy_used=strategy,
                decision="NO_TRADE",
                market_regime="RANGING",
                entry_type="NONE",
                confidence=40,
                invalidation_reason="N/A",
                rationale="x",
            ),
            {"mock": True},
        )

    monkeypatch.setattr(pipeline_mod.MexcPublicClient, "get_active_usdt_contracts", fake_contracts)
    monkeypatch.setattr(pipeline_mod.MexcPublicClient, "get_all_tickers", fake_tickers)
    monkeypatch.setattr(pipeline_mod.MexcPublicClient, "get_kline", fake_get_kline)
    monkeypatch.setattr(pipeline_mod, "analyze_market_snapshot", fake_analyze)

    summary = await ScanPipeline().run_once(strategies=["TREND_PULLBACK"])
    assert summary["status"] == "COMPLETED"
    assert set(analyzed) == {"ARB_USDT"}
    assert summary["invalid_custom_pairs"] == ["DEAD_USDT"]
    assert "DEAD_USDT" in (summary["warning"] or "")
    for key in ("fetch_pairs_s", "btc_context_s", "fetch_prefilter_s", "ai_tail_s", "stream_total_s", "save_s", "total_s"):
        assert key in summary["stage_timings"]

    verify_db = TestingSessionLocal()
    try:
        run = verify_db.query(ScanRun).order_by(ScanRun.id.desc()).first()
        assert run.settings_snapshot["stage_timings"]["total_s"] >= 0
        assert run.settings_snapshot["invalid_custom_pairs"][0]["symbol"] == "DEAD_USDT"
    finally:
        verify_db.close()


@pytest.mark.asyncio
async def test_pipeline_custom_mode_fails_when_all_pairs_invalid(db_session, monkeypatch):
    db, TestingSessionLocal, _ = db_session
    key_row = db.query(AppSetting).filter(AppSetting.key == "commandcode_api_key").first()
    key_row.value = "test-cmd-key"
    db.add(AppSetting(key="pair_selection_mode", value="CUSTOM"))
    db.add(AppSetting(key="selected_pairs", value="DEAD_USDT"))
    db.commit()

    from app.core import pipeline as pipeline_mod

    monkeypatch.setattr(pipeline_mod, "SessionLocal", TestingSessionLocal)

    async def fake_contracts(self):
        return []

    async def fake_tickers(self):
        return {}

    monkeypatch.setattr(pipeline_mod.MexcPublicClient, "get_active_usdt_contracts", fake_contracts)
    monkeypatch.setattr(pipeline_mod.MexcPublicClient, "get_all_tickers", fake_tickers)

    summary = await ScanPipeline().run_once(strategies=["TREND_PULLBACK"])
    assert summary["status"] == "FAILED"
    assert "DEAD_USDT" in summary["error"]
