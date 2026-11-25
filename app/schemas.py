"""Pydantic schemas for AI decisions, API responses, and settings management."""

from datetime import datetime
import re
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

StrategyType = str
DecisionType = Literal["LONG", "SHORT", "NO_TRADE"]
RegimeType = Literal["TRENDING_UP", "TRENDING_DOWN", "RANGING", "HIGH_VOLATILITY_CHOP"]
EntryType = Literal["MARKET", "LIMIT", "NONE"]
SetupStatusType = Literal[
    "OPEN",
    "ENTRY_HIT",
    "EXTENDED",
    "HIT_TP",
    "HIT_SL",
    "BEP",
    "EXPIRED",
    "MANUAL_TAKEN",
    "MANUAL_SKIPPED",
    "CLOSED_MANUAL_TP",
    "CLOSED_MANUAL_CL",
]
LLMProviderType = Literal["commandcode", "openrouter", "custom"]


def normalize_strategy_code(raw: str) -> str:
    """Normalize strategy code to uppercase A-Z0-9_ identifier."""
    cleaned = re.sub(r"[^A-Z0-9_]+", "_", raw.strip().upper().replace("-", "_").replace(" ", "_"))
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    if not cleaned:
        raise ValueError("Kode strategi tidak valid (gunakan huruf/angka/underscore).")
    return cleaned[:64]


class SetupChecklist(BaseModel):
    """Structured confluence checklist evaluated before final trade decision."""

    htf_trend_ok: bool = False
    pullback_or_level_ok: bool = False
    trigger_candle_ok: bool = False
    volume_ok: bool = False
    momentum_ok: bool = False
    rr_ok: bool = False


class AISetupDecision(BaseModel):
    """Strict structured JSON schema expected from the LLM decision engine."""

    symbol: str
    strategy_used: str = Field(..., min_length=1, max_length=64)
    htf_analysis: str = ""
    ltf_trigger_analysis: str = ""
    checklist: Optional[SetupChecklist] = None
    market_regime: RegimeType
    decision: DecisionType
    entry_type: EntryType
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    risk_reward_ratio: Optional[float] = None
    confidence: int = Field(..., ge=0, le=100)
    invalidation_reason: str
    rationale: str


