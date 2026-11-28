"""AI decision engine with MySQL-backed provider/model resolution and strict Pydantic parsing."""

import asyncio
import json
import logging
import re
import random
import time
from typing import Any, Optional

import httpx
from pydantic import ValidationError
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

ANALYZER_PROMPT_VERSION = "v2"


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


# Module-level caches: the decision schema is static, so build/serialize it once per process.
_CACHED_STRICT_SCHEMA: dict[str, Any] | None = None
_CACHED_RESPONSE_FORMAT: dict[str, Any] | None = None
_CACHED_SCHEMA_JSON: str | None = None


def _get_strict_schema() -> dict[str, Any]:
    global _CACHED_STRICT_SCHEMA
    if _CACHED_STRICT_SCHEMA is None:
        _CACHED_STRICT_SCHEMA = _build_strict_decision_json_schema()
    return _CACHED_STRICT_SCHEMA


def _get_schema_json_str() -> str:
    global _CACHED_SCHEMA_JSON
    if _CACHED_SCHEMA_JSON is None:
        _CACHED_SCHEMA_JSON = json.dumps(_get_strict_schema(), ensure_ascii=False)
    return _CACHED_SCHEMA_JSON


def _get_response_format() -> dict[str, Any]:
    global _CACHED_RESPONSE_FORMAT
    if _CACHED_RESPONSE_FORMAT is None:
        _CACHED_RESPONSE_FORMAT = {
            "type": "json_schema",
            "json_schema": {
                "name": "mexc_trade_setup_decision",
                "strict": True,
                "schema": _get_strict_schema(),
            },
        }
    return _CACHED_RESPONSE_FORMAT


def _build_strict_decision_json_schema() -> dict[str, Any]:
    """Build OpenAI-compatible strict JSON Schema with reasoning-first field order.

    Every property is listed in `required`, `additionalProperties` is false on all objects,
    and nullable fields use `["number", "null"]` without `default` so strict mode succeeds.
    """
    checklist_props = {
        "htf_trend_ok": {"type": "boolean"},
        "pullback_or_level_ok": {"type": "boolean"},
        "trigger_candle_ok": {"type": "boolean"},
        "volume_ok": {"type": "boolean"},
        "momentum_ok": {"type": "boolean"},
        "rr_ok": {"type": "boolean"},
    }
    properties: dict[str, Any] = {
        "symbol": {"type": "string"},
        "strategy_used": {"type": "string"},
        "htf_analysis": {"type": "string"},
        "ltf_trigger_analysis": {"type": "string"},
        "checklist": {
            "type": "object",
            "properties": checklist_props,
            "required": list(checklist_props.keys()),
            "additionalProperties": False,
        },
        "market_regime": {
            "type": "string",
            "enum": ["TRENDING_UP", "TRENDING_DOWN", "RANGING", "HIGH_VOLATILITY_CHOP"],
        },
        "decision": {
            "type": "string",
            "enum": ["LONG", "SHORT", "NO_TRADE"],
        },
        "entry_type": {
            "type": "string",
            "enum": ["MARKET", "LIMIT", "NONE"],
        },
        "entry_price": {"type": ["number", "null"]},
        "stop_loss": {"type": ["number", "null"]},
        "take_profit": {"type": ["number", "null"]},
        "risk_reward_ratio": {"type": ["number", "null"]},
        "confidence": {"type": "integer", "minimum": 0, "maximum": 100},
        "invalidation_reason": {"type": "string"},
        "rationale": {"type": "string"},
    }
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties.keys()),
        "additionalProperties": False,
    }


def _build_response_format_schema() -> dict[str, Any]:
    """Return OpenAI-compatible json_schema response_format (cached; schema is static)."""
    return _get_response_format()


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


