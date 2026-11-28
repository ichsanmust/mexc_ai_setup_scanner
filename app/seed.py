"""Initial database seeding for AI models and LLM provider settings."""

from decimal import Decimal
import json
import logging

from sqlalchemy.orm import Session

from .config import (
    DEFAULT_COMMANDCODE_BASE_URL,
    DEFAULT_OPENROUTER_BASE_URL,
    PROMPTS_DIR,
    STRATEGY_MIN_RR,
    STRATEGY_PROMPT_FILES,
    settings,
)
from .models import AIModel, AppSetting, Strategy

DEFAULT_STRATEGY_META: dict[str, dict[str, object]] = {
    "TREND_PULLBACK": {
        "display_name": "Trend Pullback (Intraday)",
        "description": "Intraday trend following & pullback ke EMA 21/50 / flip zone searah tren HTF (min R:R 1.8).",
        "trade_style": "INTRADAY",
        "holding_period": "4 - 24 Jam (Intraday)",
        "suggested_htf": "Min60",
        "suggested_ltf": "Min15",
        "suggested_kline_limit": 250,
        "suggested_expiry_hours": 12,
    },
    "BREAKOUT_MOMENTUM": {
        "display_name": "Breakout Momentum (Intraday / Short-Swing)",
        "description": "Breakout konsolidasi level kunci dengan konfirmasi volume >= 1.5x MA20 (min R:R 2.0).",
        "trade_style": "INTRADAY_SWING",
        "holding_period": "4 - 48 Jam (1 - 2 Hari)",
        "suggested_htf": "Min60",
        "suggested_ltf": "Min15",
        "suggested_kline_limit": 250,
        "suggested_expiry_hours": 24,
    },
    "MEAN_REVERSION_SCALP": {
        "display_name": "Mean Reversion (Scalp)",
        "description": "Pantulan Support/Resistance + RSI ekstrem khusus saat market RANGING (min R:R 1.5).",
        "trade_style": "SCALP",
        "holding_period": "1 - 6 Jam (Scalp)",
        "suggested_htf": "Min30",
        "suggested_ltf": "Min5",
        "suggested_kline_limit": 250,
        "suggested_expiry_hours": 6,
    },
}

log = logging.getLogger(__name__)

DEFAULT_AI_MODELS = [
    # Command Code AI presets
    {
        "name": "Gemini 2.5 Flash (Command Code)",
        "model_id": "google/gemini-2.5-flash",
        "provider": "commandcode",
        "description": "Cepat dan akurat untuk analisis JSON terstruktur multi-pair.",
        "is_custom": False,
    },
    {
        "name": "GPT-4o Mini (Command Code)",
        "model_id": "openai/gpt-4o-mini",
        "provider": "commandcode",
        "description": "Model ringan dan konsisten untuk output JSON Schema ketat.",
        "is_custom": False,
    },
    {
        "name": "Claude 3.5 Sonnet (Command Code)",
        "model_id": "anthropic/claude-3.5-sonnet",
        "provider": "commandcode",
        "description": "Penalaran teknikal mendalam untuk konfirmasi struktur multi-timeframe.",
        "is_custom": False,
    },
    # OpenRouter presets
    {
        "name": "Google Gemini 2.5 Flash (OpenRouter)",
        "model_id": "google/gemini-2.5-flash",
        "provider": "openrouter",
        "description": "Rekomendasi cepat & hemat token melalui OpenRouter.",
        "is_custom": False,
    },
    {
        "name": "OpenAI GPT-4o Mini (OpenRouter)",
        "model_id": "openai/gpt-4o-mini",
        "provider": "openrouter",
        "description": "Model cepat OpenAI via OpenRouter dengan dukungan JSON Schema.",
        "is_custom": False,
    },
    {
        "name": "DeepSeek Chat V3 (OpenRouter)",
        "model_id": "deepseek/deepseek-chat-v3-0324",
        "provider": "openrouter",
        "description": "Alternatif reasoning kuantitatif hemat biaya via OpenRouter.",
        "is_custom": False,
    },
    {
        "name": "Anthropic Claude 3.7 Sonnet (OpenRouter)",
        "model_id": "anthropic/claude-3.7-sonnet",
        "provider": "openrouter",
        "description": "Model penalaran tinggi untuk filtering setup ketat.",
        "is_custom": False,
    },
    # OpenRouter Free models
    {
        "name": "OpenRouter Free Router [Free]",
        "model_id": "openrouter/free",
        "provider": "openrouter",
        "description": "Free - Router otomatis ke model gratis yang tersedia (mendukung structured_outputs & response_format).",
        "is_custom": False,
    },
    {
        "name": "Google Gemma 4 31B [Free]",
        "model_id": "google/gemma-4-31b-it:free",
        "provider": "openrouter",
        "description": "Free - Google Gemma 4 31B gratis, mendukung response_format & context 262k.",
        "is_custom": False,
    },
    {
        "name": "Google Gemma 4 26B A4B [Free]",
        "model_id": "google/gemma-4-26b-a4b-it:free",
        "provider": "openrouter",
        "description": "Free - Google Gemma 4 26B MoE cepat & gratis, mendukung response_format.",
        "is_custom": False,
    },
    {
        "name": "Ling 3.2 Flash [Free]",
        "model_id": "inclusionai/ling-3.2-flash:free",
        "provider": "openrouter",
        "description": "Free - Gratis, mendukung response_format & structured_outputs (context 1M).",
        "is_custom": False,
    },
    {
        "name": "NVIDIA Nemotron 3.5 Lightning [Free]",
        "model_id": "nvidia/nemotron-3.5-lightning:free",
        "provider": "openrouter",
        "description": "Free - Gratis, inferensi cepat (fallback JSON prompt).",
        "is_custom": False,
    },
    {
        "name": "NVIDIA Nemotron 3 Ultra [Free]",
        "model_id": "nvidia/nemotron-3-ultra-550b-a55b:free",
        "provider": "openrouter",
        "description": "Free - Gratis, model reasoning besar (fallback JSON prompt).",
        "is_custom": False,
    },
]