class SetupOut(BaseModel):
    """Serialized trade setup returned to the dashboard."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    scan_run_id: Optional[int] = None
    symbol: str
    strategy_used: str
    decision: str
    market_regime: str
    entry_type: str
    entry_price: float
    stop_loss: float
    take_profit: float
    risk_reward_ratio: float
    confidence: int
    llm_provider: Optional[str] = None
    llm_model: Optional[str] = None
    invalidation_reason: str
    rationale: str
    status: str
    entry_hit_at: Optional[datetime] = None
    missed_tp_at: Optional[datetime] = None
    missed_tp_price: Optional[float] = None
    manual_action_at: Optional[datetime] = None
    manual_entry_price: Optional[float] = None
    sl_bep_price: Optional[float] = None
    sl_bep_at: Optional[datetime] = None
    manual_notes: Optional[str] = None
    resolved_price: Optional[float] = None
    resolved_at: Optional[datetime] = None
    status_history: Optional[list[dict[str, Any]]] = None
    expires_at: datetime
    features_snapshot: dict[str, Any]
    ai_payload: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    live_price: Optional[float] = None
    holding_period: Optional[str] = None
    strategy_profile: Optional[dict[str, Any]] = None
    scan_run_started_at: Optional[datetime] = None
    scan_run_settings: Optional[dict[str, Any]] = None


class RecentStatusChangeItem(BaseModel):
    """Latest status transition event surfaced in Daftar Setup recent activity strip."""

    setup_id: int
    symbol: str
    decision: str
    from_status: Optional[str] = None
    to_status: str
    event: str
    note: Optional[str] = None
    price: Optional[float] = None
    at: Optional[str] = None


class SetupListResponse(BaseModel):
    """Paginated list of trade setups."""

    items: list[SetupOut]
    total: int
    status_counts: dict[str, int] = {}
    recent_changes: list[RecentStatusChangeItem] = []


class SetupStatusUpdate(BaseModel):
    """Manual user status update request."""

    status: Literal[
        "OPEN",
        "ENTRY_HIT",
        "EXTENDED",
        "MANUAL_TAKEN",
        "MANUAL_SKIPPED",
        "CLOSED_MANUAL_TP",
        "CLOSED_MANUAL_CL",
        "BEP",
        "EXPIRED",
        "MOVE_SL_BEP",
    ]
    manual_entry_price: Optional[float] = Field(default=None, gt=0)
    sl_bep_price: Optional[float] = Field(default=None, gt=0)
    live_price: Optional[float] = Field(default=None, gt=0)
    stop_loss: Optional[float] = Field(default=None, gt=0)
    take_profit: Optional[float] = Field(default=None, gt=0)
    resolved_price: Optional[float] = Field(default=None, gt=0)
    extend_hours: Optional[int] = Field(default=None, ge=1, le=720)
    manual_notes: Optional[str] = Field(default=None, max_length=2000)


class StrategyAnalyticsItem(BaseModel):
    """Aggregated outcome performance per strategy."""

    strategy_used: str
    total_setups: int
    open_count: int
    open_waiting_count: int = 0
    entry_hit_active_count: int = 0
    extended_active_count: int = 0
    hit_tp_count: int
    hit_tp_auto_count: int = 0
    closed_manual_tp_count: int = 0
    hit_sl_count: int
    hit_sl_auto_count: int = 0
    closed_manual_cl_count: int = 0
    sl_no_entry_count: int = 0
    tp_no_entry_count: int = 0
    bep_count: int = 0
    expired_count: int
    manual_taken_count: int
    manual_skipped_count: int
    decided_count: int
    win_rate_pct: float
    avg_rr: float


class AnalyticsSummaryResponse(BaseModel):
    """Overall & per-strategy analytics summary."""

    total_setups: int
    open_count: int
    total_open_waiting_count: int = 0
    total_entry_hit_active_count: int = 0
    total_extended_active_count: int = 0
    total_manual_taken_count: int = 0
    total_tp_count: int = 0
    total_hit_tp_auto_count: int = 0
    total_closed_manual_tp_count: int = 0
    total_sl_count: int = 0
    total_hit_sl_auto_count: int = 0
    total_closed_manual_cl_count: int = 0
    total_decided_count: int = 0
    total_sl_no_entry_count: int = 0
    total_tp_no_entry_count: int = 0
    total_bep_count: int = 0
    total_expired_count: int = 0
    total_skipped_count: int = 0
    overall_win_rate_pct: float
    overall_avg_rr: float
    strategies: list[StrategyAnalyticsItem]


class CandlePoint(BaseModel):
    """Single OHLCV candle formatted for TradingView Lightweight Charts."""

    time: int
    open: float
    high: float
    low: float
    close: float
    volume: float


class EMAPoint(BaseModel):
    """Single timestamp/value point for EMA overlay."""

    time: int
    value: float


class ChartDataResponse(BaseModel):
    """Candlestick data with EMA overlays and DSS Bressert oscillator."""

    symbol: str
    interval: str
    candles: list[CandlePoint]
    ema21: list[EMAPoint]
    ema50: list[EMAPoint]
    ema200: list[EMAPoint]
    dss: list[EMAPoint] = []
    dss_signal: list[EMAPoint] = []


class ScanTriggerRequest(BaseModel):
    """Optional parameters for manual scan trigger."""

    strategies: Optional[list[StrategyType]] = None
    top_n: Optional[int] = Field(default=None, ge=1, le=100)


class ScanRunOut(BaseModel):
    """Serialized scan run history row."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    strategy: str
    llm_provider: Optional[str] = None
    llm_model: Optional[str] = None
    total_contracts: int
    top_pairs_count: int
    prefiltered_count: int
    ai_analyzed_count: int
    setups_created_count: int
    status: str
    error_message: Optional[str] = None
    settings_snapshot: Optional[dict[str, Any]] = None
    started_at: datetime
    finished_at: Optional[datetime] = None


class ScanRunListResponse(BaseModel):
    """Paginated list of scan runs."""

    items: list[ScanRunOut]
    total: int


