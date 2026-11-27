"""Tests for scan-performance/reliability changes: MEXC retry semantics, incremental persistence, shared LLM client."""

import asyncio

import httpx
import pytest

from app.core import pipeline as pipeline_mod
from app.core.pipeline import ScanPipeline
from app.models import AppSetting, ScanEvaluation, ScanRun, TradeSetup
from app.schemas import AISetupDecision
from app.scanner.mexc_public import MexcPublicClient


def _candles(n: int = 80, base: float = 100.0) -> list[dict]:
    out, price = [], base
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


# ---------- MexcPublicClient._get_json retry semantics ----------


class _FakeResp:
    def __init__(self, status: int, payload=None):
        self.status_code = status
        self._payload = payload if payload is not None else {"success": True, "data": []}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("err", request=None, response=None)  # type: ignore[arg-type]

    def json(self):
        return self._payload


class _ScriptedClient:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0

    async def get(self, path, params=None):
        self.calls += 1
        return self._responses.pop(0)

    async def aclose(self):
        pass


@pytest.mark.asyncio
async def test_get_json_raises_when_all_attempts_return_429(monkeypatch):
    sleeps: list[float] = []

    async def fake_sleep(s):
        sleeps.append(s)

    monkeypatch.setattr("app.scanner.mexc_public.asyncio.sleep", fake_sleep)
    client = MexcPublicClient(base_url="http://x", max_concurrency=2)
    client._client = _ScriptedClient([_FakeResp(429)] * 3)

    with pytest.raises(RuntimeError, match="429"):
        await client._get_json("/api/v1/x", retries=3)
    # Backoff sleeps only between attempts (not after the final failure)
    assert len(sleeps) == 2


@pytest.mark.asyncio
async def test_get_json_succeeds_after_transient_5xx(monkeypatch):
    async def fake_sleep(s):
        return None

    monkeypatch.setattr("app.scanner.mexc_public.asyncio.sleep", fake_sleep)
    client = MexcPublicClient(base_url="http://x", max_concurrency=2)
    client._client = _ScriptedClient([_FakeResp(503), _FakeResp(200, {"success": True, "data": [1, 2]})])

    assert await client._get_json("/api/v1/x", retries=3) == [1, 2]


@pytest.mark.asyncio
async def test_get_json_backoff_does_not_hold_semaphore(monkeypatch):
    """While one request is backing off, another request must be able to acquire the semaphore."""
    client = MexcPublicClient(base_url="http://x", max_concurrency=1)
    held_during_sleep: list[bool] = []

    async def fake_sleep(s):
        # During backoff the single semaphore slot must be free.
        held_during_sleep.append(client.semaphore.locked())

    monkeypatch.setattr("app.scanner.mexc_public.asyncio.sleep", fake_sleep)
    client._client = _ScriptedClient([_FakeResp(429), _FakeResp(200, {"success": True, "data": []})])

    await client._get_json("/api/v1/x", retries=2)
    assert held_during_sleep == [False]


@pytest.mark.asyncio
async def test_get_json_retries_on_mexc_code_510_rate_limit(monkeypatch):
    sleeps: list[float] = []

    async def fake_sleep(s):
        sleeps.append(s)

    monkeypatch.setattr("app.scanner.mexc_public.asyncio.sleep", fake_sleep)
    rate_limit_payload = {
        "success": False,
        "code": 510,
        "message": "Endpoint rate limit exceeded. Resource: /api/v1/contract/kline/*; scope: IP",
        "_extend": {"rateLimitType": "ENDPOINT_RATE_LIMIT", "resource": "/api/v1/contract/kline/*", "scope": "IP"},
    }
    client = MexcPublicClient(base_url="http://x", max_concurrency=2)
    client._client = _ScriptedClient(
        [_FakeResp(200, rate_limit_payload), _FakeResp(200, {"success": True, "data": [42]})]
    )

    assert await client._get_json("/api/v1/contract/kline/GALA_USDT", retries=3) == [42]
    assert len(sleeps) == 1


@pytest.mark.asyncio
async def test_get_json_does_not_retry_non_rate_limit_api_error(monkeypatch):
    sleeps: list[float] = []

    async def fake_sleep(s):
        sleeps.append(s)

    monkeypatch.setattr("app.scanner.mexc_public.asyncio.sleep", fake_sleep)
    client = MexcPublicClient(base_url="http://x", max_concurrency=2)
    client._client = _ScriptedClient([_FakeResp(200, {"success": False, "code": 1001, "message": "Invalid symbol"})])

    with pytest.raises(RuntimeError, match="MEXC API error"):
        await client._get_json("/api/v1/contract/kline/BAD_USDT", retries=3)
    assert sleeps == []


# ---------- Pipeline: incremental persistence & partial AI failures ----------


