"""AI decision engine with MySQL-backed provider/model resolution and strict Pydantic parsing."""

import json
import logging
import re
import time
from typing import Any, Optional

import httpx
from sqlalchemy.orm import Session

from ..config import (
    DEFAULT_COMMANDCODE_BASE_URL,
    DEFAULT_OPENROUTER_BASE_URL,
    PROMPTS_DIR,
    STRATEGY_PROMPT_FILES,
    settings,
)
from ..models import AIModel, AppSetting, Strategy
from ..schemas import AISetupDecision

log = logging.getLogger(__name__)


def _get_setting_map(db: Session | None) -> dict[str, str]:
    """Fetch app_settings as a key->value dict."""
    if db is None:
        return {}
    rows = db.query(AppSetting).all()
    return {row.key: (row.value or "") for row in rows}


def resolve_active_llm_config(db: Session | None = None) -> dict[str, str]:
    """Resolve active LLM provider, base_url, api_key, and model_id from MySQL with .env fallback."""
    setting_map = _get_setting_map(db)

    active_model_obj: AIModel | None = None
    if db is not None:
        active_model_obj = db.query(AIModel).filter(AIModel.is_active.is_(True)).first()
        if not active_model_obj:
            active_model_obj = db.query(AIModel).order_by(AIModel.id.asc()).first()

    provider = (
        setting_map.get("llm_active_provider")
        or (active_model_obj.provider if active_model_obj else None)
        or settings.llm_provider
        or "commandcode"
    ).strip().lower()
    if provider not in {"commandcode", "openrouter", "custom"}:
        provider = "commandcode"

    model_id = (
        (active_model_obj.model_id if active_model_obj else None)
        or setting_map.get("active_model_id")
        or settings.llm_model
        or "google/gemini-2.5-flash"
    ).strip()
    model_name = active_model_obj.name if active_model_obj else model_id

    if provider == "openrouter":
        base_url = (
            setting_map.get("openrouter_base_url")
            or settings.openrouter_base_url
            or DEFAULT_OPENROUTER_BASE_URL
        ).strip()
        api_key = (
            setting_map.get("openrouter_api_key")
            or settings.openrouter_api_key
            or (settings.llm_api_key if settings.llm_provider == "openrouter" else "")
        ).strip()
    elif provider == "custom":
        base_url = (
            setting_map.get("custom_llm_base_url")
            or settings.custom_llm_base_url
            or settings.llm_base_url
        ).strip()
        api_key = (
            setting_map.get("custom_llm_api_key")
            or settings.custom_llm_api_key
            or settings.llm_api_key
        ).strip()
    else:
        base_url = (
            setting_map.get("commandcode_base_url")
            or settings.commandcode_base_url
            or DEFAULT_COMMANDCODE_BASE_URL
        ).strip()
        api_key = (
            setting_map.get("commandcode_api_key")
            or settings.commandcode_api_key
            or (settings.llm_api_key if settings.llm_provider == "commandcode" else "")
        ).strip()

    # Final fallback if provider-specific key empty but generic LLM_API_KEY was provided
    if not api_key and settings.llm_api_key:
        api_key = settings.llm_api_key.strip()

    return {
        "provider": provider,
        "base_url": base_url,
        "api_key": api_key,
        "model_id": model_id,
        "model_name": model_name,
    }


def load_strategy_prompt(strategy: str, db: Session | None = None) -> str:
    """Load system prompt text from DB `strategies` table first, falling back to prompts/ file."""
    strat_key = strategy.strip().upper()
    if db is not None:
        row = db.query(Strategy).filter(Strategy.name == strat_key).first()
        if row and row.prompt_text and row.prompt_text.strip():
            return row.prompt_text

    filename = STRATEGY_PROMPT_FILES.get(strat_key)
    if not filename:
        raise ValueError(f"Unsupported strategy: {strategy}")
    path = PROMPTS_DIR / filename
    return path.read_text(encoding="utf-8")


def load_strategy_prompts_map(db: Session | None, strategies: list[str]) -> dict[str, str]:
    """Batch load strategy prompt texts prior to concurrent async LLM calls."""
    prompts: dict[str, str] = {}
    for strat in strategies:
        key = strat.strip().upper()
        prompts[key] = load_strategy_prompt(key, db=db)
    return prompts


def _build_response_format_schema() -> dict[str, Any]:
    """Build OpenAI-compatible json_schema response_format from AISetupDecision."""
    schema = AISetupDecision.model_json_schema()
    schema["additionalProperties"] = False
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "mexc_trade_setup_decision",
            "strict": True,
            "schema": schema,
        },
    }


def _extract_json_content(raw_content: str) -> str:
    """Strip markdown code fences if a provider wrapped JSON in ```json ... ```."""
    cleaned = raw_content.strip()
    fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", cleaned, re.IGNORECASE)
    if fence_match:
        return fence_match.group(1).strip()
    return cleaned


def _build_headers(provider: str, api_key: str) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    if provider == "openrouter":
        headers["HTTP-Referer"] = "http://localhost:8001"
        headers["X-Title"] = "MEXC AI Setup Scanner"
    return headers