class ScanEvaluationOut(BaseModel):
    """Serialized scan evaluation row showing NO_TRADE / prefilter / rejection reasons."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    scan_run_id: int
    symbol: str
    strategy_used: str
    raw_decision: str
    rejection_reason: str
    confidence: Optional[int] = None
    created_at: datetime


class ScanRunEvaluationsResponse(BaseModel):
    """Full audit detail of a single scan run."""

    run: ScanRunOut
    evaluations: list[ScanEvaluationOut]
    setups: list[SetupOut]


class AIModelCreate(BaseModel):
    """Request schema to register a new AI model."""

    name: str = Field(..., min_length=1, max_length=100)
    model_id: str = Field(..., min_length=1, max_length=150)
    provider: LLMProviderType = "commandcode"
    description: Optional[str] = Field(default=None, max_length=255)


class AIModelUpdate(BaseModel):
    """Request schema to edit an existing AI model."""

    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    model_id: Optional[str] = Field(default=None, min_length=1, max_length=150)
    provider: Optional[LLMProviderType] = None
    description: Optional[str] = Field(default=None, max_length=255)


class AIModelOut(BaseModel):
    """Serialized AI model record."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    model_id: str
    provider: str
    description: Optional[str] = None
    is_active: bool
    is_custom: bool
    created_at: datetime
    updated_at: datetime


class AISettingsOut(BaseModel):
    """Active LLM provider settings with masked API keys."""

    active_provider: str
    active_model_id: str
    active_model_name: str
    active_base_url: str
    commandcode_base_url: str
    commandcode_api_key_masked: str
    has_commandcode_api_key: bool
    openrouter_base_url: str
    openrouter_api_key_masked: str
    has_openrouter_api_key: bool
    custom_llm_base_url: str
    custom_llm_api_key_masked: str
    has_custom_llm_api_key: bool


class AISettingsUpdate(BaseModel):
    """Update provider selection, base URLs, and API keys."""

    active_provider: Optional[LLMProviderType] = None
    commandcode_base_url: Optional[str] = Field(default=None, max_length=500)
    commandcode_api_key: Optional[str] = None
    openrouter_base_url: Optional[str] = Field(default=None, max_length=500)
    openrouter_api_key: Optional[str] = None
    custom_llm_base_url: Optional[str] = Field(default=None, max_length=500)
    custom_llm_api_key: Optional[str] = None


class AITestRequest(BaseModel):
    """Optional overrides to test connection before saving/activating."""

    provider: Optional[LLMProviderType] = None
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    model_id: Optional[str] = None


class AITestResponse(BaseModel):
    """Connection test result."""

    success: bool
    message: str
    provider: str
    model_id: str
    latency_ms: Optional[int] = None


class ScannerSettingsOut(BaseModel):
    """Persistent global scanner, MEXC API, LLM runtime, and risk-guard settings."""

    llm_timeout_seconds: int
    llm_max_concurrency: int
    llm_max_tokens: int = 1500
    mexc_base_url: str
    mexc_proxy_url: str
    mexc_max_concurrency: int
    auto_scan_enabled: bool
    scan_mode: Literal["AUTO", "MANUAL"]
    pair_selection_mode: Literal["TOP_N", "CUSTOM"] = "TOP_N"
    selected_pairs: list[str] = []
    top_n_pairs: int
    scan_interval_minutes: int
    tracker_interval_seconds: int
    active_strategies: list[str]
    min_24h_quote_volume: float
    max_24h_quote_volume: float = 0.0
    min_atr_pct: float
    max_atr_pct: float
    min_confidence: int
    risk_profile: Literal["CONSERVATIVE", "MODERATE", "AGGRESSIVE"] = "CONSERVATIVE"


