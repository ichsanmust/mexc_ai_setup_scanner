"""End-to-end market scanning, AI evaluation, validation, and persistence pipeline."""

import asyncio
from datetime import timedelta
from decimal import Decimal
import hashlib
import inspect
import logging
import math
from typing import Any, Optional

import httpx
from sqlalchemy.orm import Session

from ..ai.analyzer import (
    ANALYZER_PROMPT_VERSION,
    analyze_market_snapshot,
    load_strategy_prompts_map,
    resolve_active_llm_config,
)
from ..config import settings
from ..database import SessionLocal
from ..models import ScanEvaluation, ScanRun, Strategy, TradeSetup, utcnow
from ..scanner.features import prefilter_and_build_snapshot, summarize_timeframe
from ..scanner.mexc_public import INTERVAL_SECONDS_MAP, MexcPublicClient
from .market_mover import analyze_btc_market_mover, build_btc_strategy_advisor
from .runtime_settings import resolve_runtime_settings
from .validator import validate_and_guard_setup

log = logging.getLogger(__name__)


def _resolve_strategy_profiles(
    db: Session,
    strategies: list[str],
) -> dict[str, dict[str, Any]]:
    """Resolve effective HTF/LTF/kline_limit/expiry_hours per active strategy.

    Every active strategy uses its own suggested_htf/suggested_ltf/suggested_kline_limit/
    suggested_expiry_hours from the strategies table (falling back to code defaults only if null).
    """
    rows = db.query(Strategy).filter(Strategy.name.in_([s.strip().upper() for s in strategies])).all()
    rows_by_name = {r.name.strip().upper(): r for r in rows}

    profiles: dict[str, dict[str, Any]] = {}
    for strat in strategies:
        key = strat.strip().upper()
        row = rows_by_name.get(key)
        profiles[strat] = {
            "htf": (row.suggested_htf if row and row.suggested_htf else settings.htf_interval),
            "ltf": (row.suggested_ltf if row and row.suggested_ltf else settings.ltf_interval),
            "kline_limit": int(
                row.suggested_kline_limit if row and row.suggested_kline_limit else settings.kline_limit
            ),
            "expiry_hours": int(
                row.suggested_expiry_hours if row and row.suggested_expiry_hours else settings.setup_expiry_hours
            ),
        }
    return profiles


def resolve_scanner_settings(db: Session) -> dict[str, Any]:
    """Backward-compatible wrapper returning runtime settings from MySQL."""
    return resolve_runtime_settings(db)


def _summarize_btc_tf(candles: list[dict[str, Any]], interval: str) -> dict[str, Any] | None:
    """Compact BTC market context summary for a single timeframe."""
    if len(candles) < 30:
        return None
    s = summarize_timeframe(candles, interval)
    return {
        "interval": s["interval"],
        "close": s["close"],
        "ema_bias": s["ema_bias"],
        "ema21_slope_pct": s["ema21_slope_pct"],
        "rsi14": s["rsi14"],
        "structure_bias": s["structure_bias"],
    }


def _scale_atr_bounds(min_atr_pct: float, max_atr_pct: float, ltf_interval: str) -> tuple[float, float]:
    """Scale Min15-baseline ATR% bounds to the strategy's actual LTF interval via sqrt(time)."""
    ltf_sec = INTERVAL_SECONDS_MAP.get(ltf_interval, 900)
    scale = math.sqrt(max(60, ltf_sec) / 900.0)
    return round(min_atr_pct * scale, 4), round(max_atr_pct * scale, 4)


