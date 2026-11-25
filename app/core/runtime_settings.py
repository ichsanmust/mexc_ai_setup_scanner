"""Centralized MySQL-backed runtime settings resolver with .env/code defaults fallback."""

from typing import Any, Optional

from sqlalchemy.orm import Session

from ..config import STRATEGY_MIN_RR, settings
from ..models import AppSetting, Strategy

RUNTIME_SETTING_KEYS = [
    "llm_timeout_seconds",
    "llm_max_concurrency",
    "llm_max_tokens",
    "mexc_base_url",
    "mexc_proxy_url",
    "mexc_max_concurrency",
    "auto_scan_enabled",
    "pair_selection_mode",
    "selected_pairs",
    "top_n_pairs",
    "scan_interval_minutes",
    "tracker_interval_seconds",
    "active_strategies",
    "min_24h_quote_volume",
    "max_24h_quote_volume",
    "min_atr_pct",
    "max_atr_pct",
    "min_confidence",
    "risk_profile",
]


def _parse_int(raw: Optional[str], default: int, min_val: int, max_val: int) -> int:
    try:
        val = int(str(raw).strip()) if raw is not None and str(raw).strip() != "" else default
    except (ValueError, TypeError):
        val = default
    return max(min_val, min(max_val, val))


def _parse_float(raw: Optional[str], default: float, min_val: float, max_val: float) -> float:
    try:
        val = float(str(raw).strip()) if raw is not None and str(raw).strip() != "" else default
    except (ValueError, TypeError):
        val = default
    return max(min_val, min(max_val, val))


def _parse_bool(raw: Optional[str], default: bool) -> bool:
    if raw is None or str(raw).strip() == "":
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on", "auto"}


def _parse_strategies(raw: Optional[str], default_list: list[str]) -> list[str]:
    if raw is None or not str(raw).strip():
        return default_list
    items = [s.strip().upper() for s in str(raw).split(",") if s.strip()]
    valid = [s for s in items if s in STRATEGY_MIN_RR]
    return valid or default_list


def _parse_risk_profile(raw: Optional[str], default: str = "CONSERVATIVE") -> str:
    val = str(raw or "").strip().upper()
    if val in {"CONSERVATIVE", "MODERATE", "AGGRESSIVE"}:
        return val
    d = str(default or "CONSERVATIVE").strip().upper()
    return d if d in {"CONSERVATIVE", "MODERATE", "AGGRESSIVE"} else "CONSERVATIVE"


def _parse_pair_selection_mode(raw: Optional[str], default: str = "TOP_N") -> str:
    val = str(raw or "").strip().upper()
    if val in {"TOP_N", "CUSTOM"}:
        return val
    d = str(default or "TOP_N").strip().upper()
    return d if d in {"TOP_N", "CUSTOM"} else "TOP_N"


def parse_selected_pairs(raw: Optional[str | list[str]]) -> list[str]:
    """Normalize comma-separated or list pair symbols into deduplicated uppercase list."""
    if raw is None:
        return []
    items = raw if isinstance(raw, list) else str(raw).split(",")
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        sym = str(item or "").strip().upper()
        if sym and sym not in seen:
            seen.add(sym)
            result.append(sym)
    return result


def resolve_runtime_settings(db: Optional[Session] = None) -> dict[str, Any]:
    """Resolve all scanner, MEXC API, LLM runtime, and risk-guard settings from MySQL."""
    rows: dict[str, str] = {}
    if db is not None:
        db_rows = db.query(AppSetting).filter(AppSetting.key.in_(RUNTIME_SETTING_KEYS)).all()
        rows = {r.key: (r.value or "") for r in db_rows}

    auto_enabled = _parse_bool(rows.get("auto_scan_enabled"), settings.auto_start_scheduler)
    strategies: list[str]
    if db is not None:
        db_strats = db.query(Strategy).order_by(Strategy.id.asc()).all()
        if db_strats:
            strategies = [s.name for s in db_strats if s.is_active]
        else:
            strategies = _parse_strategies(rows.get("active_strategies"), settings.active_strategy_list)
    else:
        strategies = _parse_strategies(rows.get("active_strategies"), settings.active_strategy_list)
    mexc_base_url = (rows.get("mexc_base_url") or settings.mexc_base_url).strip().rstrip("/")
    mexc_proxy_url = (
        rows["mexc_proxy_url"].strip()
        if "mexc_proxy_url" in rows
        else settings.mexc_proxy_url.strip()
    )
    return {
        "llm_timeout_seconds": _parse_int(rows.get("llm_timeout_seconds"), settings.llm_timeout_seconds, 5, 300),
        "llm_max_concurrency": _parse_int(rows.get("llm_max_concurrency"), settings.llm_max_concurrency, 1, 20),
        "llm_max_tokens": _parse_int(rows.get("llm_max_tokens"), settings.llm_max_tokens, 512, 8192),
        "mexc_base_url": mexc_base_url,
        "mexc_proxy_url": mexc_proxy_url,
        "mexc_max_concurrency": _parse_int(rows.get("mexc_max_concurrency"), settings.mexc_max_concurrency, 1, 20),
        "auto_scan_enabled": auto_enabled,
        "scan_mode": "AUTO" if auto_enabled else "MANUAL",
        "pair_selection_mode": _parse_pair_selection_mode(
            rows.get("pair_selection_mode"), settings.pair_selection_mode
        ),
        "selected_pairs": parse_selected_pairs(
            rows.get("selected_pairs") if "selected_pairs" in rows else settings.selected_pairs
        ),
        "top_n_pairs": _parse_int(rows.get("top_n_pairs"), settings.top_n_pairs, 1, 100),
        "scan_interval_minutes": _parse_int(rows.get("scan_interval_minutes"), settings.scan_interval_minutes, 1, 1440),
        "tracker_interval_seconds": _parse_int(
            rows.get("tracker_interval_seconds"), settings.tracker_interval_seconds, 15, 3600
        ),
        "active_strategies": strategies,
        "min_24h_quote_volume": _parse_float(
            rows.get("min_24h_quote_volume"), settings.min_24h_quote_volume, 0.0, 1e13
        ),
        "max_24h_quote_volume": _parse_float(
            rows.get("max_24h_quote_volume"), settings.max_24h_quote_volume, 0.0, 1e13
        ),
        "min_atr_pct": _parse_float(rows.get("min_atr_pct"), settings.min_atr_pct, 0.0, 50.0),
        "max_atr_pct": _parse_float(rows.get("max_atr_pct"), settings.max_atr_pct, 0.1, 100.0),
        "min_confidence": _parse_int(rows.get("min_confidence"), settings.min_confidence, 0, 100),
        "risk_profile": _parse_risk_profile(rows.get("risk_profile"), settings.risk_profile),
    }
