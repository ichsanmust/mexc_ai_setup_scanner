"""Application configuration and strategy constants."""

from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROMPTS_DIR = PROJECT_ROOT / "prompts"
FRONTEND_DIR = PROJECT_ROOT / "frontend"

StrategyName = Literal[
    "TREND_PULLBACK",
    "BREAKOUT_MOMENTUM",
    "MEAN_REVERSION_SCALP",
]

STRATEGY_MIN_RR: dict[str, float] = {
    "TREND_PULLBACK": 1.8,
    "BREAKOUT_MOMENTUM": 2.0,
    "MEAN_REVERSION_SCALP": 1.5,
}

STRATEGY_PROMPT_FILES: dict[str, str] = {
    "TREND_PULLBACK": "trend_pullback.txt",
    "BREAKOUT_MOMENTUM": "breakout_momentum.txt",
    "MEAN_REVERSION_SCALP": "mean_reversion_scalp.txt",
}

DEFAULT_COMMANDCODE_BASE_URL = "https://api.commandcode.ai/provider/v1/chat/completions"
DEFAULT_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1/chat/completions"


class Settings(BaseSettings):
    """Environment-backed runtime settings with safe defaults."""

    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # MySQL / Database
    database_url: str = "mysql+pymysql://root:password@127.0.0.1:3306/mexc_scanner?charset=utf8mb4"

    # LLM Initial Seed & Fallback
    llm_provider: str = "commandcode"
    llm_base_url: str = DEFAULT_COMMANDCODE_BASE_URL
    llm_api_key: str = ""
    llm_model: str = "google/gemini-2.5-flash"

    commandcode_base_url: str = DEFAULT_COMMANDCODE_BASE_URL
    commandcode_api_key: str = ""
    openrouter_base_url: str = DEFAULT_OPENROUTER_BASE_URL
    openrouter_api_key: str = ""
    custom_llm_base_url: str = ""
    custom_llm_api_key: str = ""

    llm_timeout_seconds: int = 45
    llm_max_concurrency: int = 3
    llm_max_tokens: int = 1500

    # MEXC Public Futures API
    mexc_base_url: str = "https://contract.mexc.com"
    mexc_proxy_url: str = ""
    mexc_max_concurrency: int = 5
    mexc_request_timeout_seconds: float = 15.0

    # Scanner & Scheduler
    top_n_pairs: int = 30
    htf_interval: str = "Min60"
    ltf_interval: str = "Min15"
    kline_limit: int = 250
    scan_interval_minutes: int = 15
    tracker_interval_seconds: int = 60
    setup_expiry_hours: int = 12
    active_strategies: str = "TREND_PULLBACK,BREAKOUT_MOMENTUM,MEAN_REVERSION_SCALP"

    # Pre-Filter & Risk Guard
    min_24h_quote_volume: float = 5_000_000.0
    max_24h_quote_volume: float = 0.0
    min_atr_pct: float = 0.25
    max_atr_pct: float = 8.0
    min_confidence: int = 75

    # Web Server
    app_host: str = "0.0.0.0"
    app_port: int = 8001
    auto_start_scheduler: bool = True

    @property
    def active_strategy_list(self) -> list[str]:
        """Return validated list of configured active strategy names."""
        items = [s.strip().upper() for s in self.active_strategies.split(",") if s.strip()]
        valid = [s for s in items if s in STRATEGY_MIN_RR]
        return valid or list(STRATEGY_MIN_RR.keys())


settings = Settings()