def _extract_choice_fields(raw_response: dict[str, Any]) -> tuple[str, str, str]:
    """Extract (content, reasoning, finish_reason) from first chat completion choice."""
    choice = (raw_response.get("choices") or [{}])[0]
    msg = choice.get("message") or {}
    content = str(msg.get("content") or "").strip()
    reasoning = str(msg.get("reasoning") or msg.get("reasoning_content") or "").strip()
    finish_reason = str(choice.get("finish_reason") or "").strip().lower()
    return content, reasoning, finish_reason


async def analyze_market_snapshot(
    snapshot: dict[str, Any],
    strategy: str,
    llm_config: dict[str, str],
    client: Optional[httpx.AsyncClient] = None,
    timeout_seconds: Optional[int] = None,
    max_tokens: Optional[int] = None,
    min_confidence: Optional[int] = None,
    risk_profile: Optional[str] = None,
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
    schema_json_str = _get_schema_json_str()
    htf_iv = (snapshot.get("htf_1h") or {}).get("interval", "HTF")
    ltf_iv = (snapshot.get("ltf_15m") or {}).get("interval", "LTF")
    eff_min_conf = max(0, min(100, int(min_confidence if min_confidence is not None else settings.min_confidence)))
    eff_risk_profile = (risk_profile or "CONSERVATIVE").strip().upper()
    if eff_risk_profile == "MODERATE":
        confidence_instruction = (
            f"Mode Risiko Aktif: MODERATE (mengesampingkan batas ketat < 70 dan syarat minor pada aturan strategi). "
            f"Nilai confidence (0-100) berdasarkan kualitas konfluensi: 80-95 (A-Grade lengkap), "
            f"{eff_min_conf}-79 (B/C-Grade: struktur utama & arah jelas dengan R:R layak walau 1-2 konfluensi tambahan moderat/belum ekstrem -> "
            f"tetap keluarkan LONG/SHORT, utamakan LIMIT di level kunci jika belum terkonfirmasi penuh), "
            f"<{eff_min_conf} (lemah/berkonflik berat -> NO_TRADE)."
        )
    elif eff_risk_profile == "AGGRESSIVE":
        confidence_instruction = (
            f"Mode Risiko Aktif: AGGRESSIVE (mengesampingkan batas ketat < 70 dan syarat volume/konfluensi sekunder pada aturan strategi). "
            f"Nilai confidence (0-100) untuk setup taktis/early entry: 75-95 (A-Grade), "
            f"{eff_min_conf}-74 (B/C-Grade: ada edge arah, sweep, atau pullback S/R yang layak dengan R:R masuk akal meski konfluensi parsial seperti volume moderat atau HTF MIXED -> "
            f"tetap keluarkan LONG/SHORT dan jelaskan risikonya di rationale), "
            f"<{eff_min_conf} (sangat lemah/berkonflik ekstrem -> NO_TRADE)."
        )
    else:
        b_grade_range = f"{eff_min_conf}-79" if eff_min_conf < 80 else "80+"
        confidence_instruction = (
            f"Nilai confidence (0-100) murni berdasarkan kualitas konfluensi "
            f"(80-95: A-Grade lengkap, {b_grade_range}: B-Grade struktur utama & R:R terpenuhi, <{eff_min_conf}: lemah/berkonflik -> NO_TRADE)."
        )
    user_message = (
        f"Evaluasi snapshot market MEXC Futures berikut untuk strategi {strategy}.\n"
        f"Catatan Struktur Snapshot: key 'htf_1h' berisi ringkasan Higher Timeframe aktual ({htf_iv}) "
        f"dan key 'ltf_15m' berisi ringkasan Lower Timeframe aktual ({ltf_iv}); selalu rujuk field 'interval' aktual tersebut. "
        f"Indikator & recent_candles dihitung murni dari candle yang sudah close (jika ada forming_candle, itu hanya konteks berjalan). "
        f"Potensi squeeze/crowding dinilai dari funding_rate + open_interest_hold_vol (tanpa feed likuidasi terpisah).\n"
        f"Kamus Field Tambahan:\n"
        f"- swept_prior_low / swept_prior_high + prior_swing_low / prior_swing_high: flag sweep & reclaim yang sudah dihitung kode; pakai sebagai sumber utama deteksi sweep.\n"
        f"- dss_cross_up / dss_cross_down: cross DSS terhadap dss_signal yang sudah dihitung kode.\n"
        f"- structure_bias (HH_HL / LH_LL / MIXED_RANGE), ema21_slope_pct, ema50_slope_pct: arah struktur & kemiringan EMA.\n"
        f"- compact_candles_15: 15 candle closed terakhir format {{o,h,l,c,vr}} (vr = volume_ratio).\n"
        f"- pivot_highs_recent / pivot_lows_recent (bars_ago), support_is_fallback / resistance_is_fallback (true = fallback min/max, bukan pivot asli; jangan dijadikan level kuat).\n"
        f"- level_candidates: kandidat SL/TP beserta R:R dari harga pasar yang sudah dihitung kode; prioritaskan memilih level dari sini dan jangan menghitung ulang secara bebas.\n"
        f"- market_context.btc: bias BTC pada HTF/LTF yang sama; jika setup altcoin melawan bias BTC yang kuat, turunkan confidence.\n"
        f"- market_ticker.open_interest_usdt, oi_to_volume_ratio, funding_rate_pct, funding_extreme: normalisasi OI & status funding.\n"
        f"Instruksi Evaluasi Berurutan: Isi terlebih dahulu htf_analysis, ltf_trigger_analysis, dan checklist secara objektif "
        f"berdasarkan aturan strategi, baru kemudian tentukan market_regime, decision, level harga, dan confidence. "
        f"{confidence_instruction}\n"
        f"Kembalikan HANYA JSON valid sesuai schema ini:\n{schema_json_str}\n\n"
        f"MARKET SNAPSHOT:\n{json.dumps(snapshot, ensure_ascii=False)}"
    )

    eff_max_tokens = max(512, min(8192, int(max_tokens if max_tokens is not None else settings.llm_max_tokens)))
    headers = _build_headers(provider, api_key)
    base_payload: dict[str, Any] = {
        "model": model_id,
        "temperature": 0.1,
        "max_tokens": eff_max_tokens,
        "stream": False,
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
        async def _call_llm(
            messages_payload: list[dict[str, str]],
            max_tokens_override: Optional[int] = None,
            force_plain: bool = False,
            max_retries: int = 4,
        ) -> dict[str, Any]:
            req_base = {
                **base_payload,
                "messages": messages_payload,
                "max_tokens": max_tokens_override if max_tokens_override is not None else eff_max_tokens,
            }
            last_err_text = ""
            for attempt in range(max_retries):
                if force_plain:
                    resp = await client.post(base_url, headers=headers, json=req_base)
                else:
                    payload_schema = {**req_base, "response_format": _build_response_format_schema()}
                    resp = await client.post(base_url, headers=headers, json=payload_schema)

                    # Graceful fallback if provider rejects strict json_schema format
                    if resp.status_code in (400, 422):
                        log.warning(
                            "Provider %s (%s) returned %s for strict json_schema; falling back to json_object",
                            provider,
                            model_id,
                            resp.status_code,
                        )
                        payload_obj = {**req_base, "response_format": {"type": "json_object"}}
                        resp = await client.post(base_url, headers=headers, json=payload_obj)
                        if resp.status_code in (400, 422):
                            log.warning(
                                "Provider %s (%s) returned %s for json_object; falling back to plain chat completions",
                                provider,
                                model_id,
                                resp.status_code,
                            )
                            resp = await client.post(base_url, headers=headers, json=req_base)

                # Handle Rate Limit (429) or Server Errors (502, 503, 504) with exponential backoff + jitter
                if resp.status_code in (429, 502, 503, 504):
                    last_err_text = resp.text[:300]
                    if attempt < max_retries - 1:
                        wait_s = (2 ** attempt) * 1.5 + random.uniform(0.5, 2.0)
                        log.warning(
                            "LLM HTTP %s on %s (%s) [attempt %s/%s]; rate-limited or transient error, retrying in %.1fs...",
                            resp.status_code,
                            model_id,
                            snapshot.get("symbol"),
                            attempt + 1,
                            max_retries,
                            wait_s,
                        )
                        await asyncio.sleep(wait_s)
                        continue

                if resp.is_error:
                    raise RuntimeError(f"HTTP {resp.status_code} ({model_id}): {resp.text[:300]}")
                raw_resp = resp.json()
                if isinstance(raw_resp, dict) and raw_resp.get("error") and not raw_resp.get("choices"):
                    err_msg = str(raw_resp["error"])
                    if "rate_limit" in err_msg.lower() or "429" in err_msg:
                        last_err_text = err_msg
                        if attempt < max_retries - 1:
                            wait_s = (2 ** attempt) * 1.5 + random.uniform(0.5, 2.0)
                            log.warning(
                                "LLM body rate limit error on %s (%s) [attempt %s/%s], retrying in %.1fs...",
                                model_id,
                                snapshot.get("symbol"),
                                attempt + 1,
                                max_retries,
                                wait_s,
                            )
                            await asyncio.sleep(wait_s)
                            continue
                    raise RuntimeError(f"LLM API error: {err_msg}")
                return raw_resp
            raise RuntimeError(f"HTTP 429 / Rate limit exceeded after {max_retries} attempts ({model_id}): {last_err_text}")

        messages = list(base_payload["messages"])
        raw_response = await _call_llm(messages)
        content, reasoning, finish_reason = _extract_choice_fields(raw_response)

        # Some thinking/reasoning models place the final JSON inside reasoning when content is empty
        decision: Optional[AISetupDecision] = None
        if not content and reasoning:
            try:
                decision = AISetupDecision.model_validate_json(_extract_json_content(reasoning))
            except (ValidationError, ValueError):
                decision = None

        # Retry once with higher max_tokens & plain mode if content is empty (e.g. thinking exhausted max_tokens)
        if decision is None and not content:
            retry_max_tokens = min(8192, max(eff_max_tokens * 2, 4096))
            log.warning(
                "Model '%s' (%s) returned empty content (finish_reason=%s); retrying once with max_tokens=%s in plain mode",
                model_id,
                snapshot.get("symbol"),
                finish_reason or "unknown",
                retry_max_tokens,
            )
            empty_retry_messages = [
                messages[0],
                {
                    "role": "user",
                    "content": (
                        f"{messages[1]['content']}\n\n"
                        "PENTING: Berpikir singkat saja dan langsung tulis JSON valid sesuai schema pada content utama (jangan sampai terpotong)."
                    ),
                },
            ]
            raw_response = await _call_llm(
                empty_retry_messages,
                max_tokens_override=retry_max_tokens,
                force_plain=True,
            )
            content, reasoning, finish_reason = _extract_choice_fields(raw_response)
            if not content and reasoning:
                try:
                    decision = AISetupDecision.model_validate_json(_extract_json_content(reasoning))
                except (ValidationError, ValueError):
                    decision = None

        if decision is None and not content:
            reason_hint = f" (finish_reason={finish_reason})" if finish_reason else ""
            raise RuntimeError(
                f"Model '{model_id}' mengembalikan content kosong/null{reason_hint}. "
                f"Jika memakai model :thinking, naikkan LLM Max Tokens (mis. 4000) atau pilih model non-thinking."
            )

        if decision is None:
            json_text = _extract_json_content(content)
            try:
                decision = AISetupDecision.model_validate_json(json_text)
            except (ValidationError, ValueError) as parse_err:
                log.warning(
                    "JSON/Schema validation failed for %s (%s); retrying once: %s",
                    model_id,
                    snapshot.get("symbol"),
                    parse_err,
                )
                retry_messages = [
                    *messages,
                    {"role": "assistant", "content": content},
                    {
                        "role": "user",
                        "content": (
                            f"Output JSON sebelumnya gagal validasi schema: {str(parse_err)[:400]}. "
                            f"Perbaiki dan kembalikan HANYA JSON valid sesuai schema tanpa teks lain."
                        ),
                    },
                ]
                raw_response = await _call_llm(retry_messages)
                content, _, _ = _extract_choice_fields(raw_response)
                if not content:
                    raise RuntimeError(
                        f"Model '{model_id}' mengembalikan content kosong pada retry validasi JSON."
                    ) from parse_err
                json_text = _extract_json_content(content)
                decision = AISetupDecision.model_validate_json(json_text)

        # Ensure symbol and strategy_used are normalized cleanly
        decision.symbol = snapshot["symbol"]
        decision.strategy_used = strategy.strip().upper()
        return decision, raw_response
    finally:
        if own_client:
            await client.aclose()


PAIR_RANKER_SYSTEM_PROMPT = (
    "Kamu adalah analis crypto futures yang memilih pair paling layak dipindai untuk setup trading "
    "intraday (LONG/SHORT) dari daftar kandidat MEXC Futures. Prioritaskan pair dengan peluang setup "
    "jelas: likuiditas memadai, volatilitas sehat, momentum/struktur berarah, dan funding yang "
    "mengindikasikan potensi squeeze/reversal. Hindari pair yang tampak sudah pump/dump ekstrem tanpa "
    "pola, terlalu sempit range-nya, atau bergerak acak. Jawab HANYA JSON valid."
)


def _compact_candidate(c: dict[str, Any]) -> dict[str, Any]:
    t = c.get("ticker") or {}
    last = float(t.get("lastPrice") or 0.0)
    high = float(t.get("high24Price") or 0.0)
    low = float(t.get("lower24Price") or 0.0)
    span = high - low
    return {
        "symbol": c["symbol"],
        "rule_score": c.get("auto_score"),
        "price": last,
        "change_24h_pct": round(float(t.get("riseFallRate") or 0.0) * 100.0, 2),
        "range_24h_pct": round(span / last * 100.0, 2) if last > 0 else None,
        "pos_in_range_pct": round((last - low) / span * 100.0, 1) if span > 0 else None,
        "funding_rate_pct": round(float(t.get("fundingRate") or 0.0) * 100.0, 4),
        "volume_24h_usdt_m": round(float(t.get("amount24") or 0.0) / 1e6, 1),
    }


async def rank_pairs_with_ai(
    candidates: list[dict[str, Any]],
    pick_n: int,
    llm_config: dict[str, str],
    btc_context: Optional[dict[str, Any]] = None,
    client: Optional[httpx.AsyncClient] = None,
    timeout_seconds: Optional[int] = None,
    max_tokens: Optional[int] = None,
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """Ask the LLM to pick the best `pick_n` pairs among rule-scored candidates.

    Returns ([{"symbol", "reason"}, ...] in ranked order, raw_response). Only symbols present in
    `candidates` are kept (hallucinated symbols are dropped). Raises RuntimeError on config/API/parse
    failure so callers can fall back to rule-based ranking.
    """
    api_key = llm_config.get("api_key", "").strip()
    base_url = llm_config.get("base_url", "").strip()
    model_id = llm_config.get("model_id", "").strip()
    provider = llm_config.get("provider", "commandcode").strip()
    if not api_key:
        raise RuntimeError(f"API Key untuk provider '{provider}' belum diisi.")
    if not base_url:
        raise RuntimeError(f"Base URL untuk provider '{provider}' belum diisi.")
    if not candidates:
        return [], {}

    allowed = {c["symbol"] for c in candidates}
    pick_n = max(1, min(int(pick_n), len(candidates)))
    if btc_context:
        btc_section = (
            f"Konteks BTC_USDT (hasil scan Market Mover terakhir, cek 'scanned_at' untuk umurnya): "
            f"{json.dumps(btc_context, ensure_ascii=False)}\n"
            f"Gunakan konteks BTC: saat BTC TRENDING utamakan altcoin yang bergerak searah bias BTC; "
            f"saat RANGING utamakan pair dengan range jelas untuk mean reversion/scalp; saat volatilitas "
            f"tinggi atau funding ekstrem utamakan pair paling likuid dan hindari yang sudah pump/dump ekstrem.\n"
        )
    else:
        btc_section = "Konteks BTC_USDT tidak tersedia; nilai kandidat murni dari datanya sendiri.\n"
    user_message = (
        f"Pilih maksimal {pick_n} pair terbaik (urut dari paling menjanjikan) dari kandidat berikut.\n"
        f"'rule_score' adalah skor peluang berbasis rumus (0-100) sebagai referensi, bukan keharusan.\n"
        f"{btc_section}"
        f"Kembalikan HANYA JSON: "
        f'{{"picks":[{{"symbol":"<SYMBOL dari kandidat>","reason":"<alasan singkat maks 140 karakter>"}}]}}\n\n'
        f"KANDIDAT:\n{json.dumps([_compact_candidate(c) for c in candidates], ensure_ascii=False)}"
    )
    payload: dict[str, Any] = {
        "model": model_id,
        "temperature": 0.2,
        "max_tokens": max(1024, min(8192, int(max_tokens if max_tokens is not None else settings.llm_max_tokens))),
        "stream": False,
        "messages": [
            {"role": "system", "content": PAIR_RANKER_SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
    }
    headers = _build_headers(provider, api_key)

    own_client = False
    if client is None:
        client = httpx.AsyncClient(timeout=httpx.Timeout(timeout_seconds or settings.llm_timeout_seconds))
        own_client = True
    try:
        resp = await client.post(base_url, headers=headers, json={**payload, "response_format": {"type": "json_object"}})
        if resp.status_code in (400, 422):
            resp = await client.post(base_url, headers=headers, json=payload)
        if resp.is_error:
            raise RuntimeError(f"HTTP {resp.status_code} ({model_id}): {resp.text[:300]}")
        raw = resp.json()
        content, reasoning, _ = _extract_choice_fields(raw)
        text = content or reasoning
        if not text:
            raise RuntimeError(f"Model '{model_id}' mengembalikan content kosong untuk ranking pair.")
        try:
            parsed = json.loads(_extract_json_content(text))
        except ValueError as exc:
            raise RuntimeError(f"Ranking pair AI bukan JSON valid: {exc}") from exc
    finally:
        if own_client:
            await client.aclose()

    raw_picks = parsed.get("picks") if isinstance(parsed, dict) else parsed
    if not isinstance(raw_picks, list):
        raise RuntimeError("Ranking pair AI tidak memuat daftar 'picks'.")

    picks: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in raw_picks:
        sym = str(item.get("symbol") if isinstance(item, dict) else item or "").strip().upper()
        if sym not in allowed or sym in seen:
            continue
        seen.add(sym)
        reason = str(item.get("reason") or "").strip()[:200] if isinstance(item, dict) else ""
        picks.append({"symbol": sym, "reason": reason})
        if len(picks) >= pick_n:
            break
    if not picks:
        raise RuntimeError("Ranking pair AI tidak menghasilkan simbol valid dari kandidat.")
    return picks, raw


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
        "stream": False,
    }

    start = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(20.0)) as client:
            resp = await client.post(base_url.strip(), headers=headers, json=payload)
            latency_ms = int((time.perf_counter() - start) * 1000)

            if resp.status_code == 200:
                try:
                    data = resp.json()
                except ValueError:
                    ctype = resp.headers.get("content-type", "-")
                    snippet = resp.text.strip()[:300] or "(response body kosong)"
                    return {
                        "success": False,
                        "message": f"HTTP 200 dari {provider}, tetapi respons bukan JSON ({ctype}): {snippet}",
                        "provider": provider,
                        "model_id": model_id,
                        "latency_ms": latency_ms,
                    }
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
