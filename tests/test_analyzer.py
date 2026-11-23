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
    user_msgs_seen = []

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        calls.append(body.get("response_format"))
        max_tokens_seen.append(body.get("max_tokens"))
        user_msgs_seen.append(body["messages"][1]["content"])
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

    # Custom max_tokens & min_confidence (min_confidence must NOT leak into prompt)
    max_tokens_seen.clear()
    user_msgs_seen.clear()
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
            min_confidence=88,
        )
    assert all(mt == 2048 for mt in max_tokens_seen)
    assert not any("88%" in msg for msg in user_msgs_seen)


def test_strict_json_schema_has_all_required_and_reasoning_first():
    rf = analyzer_mod._build_response_format_schema()
    assert rf["type"] == "json_schema"
    assert rf["json_schema"]["strict"] is True
    schema = rf["json_schema"]["schema"]
    assert schema["additionalProperties"] is False

    props = schema["properties"]
    keys = list(props.keys())
    assert set(schema["required"]) == set(keys)
    # Reasoning & checklist must precede market_regime and decision
    assert keys.index("htf_analysis") < keys.index("decision")
    assert keys.index("ltf_trigger_analysis") < keys.index("decision")
    assert keys.index("checklist") < keys.index("decision")

    # No default keys anywhere in strict schema, and no unsupported minLength/maxLength on strategy_used
    assert "minLength" not in props["strategy_used"]
    assert "maxLength" not in props["strategy_used"]
    for prop in props.values():
        assert "default" not in prop

    checklist_schema = props["checklist"]
    assert checklist_schema["additionalProperties"] is False
    assert set(checklist_schema["required"]) == set(checklist_schema["properties"].keys())


@pytest.mark.asyncio
async def test_analyze_market_snapshot_retries_once_on_invalid_json():
    attempts = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(200, json={"choices": [{"message": {"content": "{not-valid-json"}}]})
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "symbol": "SOL_USDT",
                                    "strategy_used": "TREND_PULLBACK",
                                    "htf_analysis": "Uptrend",
                                    "ltf_trigger_analysis": "Bounce at EMA21",
                                    "checklist": {
                                        "htf_trend_ok": True,
                                        "pullback_or_level_ok": True,
                                        "trigger_candle_ok": True,
                                        "volume_ok": True,
                                        "momentum_ok": True,
                                        "rr_ok": True,
                                    },
                                    "market_regime": "TRENDING_UP",
                                    "decision": "LONG",
                                    "entry_type": "LIMIT",
                                    "entry_price": 150.0,
                                    "stop_loss": 145.0,
                                    "take_profit": 160.0,
                                    "risk_reward_ratio": 2.0,
                                    "confidence": 82,
                                    "invalidation_reason": "Below 145",
                                    "rationale": "Clean pullback",
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
            snapshot={"symbol": "SOL_USDT", "ltf_15m": {"close": 151.0}},
            strategy="TREND_PULLBACK",
            llm_config={
                "provider": "openrouter",
                "base_url": "https://openrouter.ai/api/v1/chat/completions",
                "api_key": "test-key",
                "model_id": "google/gemini-2.5-flash",
            },
            client=client,
        )
    assert attempts == 2
    assert decision.decision == "LONG"
    assert decision.checklist.htf_trend_ok is True


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