def _upsert_default_setting(db: Session, key: str, value: str, description: str) -> None:
    """Create setting row if missing without overwriting user-edited DB values."""
    existing = db.query(AppSetting).filter(AppSetting.key == key).first()
    if not existing:
        db.add(AppSetting(key=key, value=value, description=description))


def seed_all(db: Session) -> None:
    """Seed default LLM provider settings and selectable AI models into MySQL."""
    env_provider = (settings.llm_provider or "commandcode").strip().lower()
    if env_provider not in {"commandcode", "openrouter", "custom"}:
        env_provider = "commandcode"

    cmd_key = settings.commandcode_api_key or (settings.llm_api_key if env_provider == "commandcode" else "")
    or_key = settings.openrouter_api_key or (settings.llm_api_key if env_provider == "openrouter" else "")
    custom_key = settings.custom_llm_api_key or (settings.llm_api_key if env_provider == "custom" else "")

    cmd_url = settings.commandcode_base_url or (
        settings.llm_base_url if env_provider == "commandcode" else DEFAULT_COMMANDCODE_BASE_URL
    )
    or_url = settings.openrouter_base_url or (
        settings.llm_base_url if env_provider == "openrouter" else DEFAULT_OPENROUTER_BASE_URL
    )
    custom_url = settings.custom_llm_base_url or (settings.llm_base_url if env_provider == "custom" else "")

    _upsert_default_setting(
        db,
        "llm_active_provider",
        env_provider,
        "Provider LLM aktif: commandcode, openrouter, atau custom",
    )
    _upsert_default_setting(
        db,
        "commandcode_base_url",
        cmd_url,
        "Endpoint Chat Completions untuk Command Code AI",
    )
    _upsert_default_setting(
        db,
        "commandcode_api_key",
        cmd_key,
        "API Key Command Code AI",
    )
    _upsert_default_setting(
        db,
        "openrouter_base_url",
        or_url,
        "Endpoint Chat Completions untuk OpenRouter",
    )
    _upsert_default_setting(
        db,
        "openrouter_api_key",
        or_key,
        "API Key OpenRouter",
    )
    _upsert_default_setting(
        db,
        "custom_llm_base_url",
        custom_url,
        "Endpoint Chat Completions custom OpenAI-compatible",
    )
    _upsert_default_setting(
        db,
        "custom_llm_api_key",
        custom_key,
        "API Key untuk endpoint custom",
    )
    _upsert_default_setting(
        db,
        "llm_timeout_seconds",
        str(settings.llm_timeout_seconds),
        "Timeout request LLM dalam detik",
    )
    _upsert_default_setting(
        db,
        "llm_max_concurrency",
        str(settings.llm_max_concurrency),
        "Maksimum request paralel ke LLM",
    )
    _upsert_default_setting(
        db,
        "llm_max_tokens",
        str(settings.llm_max_tokens),
        "Maksimum output token AI per panggilan (512-8192; mengontrol reservasi kredit OpenRouter)",
    )
    _upsert_default_setting(
        db,
        "mexc_base_url",
        settings.mexc_base_url,
        "Base URL public REST MEXC Futures",
    )
    _upsert_default_setting(
        db,
        "mexc_proxy_url",
        settings.mexc_proxy_url,
        "Proxy opsional untuk request MEXC (kosongkan jika langsung)",
    )
    _upsert_default_setting(
        db,
        "mexc_max_concurrency",
        str(settings.mexc_max_concurrency),
        "Maksimum request paralel ke MEXC",
    )
    _upsert_default_setting(
        db,
        "auto_scan_enabled",
        "true" if settings.auto_start_scheduler else "false",
        "Mode auto-scan terjadwal (true=AUTO, false=MANUAL)",
    )
    _upsert_default_setting(
        db,
        "top_n_pairs",
        str(settings.top_n_pairs),
        "Jumlah Top N pair berdasarkan volume 24 jam",
    )
    _upsert_default_setting(
        db,
        "scan_interval_minutes",
        str(settings.scan_interval_minutes),
        "Interval auto-scan dalam menit",
    )
    _upsert_default_setting(
        db,
        "tracker_interval_seconds",
        str(settings.tracker_interval_seconds),
        "Interval pengecekan outcome setup OPEN dalam detik",
    )
    # Remove obsolete global timeframe/kline/expiry records (now managed strictly per strategy)
    db.query(AppSetting).filter(
        AppSetting.key.in_(["htf_interval", "ltf_interval", "kline_limit", "setup_expiry_hours"])
    ).delete(synchronize_session=False)
    _upsert_default_setting(
        db,
        "active_strategies",
        ",".join(settings.active_strategy_list),
        "Daftar strategi aktif dipisah koma",
    )
    _upsert_default_setting(
        db,
        "min_24h_quote_volume",
        str(settings.min_24h_quote_volume),
        "Filter minimal volume quote 24 jam (USDT)",
    )
    _upsert_default_setting(
        db,
        "max_24h_quote_volume",
        str(settings.max_24h_quote_volume),
        "Filter maksimal volume quote 24 jam (USDT, 0 = tanpa batas)",
    )
    _upsert_default_setting(
        db,
        "auto_pair_min_volume",
        str(settings.auto_pair_min_volume),
        "Batas minimal likuiditas 24 jam (USDT) untuk mode Auto Opportunity",
    )
    _upsert_default_setting(
        db,
        "auto_use_ai_ranking",
        "true" if settings.auto_use_ai_ranking else "false",
        "Gunakan AI untuk memilih pair final di mode Auto Opportunity",
    )
    _upsert_default_setting(
        db,
        "min_atr_pct",
        str(settings.min_atr_pct),
        "Pre-filter minimal ATR% LTF (skip market mati)",
    )
    _upsert_default_setting(
        db,
        "max_atr_pct",
        str(settings.max_atr_pct),
        "Pre-filter maksimal ATR% LTF (skip chop ekstrem)",
    )
    _upsert_default_setting(
        db,
        "min_confidence",
        str(settings.min_confidence),
        "Minimal confidence AI (0-100) untuk lolos Risk Guard",
    )
    _upsert_default_setting(
        db,
        "risk_profile",
        settings.risk_profile,
        "Profil risiko AI & R:R: CONSERVATIVE, MODERATE, atau AGGRESSIVE",
    )

    # Seed AI models if missing
    for item in DEFAULT_AI_MODELS:
        exists = (
            db.query(AIModel)
            .filter(AIModel.provider == item["provider"], AIModel.model_id == item["model_id"])
            .first()
        )
        if not exists:
            db.add(
                AIModel(
                    name=item["name"],
                    model_id=item["model_id"],
                    provider=item["provider"],
                    description=item["description"],
                    is_active=False,
                    is_custom=item["is_custom"],
                )
            )
    db.flush()

    # Ensure custom env LLM_MODEL exists and is active if no active model yet
    active_model = db.query(AIModel).filter(AIModel.is_active.is_(True)).first()
    if not active_model:
        target = (
            db.query(AIModel)
            .filter(AIModel.provider == env_provider, AIModel.model_id == settings.llm_model)
            .first()
        )
        if not target:
            target = (
                db.query(AIModel)
                .filter(AIModel.provider == env_provider)
                .order_by(AIModel.id.asc())
                .first()
            )
        if not target:
            target = AIModel(
                name=f"{settings.llm_model} ({env_provider})",
                model_id=settings.llm_model,
                provider=env_provider,
                description="Seeded from .env LLM_MODEL",
                is_active=True,
                is_custom=True,
            )
            db.add(target)
        else:
            target.is_active = True
        db.flush()
        active_model = target

    if active_model:
        _upsert_default_setting(
            db,
            "active_model_id",
            active_model.model_id,
            "Model ID AI aktif yang digunakan untuk analisis setup",
        )

    # Seed default strategies from prompts/ files if missing in strategies table
    active_setting_row = db.query(AppSetting).filter(AppSetting.key == "active_strategies").first()
    raw_active = (
        active_setting_row.value
        if active_setting_row and active_setting_row.value
        else ",".join(settings.active_strategy_list)
    )
    default_active_set = {s.strip().upper() for s in raw_active.split(",") if s.strip()}

    for strat_name, filename in STRATEGY_PROMPT_FILES.items():
        exists = db.query(Strategy).filter(Strategy.name == strat_name).first()
        meta = DEFAULT_STRATEGY_META.get(strat_name, {})
        if not exists:
            prompt_path = PROMPTS_DIR / filename
            prompt_content = prompt_path.read_text(encoding="utf-8") if prompt_path.exists() else ""
            db.add(
                Strategy(
                    name=strat_name,
                    display_name=str(meta.get("display_name", strat_name)),
                    description=str(meta["description"]) if meta.get("description") else None,
                    trade_style=str(meta["trade_style"]) if meta.get("trade_style") else None,
                    holding_period=str(meta["holding_period"]) if meta.get("holding_period") else None,
                    suggested_htf=str(meta["suggested_htf"]) if meta.get("suggested_htf") else None,
                    suggested_ltf=str(meta["suggested_ltf"]) if meta.get("suggested_ltf") else None,
                    suggested_kline_limit=int(meta.get("suggested_kline_limit", 250)),
                    suggested_expiry_hours=int(meta.get("suggested_expiry_hours", 12)),
                    prompt_text=prompt_content,
                    min_rr=Decimal(str(STRATEGY_MIN_RR.get(strat_name, 1.5))),
                    is_active=strat_name in default_active_set,
                    is_builtin=True,
                )
            )
        else:
            # Backfill suggestion fields for existing rows that predate the new columns
            if not exists.trade_style and meta.get("trade_style"):
                exists.trade_style = str(meta["trade_style"])
            if not exists.holding_period and meta.get("holding_period"):
                exists.holding_period = str(meta["holding_period"])
            if not exists.suggested_htf and meta.get("suggested_htf"):
                exists.suggested_htf = str(meta["suggested_htf"])
            if not exists.suggested_ltf and meta.get("suggested_ltf"):
                exists.suggested_ltf = str(meta["suggested_ltf"])
            if not exists.suggested_kline_limit and meta.get("suggested_kline_limit"):
                exists.suggested_kline_limit = int(meta["suggested_kline_limit"])
            if not exists.suggested_expiry_hours and meta.get("suggested_expiry_hours"):
                exists.suggested_expiry_hours = int(meta["suggested_expiry_hours"])
    db.flush()

    db.commit()
    log.info("Database seed completed (active provider=%s, model=%s).", env_provider, active_model.model_id if active_model else "none")