class ScanPipeline:
    """Thread/async-safe orchestrator for scanning MEXC Futures setups."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self.is_running: bool = False
        self.last_run_summary: Optional[dict[str, Any]] = None

    async def run_once(
        self,
        strategies: Optional[list[str]] = None,
        top_n: Optional[int] = None,
    ) -> dict[str, Any]:
        """Execute a complete scan cycle safely under an async lock."""
        if self._lock.locked():
            return {"status": "SKIPPED", "message": "Scan is already in progress"}

        async with self._lock:
            self.is_running = True
            db = SessionLocal()
            rt_cfg = resolve_runtime_settings(db)
            target_strategies = strategies or rt_cfg["active_strategies"]
            llm_cfg = resolve_active_llm_config(db)
            effective_top_n = top_n or rt_cfg["top_n_pairs"]
            strategy_profiles = _resolve_strategy_profiles(db, list(target_strategies))

            settings_snapshot = {
                "scan_mode": rt_cfg["scan_mode"],
                "active_strategies": list(target_strategies),
                "strategy_timeframes": strategy_profiles,
                "top_n_pairs": effective_top_n,
                "scan_interval_minutes": rt_cfg["scan_interval_minutes"],
                "tracker_interval_seconds": rt_cfg["tracker_interval_seconds"],
                "min_24h_quote_volume": rt_cfg["min_24h_quote_volume"],
                "max_24h_quote_volume": rt_cfg["max_24h_quote_volume"],
                "min_atr_pct": rt_cfg["min_atr_pct"],
                "max_atr_pct": rt_cfg["max_atr_pct"],
                "min_confidence": rt_cfg["min_confidence"],
                "risk_profile": rt_cfg["risk_profile"],
                "mexc_base_url": rt_cfg["mexc_base_url"],
                "llm_provider": llm_cfg["provider"],
                "llm_model": llm_cfg["model_id"],
                "llm_timeout_seconds": rt_cfg["llm_timeout_seconds"],
                "llm_max_concurrency": rt_cfg["llm_max_concurrency"],
                "llm_max_tokens": rt_cfg["llm_max_tokens"],
            }

            scan_run = ScanRun(
                strategy=",".join(target_strategies)[:80],
                llm_provider=llm_cfg["provider"],
                llm_model=llm_cfg["model_id"],
                settings_snapshot=settings_snapshot,
                status="RUNNING",
                started_at=utcnow(),
            )
            db.add(scan_run)
            db.commit()
            db.refresh(scan_run)

            try:
                summary = await self._execute_cycle(
                    db=db,
                    scan_run=scan_run,
                    strategies=target_strategies,
                    top_n=effective_top_n,
                    llm_cfg=llm_cfg,
                    rt_cfg=rt_cfg,
                    strategy_profiles=strategy_profiles,
                )
                scan_run.status = "COMPLETED"
                scan_run.finished_at = utcnow()
                db.commit()
                self.last_run_summary = summary
                return summary
            except httpx.ConnectError as exc:
                msg = (
                    f"Koneksi ke MEXC ({rt_cfg['mexc_base_url']}) gagal: {exc}. "
                    "Pastikan jaringan/VPN dapat mengakses endpoint MEXC atau atur MEXC Proxy URL di Settings."
                )
                log.error("Scan cycle #%s failed: %s", scan_run.id, msg)
                scan_run.status = "FAILED"
                scan_run.error_message = msg[:2000]
                scan_run.finished_at = utcnow()
                db.commit()
                summary = {
                    "scan_run_id": scan_run.id,
                    "status": "FAILED",
                    "error": msg,
                }
                self.last_run_summary = summary
                return summary
            except Exception as exc:
                log.exception("Scan cycle #%s failed: %s", scan_run.id, exc)
                scan_run.status = "FAILED"
                scan_run.error_message = str(exc)[:2000]
                scan_run.finished_at = utcnow()
                db.commit()
                summary = {
                    "scan_run_id": scan_run.id,
                    "status": "FAILED",
                    "error": str(exc),
                }
                self.last_run_summary = summary
                return summary
            finally:
                self.is_running = False
                db.close()

    async def _execute_cycle(
        self,
        db: Session,
        scan_run: ScanRun,
        strategies: list[str],
        top_n: int,
        llm_cfg: dict[str, str],
        rt_cfg: dict[str, Any],
        strategy_profiles: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        profiles = strategy_profiles or _resolve_strategy_profiles(db, strategies)

        # Deduplicate required kline intervals (with max needed kline_limit) across active strategies
        interval_limits: dict[str, int] = {}
        for strat in strategies:
            prof = profiles.get(strat) or {
                "htf": settings.htf_interval,
                "ltf": settings.ltf_interval,
                "kline_limit": settings.kline_limit,
            }
            for iv in (prof["htf"], prof["ltf"]):
                interval_limits[iv] = max(interval_limits.get(iv, 0), int(prof["kline_limit"]))

        async with MexcPublicClient(
            base_url=rt_cfg["mexc_base_url"],
            proxy_url=rt_cfg["mexc_proxy_url"],
            max_concurrency=rt_cfg["mexc_max_concurrency"],
        ) as mexc:
            get_top_kwargs: dict[str, Any] = {
                "top_n": top_n,
                "min_quote_volume": rt_cfg["min_24h_quote_volume"],
            }
            if "max_quote_volume" in inspect.signature(mexc.get_top_pairs).parameters:
                get_top_kwargs["max_quote_volume"] = rt_cfg["max_24h_quote_volume"]
            total_contracts, top_pairs = await mexc.get_top_pairs(**get_top_kwargs)
            scan_run.total_contracts = total_contracts
            scan_run.top_pairs_count = len(top_pairs)
            db.commit()

            # Fetch unique interval klines concurrently per pair (zero duplicate MEXC requests)
            unique_intervals = list(interval_limits.items())

            async def fetch_pair_candles(pair: dict[str, Any]) -> dict[str, Any]:
                sym = pair["symbol"]
                fetched = await asyncio.gather(
                    *(mexc.get_kline(sym, interval=iv, limit=lim) for iv, lim in unique_intervals)
                )
                candles_by_iv = {iv: candles for (iv, _), candles in zip(unique_intervals, fetched)}
                return {**pair, "candles_by_iv": candles_by_iv}

            pair_results = await asyncio.gather(
                *(fetch_pair_candles(p) for p in top_pairs),
                return_exceptions=True,
            )

            # Ensure BTC_USDT candles are available for global market_context (reuse if already in top_pairs)
            btc_candles_by_iv: dict[str, list[dict[str, Any]]] = {}
            btc_ticker: dict[str, Any] | None = None
            for item in pair_results:
                if not isinstance(item, Exception) and item.get("symbol") == "BTC_USDT":
                    btc_candles_by_iv = item.get("candles_by_iv") or {}
                    btc_ticker = item.get("ticker")
                    break
            if not btc_candles_by_iv and top_pairs:
                try:
                    btc_fetched = await asyncio.gather(
                        *(mexc.get_kline("BTC_USDT", interval=iv, limit=lim) for iv, lim in unique_intervals)
                    )
                    btc_candles_by_iv = {iv: candles for (iv, _), candles in zip(unique_intervals, btc_fetched)}
                except Exception as exc:
                    log.debug("Could not fetch BTC_USDT context klines: %s", exc)

            btc_market_mover_summary: dict[str, Any] | None = None
            if btc_candles_by_iv:
                try:
                    btc_analysis = analyze_btc_market_mover(btc_candles_by_iv, ticker=btc_ticker)
                    db_strats = db.query(Strategy).order_by(Strategy.id.asc()).all()
                    btc_advisor = build_btc_strategy_advisor(btc_analysis, rt_cfg, db_strats)
                    btc_market_mover_summary = {
                        "last_price": btc_analysis.get("last_price"),
                        "change_24h_pct": btc_analysis.get("change_24h_pct"),
                        "overall_regime": btc_analysis.get("overall_regime"),
                        "overall_bias": btc_analysis.get("overall_bias"),
                        "volatility_state": btc_analysis.get("volatility_state"),
                        "alignment": btc_advisor.get("alignment"),
                        "current_conclusion": btc_advisor.get("current_summary", {}).get("conclusion"),
                        "suggested_strategies": btc_advisor.get("suggested_settings", {}).get("active_strategies"),
                        "suggested_risk_profile": btc_advisor.get("suggested_settings", {}).get("risk_profile"),
                        "suggested_styles": btc_advisor.get("suggested_settings", {}).get("recommended_styles"),
                        "headline": btc_advisor.get("suggested_settings", {}).get("headline"),
                    }
                    snap_copy = dict(scan_run.settings_snapshot or {})
                    snap_copy["btc_market_mover"] = btc_market_mover_summary
                    scan_run.settings_snapshot = snap_copy
                    db.commit()
                except Exception as exc:
                    log.debug("Could not compute BTC Market Mover summary: %s", exc)

        if not llm_cfg.get("api_key"):
            raise RuntimeError(
                f"LLM API key untuk provider '{llm_cfg['provider']}' kosong. Silakan atur di AI Models & Settings."
            )
        if not strategies:
            raise RuntimeError(
                "Tidak ada strategi aktif. Aktifkan minimal 1 strategi di menu Settings."
            )

        # Build & cache multi-timeframe snapshots per (symbol, htf, ltf)
        snapshot_cache: dict[tuple[str, str, str], tuple[bool, str, dict[str, Any] | None]] = {}
        btc_context_cache: dict[tuple[str, str], dict[str, Any] | None] = {}
        passed_symbols: set[str] = set()
        ai_tasks: list[tuple[dict[str, Any], str]] = []

        for item in pair_results:
            if isinstance(item, Exception):
                log.warning("Failed fetching kline pair: %s", item)
                continue
            sym = item["symbol"]
            candles_by_iv = item["candles_by_iv"]
            for strat in strategies:
                prof = profiles[strat]
                tf_key = (prof["htf"], prof["ltf"])
                if tf_key not in btc_context_cache:
                    btc_htf = _summarize_btc_tf(btc_candles_by_iv.get(prof["htf"], []), prof["htf"])
                    btc_ltf = _summarize_btc_tf(btc_candles_by_iv.get(prof["ltf"], []), prof["ltf"])
                    btc_context_cache[tf_key] = (
                        {"btc": {"htf": btc_htf, "ltf": btc_ltf}} if (btc_htf or btc_ltf) else None
                    )
                cache_key = (sym, prof["htf"], prof["ltf"])
                if cache_key not in snapshot_cache:
                    eff_min_atr, eff_max_atr = _scale_atr_bounds(
                        rt_cfg["min_atr_pct"], rt_cfg["max_atr_pct"], prof["ltf"]
                    )
                    ok, reason, snap = prefilter_and_build_snapshot(
                        symbol=sym,
                        ticker=item["ticker"],
                        htf_candles=candles_by_iv[prof["htf"]],
                        ltf_candles=candles_by_iv[prof["ltf"]],
                        min_atr_pct=eff_min_atr,
                        max_atr_pct=eff_max_atr,
                        htf_interval=prof["htf"],
                        ltf_interval=prof["ltf"],
                        contract=item.get("contract"),
                        market_context=btc_context_cache[tf_key],
                    )
                    snapshot_cache[cache_key] = (ok, reason, snap)
                    if not ok:
                        db.add(
                            ScanEvaluation(
                                scan_run_id=scan_run.id,
                                symbol=sym,
                                strategy_used="PREFILTER",
                                raw_decision="SKIPPED",
                                rejection_reason=f"[{prof['htf']}/{prof['ltf']}] {reason}"[:255],
                                confidence=None,
                            )
                        )
                ok, _, snap = snapshot_cache[cache_key]
                if ok and snap is not None:
                    passed_symbols.add(sym)
                    ai_tasks.append((snap, strat))

        scan_run.prefiltered_count = len(passed_symbols)
        db.commit()

        prompt_map = load_strategy_prompts_map(db, strategies)
        prompt_versions = {
            k: hashlib.sha256(f"{v}\n::{ANALYZER_PROMPT_VERSION}".encode("utf-8")).hexdigest()[:8]
            for k, v in prompt_map.items()
        }
        ai_params = inspect.signature(analyze_market_snapshot).parameters
        accepts_system_prompt = "system_prompt" in ai_params
        accepts_max_tokens = "max_tokens" in ai_params
        accepts_min_conf = "min_confidence" in ai_params
        accepts_risk_profile = "risk_profile" in ai_params

        llm_sem = asyncio.Semaphore(rt_cfg["llm_max_concurrency"])

        async def run_one_ai(snap: dict[str, Any], strat: str):
            async with llm_sem:
                try:
                    kwargs: dict[str, Any] = {
                        "snapshot": snap,
                        "strategy": strat,
                        "llm_config": llm_cfg,
                        "timeout_seconds": rt_cfg["llm_timeout_seconds"],
                    }
                    if accepts_max_tokens:
                        kwargs["max_tokens"] = rt_cfg["llm_max_tokens"]
                    if accepts_min_conf:
                        kwargs["min_confidence"] = rt_cfg["min_confidence"]
                    if accepts_risk_profile:
                        kwargs["risk_profile"] = rt_cfg["risk_profile"]
                    if accepts_system_prompt:
                        kwargs["system_prompt"] = prompt_map.get(strat.strip().upper())
                    decision, raw_resp = await analyze_market_snapshot(**kwargs)
                    return snap, strat, decision, raw_resp, None
                except Exception as exc:
                    return snap, strat, None, None, exc

        ai_results = await asyncio.gather(*(run_one_ai(s, st) for s, st in ai_tasks))

        ai_analyzed_count = 0
        setups_created = 0
        ai_errors: list[str] = []
        now = utcnow()

        for snap, strat, decision, raw_resp, err in ai_results:
            if err is not None or decision is None:
                err_str = (str(err).strip() or type(err).__name__) if err is not None else "Empty AI decision"
                ai_errors.append(f"{snap['symbol']} ({strat}): {err_str}")
                db.add(
                    ScanEvaluation(
                        scan_run_id=scan_run.id,
                        symbol=snap["symbol"],
                        strategy_used=strat,
                        raw_decision="ERROR",
                        rejection_reason=err_str[:255],
                        confidence=None,
                    )
                )
                continue

            ai_analyzed_count += 1
            is_valid, normalized, reason = validate_and_guard_setup(
                decision,
                db=db,
                min_confidence=rt_cfg["min_confidence"],
                snapshot=snap,
                risk_profile=rt_cfg["risk_profile"],
            )

            if not is_valid:
                db.add(
                    ScanEvaluation(
                        scan_run_id=scan_run.id,
                        symbol=snap["symbol"],
                        strategy_used=strat,
                        raw_decision=decision.decision,
                        rejection_reason=reason[:255],
                        confidence=decision.confidence,
                    )
                )
                continue

            strat_expiry_hours = profiles.get(strat, {}).get("expiry_hours", settings.setup_expiry_hours)
            setup = TradeSetup(
                scan_run_id=scan_run.id,
                symbol=normalized.symbol,
                strategy_used=normalized.strategy_used,
                decision=normalized.decision,
                market_regime=normalized.market_regime,
                entry_type=normalized.entry_type,
                entry_price=Decimal(f"{normalized.entry_price:.8f}"),
                stop_loss=Decimal(f"{normalized.stop_loss:.8f}"),
                take_profit=Decimal(f"{normalized.take_profit:.8f}"),
                risk_reward_ratio=Decimal(f"{normalized.risk_reward_ratio:.4f}"),
                confidence=normalized.confidence,
                llm_provider=llm_cfg["provider"],
                llm_model=llm_cfg["model_id"],
                invalidation_reason=normalized.invalidation_reason,
                rationale=normalized.rationale,
                status="OPEN",
                status_history=[
                    {
                        "at": now.isoformat(),
                        "event": "CREATED",
                        "status": "OPEN",
                        "price": float(normalized.entry_price),
                        "stop_loss": float(normalized.stop_loss),
                        "take_profit": float(normalized.take_profit),
                        "note": (
                            f"Setup dibuat oleh sistem (AI {normalized.entry_type}) — "
                            f"Entry: {float(normalized.entry_price):g}, "
                            f"SL: {float(normalized.stop_loss):g}, "
                            f"TP: {float(normalized.take_profit):g}"
                        ),
                    }
                ],
                expires_at=now + timedelta(hours=int(strat_expiry_hours)),
                features_snapshot=snap,
                ai_payload={
                    **normalized.model_dump(),
                    "prompt_version": prompt_versions.get(strat.strip().upper()),
                },
            )
            db.add(setup)
            db.flush()
            setups_created += 1

        scan_run.ai_analyzed_count = ai_analyzed_count
        scan_run.setups_created_count = setups_created
        if ai_tasks and ai_analyzed_count == 0 and ai_errors:
            raise RuntimeError(f"Semua panggilan AI gagal ({len(ai_errors)}/{len(ai_tasks)}). Contoh: {ai_errors[0]}")
        if ai_errors:
            scan_run.error_message = f"Sebagian AI gagal ({len(ai_errors)}/{len(ai_tasks)}): {ai_errors[0]}"[:2000]
        db.commit()

        return {
            "scan_run_id": scan_run.id,
            "status": "COMPLETED",
            "llm_provider": llm_cfg["provider"],
            "llm_model": llm_cfg["model_id"],
            "total_contracts": total_contracts,
            "top_pairs": len(top_pairs),
            "prefiltered_pairs": len(passed_symbols),
            "ai_analyzed": ai_analyzed_count,
            "ai_errors": len(ai_errors),
            "setups_created": setups_created,
            "warning": scan_run.error_message,
            "btc_market_mover": btc_market_mover_summary,
        }


scan_pipeline = ScanPipeline()
