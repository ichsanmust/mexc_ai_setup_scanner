"""End-to-end market scanning, AI evaluation, validation, and persistence pipeline."""

import asyncio
from datetime import timedelta
from decimal import Decimal
import inspect
import logging
from typing import Any, Optional

import httpx
from sqlalchemy.orm import Session

from ..ai.analyzer import (
    analyze_market_snapshot,
    load_strategy_prompts_map,
    resolve_active_llm_config,
)
from ..database import SessionLocal
from ..models import ScanEvaluation, ScanRun, TradeSetup, utcnow
from ..scanner.features import prefilter_and_build_snapshot
from ..scanner.mexc_public import MexcPublicClient
from .runtime_settings import resolve_runtime_settings
from .validator import validate_and_guard_setup

log = logging.getLogger(__name__)


def resolve_scanner_settings(db: Session) -> dict[str, Any]:
    """Backward-compatible wrapper returning runtime settings from MySQL."""
    return resolve_runtime_settings(db)


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

            settings_snapshot = {
                "scan_mode": rt_cfg["scan_mode"],
                "active_strategies": list(target_strategies),
                "top_n_pairs": effective_top_n,
                "htf_interval": rt_cfg["htf_interval"],
                "ltf_interval": rt_cfg["ltf_interval"],
                "kline_limit": rt_cfg["kline_limit"],
                "scan_interval_minutes": rt_cfg["scan_interval_minutes"],
                "tracker_interval_seconds": rt_cfg["tracker_interval_seconds"],
                "setup_expiry_hours": rt_cfg["setup_expiry_hours"],
                "min_24h_quote_volume": rt_cfg["min_24h_quote_volume"],
                "max_24h_quote_volume": rt_cfg["max_24h_quote_volume"],
                "min_atr_pct": rt_cfg["min_atr_pct"],
                "max_atr_pct": rt_cfg["max_atr_pct"],
                "min_confidence": rt_cfg["min_confidence"],
                "mexc_base_url": rt_cfg["mexc_base_url"],
                "llm_provider": llm_cfg["provider"],
                "llm_model": llm_cfg["model_id"],
                "llm_timeout_seconds": rt_cfg["llm_timeout_seconds"],
                "llm_max_concurrency": rt_cfg["llm_max_concurrency"],
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
    ) -> dict[str, Any]:
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

            # Fetch HTF + LTF candles concurrently
            async def fetch_pair_candles(pair: dict[str, Any]) -> dict[str, Any]:
                sym = pair["symbol"]
                htf_task = mexc.get_kline(
                    sym, interval=rt_cfg["htf_interval"], limit=rt_cfg["kline_limit"]
                )
                ltf_task = mexc.get_kline(
                    sym, interval=rt_cfg["ltf_interval"], limit=rt_cfg["kline_limit"]
                )
                htf, ltf = await asyncio.gather(htf_task, ltf_task)
                return {**pair, "htf": htf, "ltf": ltf}

            pair_results = await asyncio.gather(
                *(fetch_pair_candles(p) for p in top_pairs),
                return_exceptions=True,
            )

        snapshots: list[dict[str, Any]] = []
        for item in pair_results:
            if isinstance(item, Exception):
                log.warning("Failed fetching kline pair: %s", item)
                continue
            ok, reason, snap = prefilter_and_build_snapshot(
                symbol=item["symbol"],
                ticker=item["ticker"],
                htf_candles=item["htf"],
                ltf_candles=item["ltf"],
                min_atr_pct=rt_cfg["min_atr_pct"],
                max_atr_pct=rt_cfg["max_atr_pct"],
                htf_interval=rt_cfg["htf_interval"],
                ltf_interval=rt_cfg["ltf_interval"],
            )
            if ok and snap is not None:
                snapshots.append(snap)
            else:
                db.add(
                    ScanEvaluation(
                        scan_run_id=scan_run.id,
                        symbol=item["symbol"],
                        strategy_used="PREFILTER",
                        raw_decision="SKIPPED",
                        rejection_reason=reason[:255],
                        confidence=None,
                    )
                )

        scan_run.prefiltered_count = len(snapshots)
        db.commit()

        if not llm_cfg.get("api_key"):
            raise RuntimeError(
                f"LLM API key untuk provider '{llm_cfg['provider']}' kosong. Silakan atur di AI Models & Settings."
            )
        if not strategies:
            raise RuntimeError(
                "Tidak ada strategi aktif. Aktifkan minimal 1 strategi di menu Settings."
            )

        prompt_map = load_strategy_prompts_map(db, strategies)
        accepts_system_prompt = "system_prompt" in inspect.signature(analyze_market_snapshot).parameters

        llm_sem = asyncio.Semaphore(rt_cfg["llm_max_concurrency"])
        ai_tasks = []
        for snap in snapshots:
            for strat in strategies:
                ai_tasks.append((snap, strat))

        async def run_one_ai(snap: dict[str, Any], strat: str):
            async with llm_sem:
                try:
                    kwargs: dict[str, Any] = {
                        "snapshot": snap,
                        "strategy": strat,
                        "llm_config": llm_cfg,
                        "timeout_seconds": rt_cfg["llm_timeout_seconds"],
                    }
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
        expires_at = now + timedelta(hours=rt_cfg["setup_expiry_hours"])

        for snap, strat, decision, raw_resp, err in ai_results:
            if err is not None or decision is None:
                err_str = str(err) if err is not None else "Empty AI decision"
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
                expires_at=expires_at,
                features_snapshot=snap,
                ai_payload=normalized.model_dump(),
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
            "prefiltered_pairs": len(snapshots),
            "ai_analyzed": ai_analyzed_count,
            "ai_errors": len(ai_errors),
            "setups_created": setups_created,
            "warning": scan_run.error_message,
        }


scan_pipeline = ScanPipeline()