_LEGACY_PROMPT_MARKERS = ("ambang min_confidence Risk Guard", "ambang Risk Guard")


def sync_builtin_prompts(db: Session, force: bool = False) -> dict[str, list[str]]:
    """Sync strategy prompt_text from prompts/ (.txt & .json) without overwriting customized prompts.

    When force=False, only updates strategies whose prompt_text is empty or still contains
    legacy Risk Guard threshold phrasing.
    """
    source_prompts: dict[str, str] = {}
    for strat_name, filename in STRATEGY_PROMPT_FILES.items():
        path = PROMPTS_DIR / filename
        if path.exists():
            source_prompts[strat_name.upper()] = path.read_text(encoding="utf-8")

    for json_path in sorted(PROMPTS_DIR.glob("*.json")):
        try:
            payload = json.loads(json_path.read_text(encoding="utf-8"))
            name = str(payload.get("name") or "").strip().upper()
            text = str(payload.get("prompt_text") or "").strip()
            if name and text:
                source_prompts[name] = text
        except Exception as exc:
            log.warning("Skipping invalid preset %s during prompt sync: %s", json_path.name, exc)

    updated: list[str] = []
    skipped: list[str] = []
    for row in db.query(Strategy).order_by(Strategy.id.asc()).all():
        key = row.name.strip().upper()
        new_text = source_prompts.get(key)
        if not new_text:
            continue
        cur_text = row.prompt_text or ""
        has_legacy = any(marker in cur_text for marker in _LEGACY_PROMPT_MARKERS)
        if force or not cur_text.strip() or (row.is_builtin and has_legacy) or has_legacy:
            if cur_text != new_text:
                row.prompt_text = new_text
                updated.append(key)
        else:
            skipped.append(key)

    if updated:
        db.commit()
    return {"updated": updated, "skipped": skipped}