@pytest.mark.asyncio
async def test_analyze_market_snapshot_retries_on_empty_content_from_thinking_model():
    seen_requests = []

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        seen_requests.append(body)
        if len(seen_requests) == 1:
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "finish_reason": "length",
                            "message": {
                                "role": "assistant",
                                "content": None,
                                "reasoning": "Analyzing HTF trend and pullback levels...",
                            },
                        }
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(
                                {
                                    "symbol": "PIEVERSE_USDT",
                                    "strategy_used": "TREND_PULLBACK",
                                    "htf_analysis": "Uptrend intact",
                                    "ltf_trigger_analysis": "Weak volume",
                                    "checklist": {
                                        "htf_trend_ok": True,
                                        "pullback_or_level_ok": False,
                                        "trigger_candle_ok": False,
                                        "volume_ok": False,
                                        "momentum_ok": True,
                                        "rr_ok": False,
                                    },
                                    "market_regime": "TRENDING_UP",
                                    "decision": "NO_TRADE",
                                    "entry_type": "NONE",
                                    "entry_price": None,
                                    "stop_loss": None,
                                    "take_profit": None,
                                    "risk_reward_ratio": None,
                                    "confidence": 55,
                                    "invalidation_reason": "No trigger",
                                    "rationale": "Wait for pullback",
                                }
                            )
                        },
                    }
                ]
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        decision, _ = await analyze_market_snapshot(
            snapshot={"symbol": "PIEVERSE_USDT", "ltf_15m": {"close": 0.25}},
            strategy="TREND_PULLBACK",
            llm_config={
                "provider": "custom",
                "base_url": "https://api.nano-gpt.com/api/v1/chat/completions",
                "api_key": "test-key",
                "model_id": "deepseek/deepseek-v4.1-flash-1017:thinking",
            },
            client=client,
            max_tokens=1500,
        )

    assert len(seen_requests) == 2
    assert seen_requests[0]["max_tokens"] == 1500
    assert "response_format" in seen_requests[0]
    assert seen_requests[1]["max_tokens"] == 4096
    assert "response_format" not in seen_requests[1]
    assert decision.symbol == "PIEVERSE_USDT"
    assert decision.decision == "NO_TRADE"


@pytest.mark.asyncio
async def test_analyze_market_snapshot_extracts_json_from_reasoning_when_content_empty():
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        payload = json.dumps(
            {
                "symbol": "BTC_USDT",
                "strategy_used": "TREND_PULLBACK",
                "htf_analysis": "Bullish",
                "ltf_trigger_analysis": "Reclaim EMA21",
                "checklist": {
                    "htf_trend_ok": True,
                    "pullback_or_level_ok": True,
                    "trigger_candle_ok": True,
                    "volume_ok": True,
                    "momentum_ok": True,
                    "rr_ok": True,
                },
                "market_regime": "TRENDING_UP",
                "decision": "LONG",
                "entry_type": "LIMIT",
                "entry_price": 90000.0,
                "stop_loss": 89000.0,
                "take_profit": 92000.0,
                "risk_reward_ratio": 2.0,
                "confidence": 81,
                "invalidation_reason": "Below 89k",
                "rationale": "Valid setup",
            }
        )
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": "",
                            "reasoning": f"Thinking complete.\n```json\n{payload}\n```",
                        },
                    }
                ]
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        decision, _ = await analyze_market_snapshot(
            snapshot={"symbol": "BTC_USDT", "ltf_15m": {"close": 90100.0}},
            strategy="TREND_PULLBACK",
            llm_config={
                "provider": "custom",
                "base_url": "https://api.nano-gpt.com/api/v1/chat/completions",
                "api_key": "test-key",
                "model_id": "deepseek/deepseek-v4.1-flash-1017:thinking",
            },
            client=client,
        )

    assert calls == 1
    assert decision.decision == "LONG"
    assert decision.confidence == 81


@pytest.mark.asyncio
async def test_analyze_market_snapshot_raises_clear_error_when_empty_content_persists():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "length",
                        "message": {"content": None, "reasoning": "Still thinking..."},
                    }
                ]
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(RuntimeError, match="finish_reason=length"):
            await analyze_market_snapshot(
                snapshot={"symbol": "PIEVERSE_USDT", "ltf_15m": {"close": 0.25}},
                strategy="TREND_PULLBACK",
                llm_config={
                    "provider": "custom",
                    "base_url": "https://api.nano-gpt.com/api/v1/chat/completions",
                    "api_key": "test-key",
                    "model_id": "deepseek/deepseek-v4.1-flash-1017:thinking",
                },
                client=client,
            )