class ScannerSettingsUpdate(BaseModel):
    """Update global scanner, MEXC API, LLM runtime, and risk-guard settings in MySQL."""

    llm_timeout_seconds: Optional[int] = Field(default=None, ge=5, le=300)
    llm_max_concurrency: Optional[int] = Field(default=None, ge=1, le=20)
    llm_max_tokens: Optional[int] = Field(default=None, ge=512, le=8192)
    mexc_base_url: Optional[str] = Field(default=None, min_length=8, max_length=300)
    mexc_proxy_url: Optional[str] = Field(default=None, max_length=300)
    mexc_max_concurrency: Optional[int] = Field(default=None, ge=1, le=20)
    auto_scan_enabled: Optional[bool] = None
    pair_selection_mode: Optional[Literal["TOP_N", "CUSTOM"]] = None
    selected_pairs: Optional[list[str]] = None
    top_n_pairs: Optional[int] = Field(default=None, ge=1, le=100)
    scan_interval_minutes: Optional[int] = Field(default=None, ge=1, le=1440)
    tracker_interval_seconds: Optional[int] = Field(default=None, ge=15, le=3600)
    active_strategies: Optional[list[str]] = None
    min_24h_quote_volume: Optional[float] = Field(default=None, ge=0.0)
    max_24h_quote_volume: Optional[float] = Field(default=None, ge=0.0)
    min_atr_pct: Optional[float] = Field(default=None, ge=0.0, le=50.0)
    max_atr_pct: Optional[float] = Field(default=None, ge=0.1, le=100.0)
    min_confidence: Optional[int] = Field(default=None, ge=0, le=100)
    risk_profile: Optional[Literal["CONSERVATIVE", "MODERATE", "AGGRESSIVE"]] = None


class StrategyCreate(BaseModel):
    """Create a new AI trading strategy stored in MySQL."""

    name: str = Field(..., min_length=2, max_length=64)
    display_name: Optional[str] = Field(default=None, max_length=120)
    description: Optional[str] = Field(default=None, max_length=255)
    trade_style: Optional[str] = Field(default="INTRADAY", max_length=40)
    holding_period: Optional[str] = Field(default="4 - 24 Jam", max_length=80)
    suggested_htf: Optional[str] = Field(default="Min60", max_length=20)
    suggested_ltf: Optional[str] = Field(default="Min15", max_length=20)
    suggested_kline_limit: Optional[int] = Field(default=250, ge=60, le=500)
    suggested_expiry_hours: Optional[int] = Field(default=12, ge=1, le=168)
    prompt_text: str = Field(..., min_length=10, max_length=20000)
    min_rr: float = Field(default=1.5, ge=0.5, le=20.0)
    is_active: bool = True

    @field_validator("name")
    @classmethod
    def _clean_name(cls, v: str) -> str:
        return normalize_strategy_code(v)


class StrategyUpdate(BaseModel):
    """Update an existing strategy's code/name, metadata, suggestions, prompt rules, min R:R, or active status."""

    name: Optional[str] = Field(default=None, min_length=2, max_length=64)
    display_name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    description: Optional[str] = Field(default=None, max_length=255)
    trade_style: Optional[str] = Field(default=None, max_length=40)
    holding_period: Optional[str] = Field(default=None, max_length=80)
    suggested_htf: Optional[str] = Field(default=None, max_length=20)
    suggested_ltf: Optional[str] = Field(default=None, max_length=20)
    suggested_kline_limit: Optional[int] = Field(default=None, ge=60, le=500)
    suggested_expiry_hours: Optional[int] = Field(default=None, ge=1, le=168)
    prompt_text: Optional[str] = Field(default=None, min_length=10, max_length=20000)
    min_rr: Optional[float] = Field(default=None, ge=0.5, le=20.0)
    is_active: Optional[bool] = None

    @field_validator("name")
    @classmethod
    def _clean_name(cls, v: Optional[str]) -> Optional[str]:
        return normalize_strategy_code(v) if v is not None else None


class StrategyOut(BaseModel):
    """Serialized strategy record from MySQL."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    display_name: str
    description: Optional[str] = None
    trade_style: Optional[str] = None
    holding_period: Optional[str] = None
    suggested_htf: Optional[str] = None
    suggested_ltf: Optional[str] = None
    suggested_kline_limit: Optional[int] = None
    suggested_expiry_hours: Optional[int] = None
    prompt_text: str
    min_rr: float
    is_active: bool
    is_builtin: bool
    created_at: datetime
    updated_at: datetime
