"""End-to-end market scanning, AI evaluation, validation, and persistence pipeline."""

import asyncio
from datetime import timedelta
from decimal import Decimal
import hashlib
import inspect
import logging
import math
import time
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
from ..scanner.features import prefilter_and_build_snapshot, prescreen_for_strategy, summarize_timeframe
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
        self.current_run_id: Optional[int] = None
        self._active_task: Optional[asyncio.Task[Any]] = None
        self._cancel_requested: bool = False
        self.last_run_summary: Optional[dict[str, Any]] = None
        self.current_progress: Optional[dict[str, Any]] = None

    def request_stop(self, run_id: Optional[int] = None) -> bool:
        """Request cancellation of the currently running scan task."""
        if not self.is_running or self._active_task is None:
            return False
        if run_id is not None and self.current_run_id != run_id:
            return False
        self._cancel_requested = True
        self._active_task.cancel()
        return True

    def _set_progress(
        self,
        scan_run_id: int,
        stage: str,
        stage_label: str,
        percent: int,
        detail: str = "",
        done: int = 0,
        total: int = 0,
        current_symbol: Optional[str] = None,
    ) -> None:
        self.current_progress = {
            "scan_run_id": scan_run_id,
            "stage": stage,
            "stage_label": stage_label,
            "percent": max(0, min(100, int(percent))),
            "detail": detail,
            "done": done,
            "total": total,
            "current_symbol": current_symbol,
        }

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
            self._cancel_requested = False
            self._active_task = asyncio.current_task()
            db = SessionLocal()
            rt_cfg = resolve_runtime_settings(db)
            target_strategies = strategies or rt_cfg["active_strategies"]
            llm_cfg = resolve_active_llm_config(db)
            effective_top_n = top_n or rt_cfg["top_n_pairs"]
            strategy_profiles = _resolve_strategy_profiles(db, list(target_strategies))

            settings_snapshot = {
                "scan_mode": rt_cfg["scan_mode"],
                "pair_selection_mode": rt_cfg["pair_selection_mode"],
                "selected_pairs": list(rt_cfg["selected_pairs"]),
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
                "prescreen_enabled": bool(settings.prescreen_enabled),
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
            self.current_run_id = scan_run.id
            self._set_progress(
                scan_run.id,
                stage="FETCH_PAIRS",
                stage_label="Mengambil daftar pair MEXC",
                percent=5,
                detail="Menghubungi API publik MEXC Futures...",
            )

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
            except asyncio.CancelledError:
                log.warning("Scan cycle #%s cancelled.", scan_run.id)
                db.rollback()
                scan_run = db.get(ScanRun, scan_run.id) or scan_run
                scan_run.status = "CANCELLED"
                scan_run.error_message = "Scan dihentikan oleh user."
                scan_run.finished_at = utcnow()
                db.commit()
                summary = {
                    "scan_run_id": scan_run.id,
                    "status": "CANCELLED",
                    "error": None,
                }
                self.last_run_summary = summary
                if self._cancel_requested:
                    return summary
                raise
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
                db.rollback()
                scan_run = db.get(ScanRun, scan_run.id) or scan_run
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
                self.current_run_id = None
                self._active_task = None
                self._cancel_requested = False
                self.current_progress = None
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
        """Run one scan cycle as a streaming pipeline.

        Producers fetch klines and run prefilter + deterministic prescreen per pair; every
        surviving (snapshot, strategy) task is pushed to an asyncio.Queue immediately, and
        `llm_max_concurrency` AI workers consume it without waiting for the remaining pairs.
        """
        cycle_start = time.perf_counter()
        timings: dict[str, float] = {}
        warnings: list[str] = []

        if not llm_cfg.get("api_key"):
            raise RuntimeError(
                f"LLM API key untuk provider '{llm_cfg['provider']}' kosong. Silakan atur di AI Models & Settings."
            )
        if not strategies:
            raise RuntimeError("Tidak ada strategi aktif. Aktifkan minimal 1 strategi di menu Settings.")

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
        unique_intervals = list(interval_limits.items())

        invalid_custom: list[dict[str, str]] = []
        async with MexcPublicClient(
            base_url=rt_cfg["mexc_base_url"],
            proxy_url=rt_cfg["mexc_proxy_url"],
            max_concurrency=rt_cfg["mexc_max_concurrency"],
        ) as mexc:
            # ---- Stage 1: pair selection (TOP_N by volume, or CUSTOM manual list) ----
            t = time.perf_counter()
            if rt_cfg.get("pair_selection_mode") == "CUSTOM":
                selected_syms = rt_cfg.get("selected_pairs") or []
                if not selected_syms:
                    raise ValueError("Mode Custom Pairs aktif, tetapi belum ada pair yang dipilih di Settings.")
                total_contracts, top_pairs, invalid_custom = await mexc.get_selected_pairs(selected_syms)
                if invalid_custom:
                    names = ", ".join(i["symbol"] for i in invalid_custom)
                    warnings.append(f"Pair custom dilewati (tidak valid/tidak aktif): {names}")
                    log.warning("Custom pairs skipped on scan #%s: %s", scan_run.id, invalid_custom)
                if not top_pairs:
                    raise ValueError(
                        "Semua pair custom tidak valid atau tidak aktif di MEXC: "
                        + ", ".join(i["symbol"] for i in invalid_custom)
                    )
            else:
                get_top_kwargs: dict[str, Any] = {
                    "top_n": top_n,
                    "min_quote_volume": rt_cfg["min_24h_quote_volume"],
                }
                if "max_quote_volume" in inspect.signature(mexc.get_top_pairs).parameters:
                    get_top_kwargs["max_quote_volume"] = rt_cfg["max_24h_quote_volume"]
                total_contracts, top_pairs = await mexc.get_top_pairs(**get_top_kwargs)
            timings["fetch_pairs_s"] = round(time.perf_counter() - t, 3)

            scan_run.total_contracts = total_contracts
            scan_run.top_pairs_count = len(top_pairs)
            db.commit()

            # ---- Stage 2: BTC_USDT market context (fetched once, reused if BTC is also in top pairs) ----
            t = time.perf_counter()
            btc_candles_by_iv: dict[str, list[dict[str, Any]]] = {}
            btc_ticker: dict[str, Any] | None = None
            for pair in top_pairs:
                if pair.get("symbol") == "BTC_USDT":
                    btc_ticker = pair.get("ticker")
                    break
            self._set_progress(
                scan_run.id,
                stage="BTC_CONTEXT",
                stage_label="Menganalisis konteks BTC_USDT",
                percent=10,
                detail="Membaca struktur HTF/LTF BTC_USDT...",
            )
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
                except Exception as exc:
                    log.debug("Could not compute BTC Market Mover summary: %s", exc)
            timings["btc_context_s"] = round(time.perf_counter() - t, 3)

            # ---- Stage 3: streaming fetch -> prefilter -> prescreen -> AI ----
            total_pairs_n = len(top_pairs)
            queue: asyncio.Queue[Optional[tuple[dict[str, Any], str]]] = asyncio.Queue()
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
            accepts_client = "client" in ai_params

            kline_done = 0
            enqueued = 0
            ai_done = 0
            prefilter_cpu_s = 0.0
            save_cpu_s = 0.0
            prescreen_skipped = 0
            ai_analyzed_count = 0
            setups_created = 0
            uncommitted = 0
            ai_errors: list[str] = []
            passed_symbols: set[str] = set()
            snapshot_cache: dict[tuple[str, str, str], tuple[bool, str, dict[str, Any] | None]] = {}
            btc_context_cache: dict[tuple[str, str], dict[str, Any] | None] = {}
            commit_batch_size = 10
            self._set_progress(
                scan_run.id,
                stage="FETCH_KLINES",
                stage_label="Fetch klines, pre-filter & prescreen (streaming ke AI)",
                percent=12,
                detail=f"0/{total_pairs_n} pair",
                done=0,
                total=total_pairs_n,
            )

            def persist_ai_result(
                snap: dict[str, Any],
                strat: str,
                decision: Any,
                err: Optional[Exception],
            ) -> None:
                """Validate one AI result and stage it in the DB (sync, no awaits => safe on shared session)."""
                nonlocal ai_analyzed_count, setups_created, uncommitted
                sym = snap["symbol"]
                if err is not None or decision is None:
                    err_str = (str(err).strip() or type(err).__name__) if err is not None else "Empty AI decision"
                    ai_errors.append(f"{sym} ({strat}): {err_str}")
                    db.add(
                        ScanEvaluation(
                            scan_run_id=scan_run.id,
                            symbol=sym,
                            strategy_used=strat,
                            raw_decision="ERROR",
                            rejection_reason=err_str[:255],
                            confidence=None,
                        )
                    )
                else:
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
                                symbol=sym,
                                strategy_used=strat,
                                raw_decision=decision.decision,
                                rejection_reason=reason[:255],
                                confidence=decision.confidence,
                            )
                        )
                    else:
                        now = utcnow()
                        strat_expiry_hours = profiles.get(strat, {}).get("expiry_hours", settings.setup_expiry_hours)
                        db.add(
                            TradeSetup(
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
                        )
                        # Flush so the duplicate/conflict guard sees this setup for later results.
                        db.flush()
                        setups_created += 1

                uncommitted += 1
                if uncommitted >= commit_batch_size:
                    db.commit()
                    uncommitted = 0

            async def run_one_ai(snap: dict[str, Any], strat: str) -> None:
                nonlocal ai_done, save_cpu_s
                try:
                    kwargs: dict[str, Any] = {
                        "snapshot": snap,
                        "strategy": strat,
                        "llm_config": llm_cfg,
                        "timeout_seconds": rt_cfg["llm_timeout_seconds"],
                    }
                    if accepts_client:
                        kwargs["client"] = llm_client
                    if accepts_max_tokens:
                        kwargs["max_tokens"] = rt_cfg["llm_max_tokens"]
                    if accepts_min_conf:
                        kwargs["min_confidence"] = rt_cfg["min_confidence"]
                    if accepts_risk_profile:
                        kwargs["risk_profile"] = rt_cfg["risk_profile"]
                    if accepts_system_prompt:
                        kwargs["system_prompt"] = prompt_map.get(strat.strip().upper())
                    decision, _raw_resp = await analyze_market_snapshot(**kwargs)
                    ai_exc: Optional[Exception] = None
                except Exception as exc:
                    decision, ai_exc = None, exc

                t_save0 = time.perf_counter()
                try:
                    persist_ai_result(snap, strat, decision, ai_exc)
                except Exception as exc:
                    # A DB/validation failure on one result must not kill the worker or lose other results.
                    log.exception("Failed persisting AI result %s (%s): %s", snap.get("symbol"), strat, exc)
                    db.rollback()
                    ai_errors.append(f"{snap.get('symbol')} ({strat}): gagal menyimpan hasil: {exc}")
                finally:
                    save_cpu_s += time.perf_counter() - t_save0
                    ai_done += 1
                    pct = 50 + int((ai_done / max(1, enqueued)) * 42) if enqueued else 50
                    self._set_progress(
                        scan_run.id,
                        stage="AI_ANALYSIS",
                        stage_label="Analisis setup oleh AI",
                        percent=min(92, pct),
                        detail=f"{ai_done}/{enqueued} selesai ({snap.get('symbol')} • {strat})",
                        done=ai_done,
                        total=enqueued,
                        current_symbol=snap.get("symbol"),
                    )

            async def ai_worker() -> None:
                while True:
                    item = await queue.get()
                    try:
                        if item is None:
                            return
                        await run_one_ai(*item)
                    finally:
                        queue.task_done()

            async def fetch_and_screen_pair(pair: dict[str, Any]) -> None:
                nonlocal kline_done, enqueued, prefilter_cpu_s, prescreen_skipped
                sym = pair["symbol"]
                try:
                    if sym == "BTC_USDT" and btc_candles_by_iv:
                        candles_by_iv = btc_candles_by_iv
                    else:
                        fetched = await asyncio.gather(
                            *(mexc.get_kline(sym, interval=iv, limit=lim) for iv, lim in unique_intervals)
                        )
                        candles_by_iv = {iv: c for (iv, _), c in zip(unique_intervals, fetched)}
                except Exception as exc:
                    log.warning("Failed fetching kline pair %s: %s", sym, exc)
                    kline_done += 1
                    return

                kline_done += 1
                self._set_progress(
                    scan_run.id,
                    stage="FETCH_KLINES",
                    stage_label="Fetch klines, pre-filter & prescreen (streaming ke AI)",
                    percent=12 + int((kline_done / max(1, total_pairs_n)) * 30),
                    detail=f"{kline_done}/{total_pairs_n} pair ({sym}) • antre AI: {enqueued}",
                    done=kline_done,
                    total=total_pairs_n,
                    current_symbol=sym,
                )

                t0 = time.perf_counter()
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
                            ticker=pair["ticker"],
                            htf_candles=candles_by_iv.get(prof["htf"], []),
                            ltf_candles=candles_by_iv.get(prof["ltf"], []),
                            min_atr_pct=eff_min_atr,
                            max_atr_pct=eff_max_atr,
                            htf_interval=prof["htf"],
                            ltf_interval=prof["ltf"],
                            contract=pair.get("contract"),
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
                    if not ok or snap is None:
                        continue
                    passed_symbols.add(sym)

                    if settings.prescreen_enabled:
                        pass_ps, ps_reason = prescreen_for_strategy(
                            strat, snap["htf_1h"], snap["ltf_15m"], rt_cfg["risk_profile"]
                        )
                        if not pass_ps:
                            prescreen_skipped += 1
                            db.add(
                                ScanEvaluation(
                                    scan_run_id=scan_run.id,
                                    symbol=sym,
                                    strategy_used=strat,
                                    raw_decision="SKIPPED",
                                    rejection_reason=f"[PRESCREEN] {ps_reason}"[:255],
                                    confidence=None,
                                )
                            )
                            continue

                    enqueued += 1
                    queue.put_nowait((snap, strat))
                prefilter_cpu_s += time.perf_counter() - t0

            n_workers = max(1, int(rt_cfg["llm_max_concurrency"]))
            t_stream = time.perf_counter()
            eff_timeout = rt_cfg["llm_timeout_seconds"]
            async with httpx.AsyncClient(timeout=httpx.Timeout(eff_timeout)) as llm_client:
                workers = [asyncio.create_task(ai_worker()) for _ in range(n_workers)]
                producer_results = await asyncio.gather(
                    *(fetch_and_screen_pair(p) for p in top_pairs),
                    return_exceptions=True,
                )
                for res in producer_results:
                    if isinstance(res, Exception):
                        log.warning("Pair producer error: %s", res)
                t_producers_done = time.perf_counter()
                timings["fetch_prefilter_s"] = round(t_producers_done - t_stream, 3)

                for _ in workers:
                    queue.put_nowait(None)
                await asyncio.gather(*workers)
                
            # Final commit for remaining buffered items
            db.commit()
            
            # Time AI kept running after the last pair was fetched (the non-overlapped tail)
            timings["ai_tail_s"] = round(time.perf_counter() - t_producers_done, 3)
            timings["stream_total_s"] = round(time.perf_counter() - t_stream, 3)
            timings["prefilter_cpu_s"] = round(prefilter_cpu_s, 3)
            timings["save_s"] = round(save_cpu_s, 3)
            timings["save_cpu_s"] = round(save_cpu_s, 3)
            timings["ai_workers"] = n_workers

        if enqueued == 0 and not passed_symbols:
            log.info("Scan #%s: no pair passed prefilter", scan_run.id)

        # ---- Stage 4: results were validated & persisted incrementally by the AI workers ----
        self._set_progress(
            scan_run.id,
            stage="SAVING",
            stage_label="Finalisasi hasil scan",
            percent=95,
            detail=f"{ai_analyzed_count} hasil AI tersimpan, {setups_created} setup dibuat",
        )

        timings["total_s"] = round(time.perf_counter() - cycle_start, 3)
        log.info("Scan #%s stage timings: %s", scan_run.id, timings)

        scan_run.ai_analyzed_count = ai_analyzed_count
        scan_run.setups_created_count = setups_created
        if enqueued and ai_analyzed_count == 0 and ai_errors:
            raise RuntimeError(f"Semua panggilan AI gagal ({len(ai_errors)}/{enqueued}). Contoh: {ai_errors[0]}")
        if ai_errors:
            warnings.append(f"Sebagian AI gagal ({len(ai_errors)}/{enqueued}): {ai_errors[0]}")
        scan_run.error_message = " | ".join(warnings)[:2000] if warnings else None

        snap_copy = dict(scan_run.settings_snapshot or {})
        snap_copy["stage_timings"] = timings
        snap_copy["prescreen_skipped"] = prescreen_skipped
        snap_copy["invalid_custom_pairs"] = invalid_custom
        scan_run.settings_snapshot = snap_copy
        db.commit()

        return {
            "scan_run_id": scan_run.id,
            "status": "COMPLETED",
            "llm_provider": llm_cfg["provider"],
            "llm_model": llm_cfg["model_id"],
            "total_contracts": total_contracts,
            "top_pairs": len(top_pairs),
            "prefiltered_pairs": len(passed_symbols),
            "prescreen_skipped": prescreen_skipped,
            "ai_analyzed": ai_analyzed_count,
            "ai_errors": len(ai_errors),
            "setups_created": setups_created,
            "invalid_custom_pairs": [i["symbol"] for i in invalid_custom],
            "stage_timings": timings,
            "warning": scan_run.error_message,
            "btc_market_mover": btc_market_mover_summary,
        }


scan_pipeline = ScanPipeline()