@pytest.mark.asyncio
async def test_pipeline_keeps_good_setups_when_other_ai_calls_fail(db_session, monkeypatch):
    db, TestingSessionLocal, _ = db_session
    key_row = db.query(AppSetting).filter(AppSetting.key == "commandcode_api_key").first()
    key_row.value = "test-cmd-key"
    db.commit()

    monkeypatch.setattr(pipeline_mod, "SessionLocal", TestingSessionLocal)

    async def fake_get_top_pairs(self, top_n=None, min_quote_volume=None):
        pair = lambda s: {  # noqa: E731
            "symbol": s,
            "contract": {"symbol": s},
            # lastPrice aligned with synthetic candles (close=132, ATR14=1.4) so the validator accepts the setup
            "ticker": {"lastPrice": 132.0, "amount24": 50_000_000},
            "amount24": 50_000_000,
        }
        return 2, [pair("AAA_USDT"), pair("BBB_USDT")]

    async def fake_get_kline(self, symbol, interval="Min15", limit=250, start_ts=None, end_ts=None):
        return _candles(80)

    async def mixed_ai(snapshot, strategy, llm_config, client=None, timeout_seconds=None):
        if snapshot["symbol"] == "AAA_USDT":
            return (
                AISetupDecision(
                    symbol="AAA_USDT",
                    strategy_used=strategy,
                    decision="LONG",
                    market_regime="TRENDING_UP",
                    entry_type="LIMIT",
                    entry_price=131.5,
                    stop_loss=129.5,
                    take_profit=137.5,
                    risk_reward_ratio=3.0,
                    confidence=86,
                    invalidation_reason="Break 129.5",
                    rationale="test",
                ),
                {},
            )
        raise RuntimeError("upstream AI boom")

    monkeypatch.setattr(pipeline_mod.MexcPublicClient, "get_top_pairs", fake_get_top_pairs)
    monkeypatch.setattr(pipeline_mod.MexcPublicClient, "get_kline", fake_get_kline)
    monkeypatch.setattr(pipeline_mod, "analyze_market_snapshot", mixed_ai)

    summary = await ScanPipeline().run_once(strategies=["TREND_PULLBACK"], top_n=2)

    assert summary["status"] == "COMPLETED"
    assert summary["ai_errors"] == 1
    assert summary["setups_created"] == 1

    verify = TestingSessionLocal()
    try:
        assert verify.query(TradeSetup).count() == 1
        errs = verify.query(ScanEvaluation).filter(ScanEvaluation.raw_decision == "ERROR").all()
        assert len(errs) == 1 and errs[0].symbol == "BBB_USDT"
    finally:
        verify.close()


@pytest.mark.asyncio
async def test_pipeline_passes_shared_llm_client_to_ai(db_session, monkeypatch):
    db, TestingSessionLocal, _ = db_session
    key_row = db.query(AppSetting).filter(AppSetting.key == "commandcode_api_key").first()
    key_row.value = "test-cmd-key"
    db.commit()

    monkeypatch.setattr(pipeline_mod, "SessionLocal", TestingSessionLocal)

    async def fake_get_top_pairs(self, top_n=None, min_quote_volume=None):
        return 1, [
            {"symbol": "AAA_USDT", "contract": {"symbol": "AAA_USDT"}, "ticker": {"lastPrice": 1.0, "amount24": 1000}, "amount24": 1000}
        ]

    async def fake_get_kline(self, symbol, interval="Min15", limit=250, start_ts=None, end_ts=None):
        return _candles(80)

    seen_clients: list[object] = []

    async def capture_ai(snapshot, strategy, llm_config, client=None, timeout_seconds=None):
        seen_clients.append(client)
        return (
            AISetupDecision(
                symbol=snapshot["symbol"],
                strategy_used=strategy,
                decision="NO_TRADE",
                market_regime="RANGING",
                entry_type="NONE",
                confidence=10,
                invalidation_reason="n/a",
                rationale="n/a",
            ),
            {},
        )

    monkeypatch.setattr(pipeline_mod.MexcPublicClient, "get_top_pairs", fake_get_top_pairs)
    monkeypatch.setattr(pipeline_mod.MexcPublicClient, "get_kline", fake_get_kline)
    monkeypatch.setattr(pipeline_mod, "analyze_market_snapshot", capture_ai)

    summary = await ScanPipeline().run_once(strategies=["TREND_PULLBACK", "MEAN_REVERSION_SCALP"], top_n=1)
    assert summary["status"] == "COMPLETED"
    assert len(seen_clients) >= 1
    # All AI calls in one scan share the same httpx.AsyncClient instance
    assert all(c is seen_clients[0] for c in seen_clients)
    assert isinstance(seen_clients[0], httpx.AsyncClient)


@pytest.mark.asyncio
async def test_pipeline_request_stop_cancels_active_scan(db_session, monkeypatch):
    db, TestingSessionLocal, _ = db_session
    key_row = db.query(AppSetting).filter(AppSetting.key == "commandcode_api_key").first()
    key_row.value = "test-cmd-key"
    db.commit()

    monkeypatch.setattr(pipeline_mod, "SessionLocal", TestingSessionLocal)
    pipeline = ScanPipeline()

    async def slow_get_top_pairs(self, **kwargs):
        await asyncio.sleep(5)
        return 0, []

    monkeypatch.setattr(pipeline_mod.MexcPublicClient, "get_top_pairs", slow_get_top_pairs)

    task = asyncio.create_task(pipeline.run_once(strategies=["TREND_PULLBACK"], top_n=1))
    # Wait until pipeline marks itself as running
    for _ in range(50):
        if pipeline.is_running and pipeline.current_run_id is not None:
            break
        await asyncio.sleep(0.01)

    assert pipeline.is_running is True
    assert pipeline.request_stop() is True

    summary = await task
    assert summary["status"] == "CANCELLED"
    assert pipeline.is_running is False
    run_row = db.get(ScanRun, summary["scan_run_id"])
    db.refresh(run_row)
    assert run_row.status == "CANCELLED"
    assert run_row.finished_at is not None


def test_stop_endpoint_cleans_up_orphaned_running_scan(api_client, db_session):
    db, _, _ = db_session
    stale_run = ScanRun(strategy="TREND_PULLBACK", status="RUNNING")
    db.add(stale_run)
    db.commit()
    db.refresh(stale_run)

    resp = api_client.post(f"/api/scanner/stop?run_id={stale_run.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["stopped"] is True
    assert body["mode"] == "db_cleanup"
    assert stale_run.id in body["updated_ids"]

    db.expire_all()
    refreshed = db.get(ScanRun, stale_run.id)
    assert refreshed.status == "CANCELLED"
    assert refreshed.finished_at is not None