async def analyze_market_snapshot(
    snapshot: dict[str, Any],
    strategy: str,
    llm_config: dict[str, str],
    client: Optional[httpx.AsyncClient] = None,
    timeout_seconds: Optional[int] = None,
    system_prompt: Optional[str] = None,
    db: Optional[Session] = None,
) -> tuple[AISetupDecision, dict[str, Any]]:
    """Send structured snapshot to configured LLM and validate response into AISetupDecision."""
    api_key = llm_config.get("api_key", "").strip()
    base_url = llm_config.get("base_url", "").strip()
    model_id = llm_config.get("model_id", "").strip()
    provider = llm_config.get("provider", "commandcode").strip()

    if not api_key:
        raise RuntimeError(f"API Key untuk provider '{provider}' belum diisi.")
    if not base_url:
        raise RuntimeError(f"Base URL untuk provider '{provider}' belum diisi.")

    resolved_prompt = system_prompt if system_prompt is not None else load_strategy_prompt(strategy, db=db)
    schema_json_str = json.dumps(AISetupDecision.model_json_schema(), ensure_ascii=False)
    user_message = (
        f"Evaluasi snapshot market MEXC Futures berikut untuk strategi {strategy}.\n"
        f"Kembalikan HANYA JSON valid sesuai schema ini:\n{schema_json_str}\n\n"
        f"MARKET SNAPSHOT:\n{json.dumps(snapshot, ensure_ascii=False)}"
    )

    headers = _build_headers(provider, api_key)
    base_payload: dict[str, Any] = {
        "model": model_id,
        "temperature": 0.1,
        "messages": [
            {"role": "system", "content": resolved_prompt},
            {"role": "user", "content": user_message},
        ],
    }

    own_client = False
    if client is None:
        eff_timeout = timeout_seconds or settings.llm_timeout_seconds
        client = httpx.AsyncClient(timeout=httpx.Timeout(eff_timeout))
        own_client = True

    try:
        payload_schema = {**base_payload, "response_format": _build_response_format_schema()}
        resp = await client.post(base_url, headers=headers, json=payload_schema)

        # Graceful fallback if provider rejects strict json_schema format
        if resp.status_code in (400, 422):
            log.debug(
                "Provider %s returned %s for json_schema; falling back to json_object",
                provider,
                resp.status_code,
            )
            payload_obj = {**base_payload, "response_format": {"type": "json_object"}}
            resp = await client.post(base_url, headers=headers, json=payload_obj)
            if resp.status_code in (400, 422):
                # Second fallback: plain chat completions without response_format
                resp = await client.post(base_url, headers=headers, json=base_payload)

        if resp.is_error:
            raise RuntimeError(f"HTTP {resp.status_code} ({model_id}): {resp.text[:300]}")
        raw_response = resp.json()
        if isinstance(raw_response, dict) and raw_response.get("error") and not raw_response.get("choices"):
            raise RuntimeError(f"LLM API error: {raw_response['error']}")
        msg = (raw_response.get("choices") or [{}])[0].get("message") or {}
        content = msg.get("content") or ""
        if not str(content).strip():
            raise RuntimeError(
                f"Model '{model_id}' mengembalikan content kosong/null. Coba pilih model lain yang mendukung output JSON."
            )
        json_text = _extract_json_content(str(content))
        decision = AISetupDecision.model_validate_json(json_text)
        # Ensure symbol and strategy_used are normalized cleanly
        decision.symbol = snapshot["symbol"]
        decision.strategy_used = strategy.strip().upper()
        return decision, raw_response
    finally:
        if own_client:
            await client.aclose()


async def test_llm_connection(
    provider: str,
    base_url: str,
    api_key: str,
    model_id: str,
) -> dict[str, Any]:
    """Verify connectivity and measure latency to OpenRouter / Command Code AI / Custom LLM."""
    if not api_key or not api_key.strip():
        return {
            "success": False,
            "message": f"API Key untuk provider '{provider}' masih kosong.",
            "provider": provider,
            "model_id": model_id,
            "latency_ms": None,
        }
    if not base_url or not base_url.strip():
        return {
            "success": False,
            "message": f"Base URL untuk provider '{provider}' tidak boleh kosong.",
            "provider": provider,
            "model_id": model_id,
            "latency_ms": None,
        }

    headers = _build_headers(provider, api_key.strip())
    payload = {
        "model": model_id,
        "messages": [{"role": "user", "content": "Reply with one word: OK"}],
        "max_tokens": 64,
        "temperature": 0,
    }

    start = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(20.0)) as client:
            resp = await client.post(base_url.strip(), headers=headers, json=payload)
            latency_ms = int((time.perf_counter() - start) * 1000)

            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, dict) and data.get("error") and not data.get("choices"):
                    return {
                        "success": False,
                        "message": f"Error dari {provider}: {data['error']}",
                        "provider": provider,
                        "model_id": model_id,
                        "latency_ms": latency_ms,
                    }
                msg = (data.get("choices") or [{}])[0].get("message") or {}
                raw_reply = msg.get("content")
                if raw_reply is None:
                    raw_reply = msg.get("reasoning") or ""
                reply = str(raw_reply).strip()
                return {
                    "success": True,
                    "message": f"Koneksi berhasil ke {provider} ({model_id}) dalam {latency_ms} ms: '{reply or 'OK'}'",
                    "provider": provider,
                    "model_id": model_id,
                    "latency_ms": latency_ms,
                }

            err_snippet = resp.text[:300]
            return {
                "success": False,
                "message": f"HTTP {resp.status_code} dari {provider}: {err_snippet}",
                "provider": provider,
                "model_id": model_id,
                "latency_ms": latency_ms,
            }
    except Exception as exc:
        return {
            "success": False,
            "message": f"Gagal menghubungi {provider}: {exc}",
            "provider": provider,
            "model_id": model_id,
            "latency_ms": None,
        }
