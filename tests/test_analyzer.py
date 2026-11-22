"""Unit tests for AI Decision Engine & MySQL-backed LLM config resolution."""

import json

import httpx
import pytest

from app.ai import analyzer as analyzer_mod
from app.ai.analyzer import analyze_market_snapshot, resolve_active_llm_config
from app.models import AIModel, AppSetting


def test_resolve_active_llm_config_switches_between_providers(db_session):
    db, _, _ = db_session

    # Set keys for both providers
    for k, v in [
        ("commandcode_api_key", "cmd-secret-123"),
        ("openrouter_api_key", "or-secret-456"),
        ("llm_active_provider", "openrouter"),
    ]:
        row = db.query(AppSetting).filter(AppSetting.key == k).first()
        row.value = v

    or_model = db.query(AIModel).filter(AIModel.provider == "openrouter").first()
    db.query(AIModel).update({AIModel.is_active: False})
    or_model.is_active = True
    db.commit()

    cfg = resolve_active_llm_config(db)
    assert cfg["provider"] == "openrouter"
    assert cfg["api_key"] == "or-secret-456"
    assert cfg["model_id"] == or_model.model_id
    assert "openrouter.ai" in cfg["base_url"]


@pytest.mark.asyncio
async def test_analyze_market_snapshot_parses_json_with_fallback():
    calls = []
    max_tokens_seen = []

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        calls.append(body.get("response_format"))
        max_tokens_seen.append(body.get("max_tokens"))
        # Simulate provider rejecting strict json_schema on 1st call, accepting json_object on 2nd
        if body.get("response_format", {}).get("type") == "json_schema":
            return httpx.Response(400, json={"error": "json_schema unsupported"})
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "symbol": "BTC_USDT",
                                    "strategy_used": "BREAKOUT_MOMENTUM",
                                    "decision": "LONG",
                                    "market_regime": "TRENDING_UP",
                                    "entry_type": "MARKET",
                                    "entry_price": 95000.0,
                                    "stop_loss": 94000.0,
                                    "take_profit": 97500.0,
                                    "risk_reward_ratio": 2.5,
                                    "confidence": 84,
                                    "invalidation_reason": "Close back inside 94k range",
                                    "rationale": "Clean breakout with 1.9x volume",
                                }
                            )
                        }
                    }
                ]
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        decision, _ = await analyze_market_snapshot(
            snapshot={"symbol": "BTC_USDT", "ltf_15m": {"close": 95000}},
            strategy="BREAKOUT_MOMENTUM",
            llm_config={
                "provider": "commandcode",
                "base_url": "https://api.commandcode.ai/provider/v1/chat/completions",
                "api_key": "test-key",
                "model_id": "google/gemini-2.5-flash",
            },
            client=client,
        )

    assert len(calls) == 2
    assert all(mt == 1500 for mt in max_tokens_seen)
    assert decision.decision == "LONG"
    assert decision.confidence == 84
    assert decision.take_profit == 97500.0

    # Custom max_tokens override (e.g. from app_settings.llm_max_tokens)
    max_tokens_seen.clear()
    async with httpx.AsyncClient(transport=transport) as client:
        await analyze_market_snapshot(
            snapshot={"symbol": "BTC_USDT", "ltf_15m": {"close": 95000}},
            strategy="BREAKOUT_MOMENTUM",
            llm_config={
                "provider": "commandcode",
                "base_url": "https://api.commandcode.ai/provider/v1/chat/completions",
                "api_key": "test-key",
                "model_id": "google/gemini-2.5-flash",
            },
            client=client,
            max_tokens=2048,
        )
    assert all(mt == 2048 for mt in max_tokens_seen)


@pytest.mark.asyncio
async def test_llm_connection_handles_null_content_from_reasoning_model(monkeypatch):
    class FakeResp:
        status_code = 200

        def json(self):
            return {"choices": [{"message": {"role": "assistant", "content": None, "reasoning": "thinking..."}}]}

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, *args, **kwargs):
            return FakeResp()

    monkeypatch.setattr(analyzer_mod.httpx, "AsyncClient", FakeAsyncClient)
    res = await analyzer_mod.test_llm_connection(
        provider="openrouter",
        base_url="https://openrouter.ai/api/v1/chat/completions",
        api_key="sk-or-test",
        model_id="openrouter/free",
    )
    assert res["success"] is True
    assert "Koneksi berhasil" in res["message"]
