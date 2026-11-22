"""FastAPI dashboard application, REST APIs, and background scheduler lifespan."""

import asyncio
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timedelta
from decimal import Decimal
import logging
import time
from typing import Optional

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import httpx
from sqlalchemy import desc, inspect, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, joinedload

from ..ai.analyzer import resolve_active_llm_config, test_llm_connection
from ..config import (
    DEFAULT_COMMANDCODE_BASE_URL,
    DEFAULT_OPENROUTER_BASE_URL,
    FRONTEND_DIR,
    STRATEGY_MIN_RR,
    settings,
)
from ..core.pipeline import scan_pipeline
from ..core.runtime_settings import resolve_runtime_settings
from ..core.tracker import check_open_setups, ensure_created_history
from ..database import Base, SessionLocal, engine, get_db
from ..models import AIModel, AppSetting, ScanEvaluation, ScanRun, Strategy, TradeSetup, utcnow
from ..scanner.features import compute_indicators_df
from ..scanner.mexc_public import MexcPublicClient
from ..schemas import (
    AIModelCreate,
    AIModelOut,
    AIModelUpdate,
    AISettingsOut,
    AISettingsUpdate,
    AITestRequest,
    AITestResponse,
    AnalyticsSummaryResponse,
    CandlePoint,
    ChartDataResponse,
    EMAPoint,
    ScanEvaluationOut,
    ScannerSettingsOut,
    ScannerSettingsUpdate,
    ScanRunEvaluationsResponse,
    ScanRunListResponse,
    ScanRunOut,
    ScanTriggerRequest,
    SetupListResponse,
    SetupOut,
    SetupStatusUpdate,
    StrategyAnalyticsItem,
    StrategyCreate,
    StrategyOut,
    StrategyUpdate,
)
from ..seed import seed_all

log = logging.getLogger(__name__)


def _mask_api_key(key: str | None) -> str:
    """Mask sensitive API key for safe display in responses."""
    if not key:
        return ""
    clean = key.strip()
    if not clean:
        return ""
    if len(clean) <= 10:
        return "•" * len(clean)
    return f"{clean[:8]}••••••••{clean[-4:]}"


def _upsert_setting(db: Session, key: str, value: str, description: str | None = None) -> None:
    row = db.query(AppSetting).filter(AppSetting.key == key).first()
    if row:
        row.value = value
    else:
        db.add(AppSetting(key=key, value=value, description=description))


def _build_ai_settings_out(db: Session) -> AISettingsOut:
    rows = {r.key: (r.value or "") for r in db.query(AppSetting).all()}
    resolved = resolve_active_llm_config(db)

    cmd_url = rows.get("commandcode_base_url") or DEFAULT_COMMANDCODE_BASE_URL
    cmd_key = rows.get("commandcode_api_key") or ""
    or_url = rows.get("openrouter_base_url") or DEFAULT_OPENROUTER_BASE_URL
    or_key = rows.get("openrouter_api_key") or ""
    custom_url = rows.get("custom_llm_base_url") or ""
    custom_key = rows.get("custom_llm_api_key") or ""

    return AISettingsOut(
        active_provider=resolved["provider"],
        active_model_id=resolved["model_id"],
        active_model_name=resolved["model_name"],
        active_base_url=resolved["base_url"],
        commandcode_base_url=cmd_url,
        commandcode_api_key_masked=_mask_api_key(cmd_key),
        has_commandcode_api_key=bool(cmd_key.strip()),
        openrouter_base_url=or_url,
        openrouter_api_key_masked=_mask_api_key(or_key),
        has_openrouter_api_key=bool(or_key.strip()),
        custom_llm_base_url=custom_url,
        custom_llm_api_key_masked=_mask_api_key(custom_key),
        has_custom_llm_api_key=bool(custom_key.strip()),
    )


def _build_strategy_map(db: Session) -> dict[str, Strategy]:
    """Return active/inactive strategies keyed by uppercase name for metadata enrichment."""
    return {r.name.strip().upper(): r for r in db.query(Strategy).all()}


def _setup_to_out(
    row: TradeSetup,
    live_price: float | None = None,
    strategy_map: dict[str, Strategy] | None = None,
    db: Session | None = None,
) -> SetupOut:
    strat_key = (row.strategy_used or "").strip().upper()
    strat_row = strategy_map.get(strat_key) if strategy_map is not None else None
    if strat_row is None and db is not None and strat_key:
        strat_row = db.query(Strategy).filter(Strategy.name == strat_key).first()

    scan_run = row.scan_run
    scan_cfg = (
        scan_run.settings_snapshot
        if (scan_run is not None and isinstance(scan_run.settings_snapshot, dict))
        else None
    )
    tf_map = scan_cfg.get("strategy_timeframes") if isinstance(scan_cfg, dict) else None
    run_strat_prof = None
    if isinstance(tf_map, dict):
        run_strat_prof = tf_map.get(row.strategy_used) or tf_map.get(strat_key)
        if run_strat_prof is None:
            for k, v in tf_map.items():
                if str(k).strip().upper() == strat_key and isinstance(v, dict):
                    run_strat_prof = v
                    break

    holding_period = strat_row.holding_period if strat_row and strat_row.holding_period else None
    strategy_profile = {
        "htf": (
            (run_strat_prof.get("htf") if isinstance(run_strat_prof, dict) else None)
            or (strat_row.suggested_htf if strat_row else None)
        ),
        "ltf": (
            (run_strat_prof.get("ltf") if isinstance(run_strat_prof, dict) else None)
            or (strat_row.suggested_ltf if strat_row else None)
        ),
        "kline_limit": (
            (run_strat_prof.get("kline_limit") if isinstance(run_strat_prof, dict) else None)
            or (strat_row.suggested_kline_limit if strat_row else None)
        ),
        "expiry_hours": (
            (run_strat_prof.get("expiry_hours") if isinstance(run_strat_prof, dict) else None)
            or (strat_row.suggested_expiry_hours if strat_row else None)
        ),
        "holding_period": holding_period,
        "trade_style": strat_row.trade_style if strat_row else None,
    }

    return SetupOut(
        id=row.id,
        scan_run_id=row.scan_run_id,
        symbol=row.symbol,
        strategy_used=row.strategy_used,
        decision=row.decision,
        market_regime=row.market_regime,
        entry_type=row.entry_type,
        entry_price=float(row.entry_price),
        stop_loss=float(row.stop_loss),
        take_profit=float(row.take_profit),
        risk_reward_ratio=float(row.risk_reward_ratio),
        confidence=row.confidence,
        llm_provider=row.llm_provider,
        llm_model=row.llm_model,
        invalidation_reason=row.invalidation_reason,
        rationale=row.rationale,
        status=row.status,
        entry_hit_at=row.entry_hit_at,
        missed_tp_at=row.missed_tp_at,
        missed_tp_price=float(row.missed_tp_price) if row.missed_tp_price is not None else None,
        manual_action_at=row.manual_action_at,
        manual_entry_price=float(row.manual_entry_price) if row.manual_entry_price is not None else None,
        manual_notes=row.manual_notes,
        resolved_price=float(row.resolved_price) if row.resolved_price is not None else None,
        resolved_at=row.resolved_at,
        status_history=row.status_history or [],
        expires_at=row.expires_at,
        features_snapshot=row.features_snapshot,
        ai_payload=row.ai_payload,
        created_at=row.created_at,
        updated_at=row.updated_at,
        live_price=live_price,
        holding_period=holding_period,
        strategy_profile=strategy_profile,
        scan_run_started_at=scan_run.started_at if scan_run is not None else None,
        scan_run_settings=scan_cfg,
    )


async def _scheduler_scan_loop() -> None:
    """Periodic background market scan loop honoring dynamic AUTO/MANUAL setting in MySQL."""
    last_auto_scan_at = 0.0
    await asyncio.sleep(5)
    while True:
        try:
            db = SessionLocal()
            try:
                scanner_cfg = resolve_runtime_settings(db)
            finally:
                db.close()

            interval_sec = max(60, scanner_cfg["scan_interval_minutes"] * 60)
            now_mono = time.monotonic()
            if scanner_cfg["auto_scan_enabled"] and (
                last_auto_scan_at == 0.0 or (now_mono - last_auto_scan_at) >= interval_sec
            ):
                await scan_pipeline.run_once()
                last_auto_scan_at = time.monotonic()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.exception("Scheduled scan loop error: %s", exc)
        await asyncio.sleep(10)


_last_tracker_error: Optional[str] = None


async def _scheduler_tracker_loop() -> None:
    """Periodic background outcome tracker loop honoring dynamic MySQL settings."""
    global _last_tracker_error
    await asyncio.sleep(10)
    while True:
        interval_sec = settings.tracker_interval_seconds
        mexc_url = settings.mexc_base_url
        try:
            db = SessionLocal()
            try:
                rt_cfg = resolve_runtime_settings(db)
                interval_sec = max(15, rt_cfg["tracker_interval_seconds"])
                mexc_url = rt_cfg["mexc_base_url"]
                async with MexcPublicClient(
                    base_url=rt_cfg["mexc_base_url"],
                    proxy_url=rt_cfg["mexc_proxy_url"],
                    max_concurrency=rt_cfg["mexc_max_concurrency"],
                ) as mexc:
                    await check_open_setups(db, mexc)
                _last_tracker_error = None
            finally:
                db.close()
        except asyncio.CancelledError:
            raise
        except httpx.ConnectError as exc:
            _last_tracker_error = f"Tracker gagal terhubung ke MEXC ({mexc_url}): {exc}"
            log.warning("Scheduled tracker could not reach MEXC (%s): %s", mexc_url, exc)
        except Exception as exc:
            _last_tracker_error = f"Tracker error: {exc}"
            log.exception("Scheduled tracker loop error: %s", exc)
        await asyncio.sleep(interval_sec)


def _ensure_schema_columns() -> None:
    """Safely add new optional columns on existing MySQL/SQLite tables without dropping data."""
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())
    if "trade_setups" in table_names:
        cols = {c["name"]: c for c in inspector.get_columns("trade_setups")}
        idxs = {idx["name"] for idx in inspector.get_indexes("trade_setups")}
        with engine.begin() as conn:
            if "entry_hit_at" not in cols:
                conn.execute(text("ALTER TABLE trade_setups ADD COLUMN entry_hit_at DATETIME NULL"))
            if "missed_tp_at" not in cols:
                conn.execute(text("ALTER TABLE trade_setups ADD COLUMN missed_tp_at DATETIME NULL"))
            if "missed_tp_price" not in cols:
                conn.execute(text("ALTER TABLE trade_setups ADD COLUMN missed_tp_price DECIMAL(20, 8) NULL"))
            if "status_history" not in cols:
                conn.execute(text("ALTER TABLE trade_setups ADD COLUMN status_history JSON NULL"))
            if "manual_entry_price" not in cols:
                conn.execute(text("ALTER TABLE trade_setups ADD COLUMN manual_entry_price DECIMAL(20, 8) NULL"))
            if engine.dialect.name == "mysql":
                su_type = str(cols.get("strategy_used", {}).get("type", "")).upper()
                if "40" in su_type:
                    conn.execute(text("ALTER TABLE trade_setups MODIFY COLUMN strategy_used VARCHAR(64) NOT NULL"))
            if "idx_trade_setups_dup_lookup" not in idxs:
                conn.execute(
                    text(
                        "CREATE INDEX idx_trade_setups_dup_lookup "
                        "ON trade_setups (symbol, decision, strategy_used, status)"
                    )
                )
    if "scan_evaluations" in table_names and engine.dialect.name == "mysql":
        eval_cols = {c["name"]: c for c in inspector.get_columns("scan_evaluations")}
        su_type = str(eval_cols.get("strategy_used", {}).get("type", "")).upper()
        if "40" in su_type:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE scan_evaluations MODIFY COLUMN strategy_used VARCHAR(64) NOT NULL"))
    if "strategies" in table_names:
        strat_cols = {c["name"] for c in inspector.get_columns("strategies")}
        alter_ddls = [
            ("trade_style", "VARCHAR(40) NULL"),
            ("holding_period", "VARCHAR(80) NULL"),
            ("suggested_htf", "VARCHAR(20) NULL"),
            ("suggested_ltf", "VARCHAR(20) NULL"),
            ("suggested_kline_limit", "INT NULL"),
            ("suggested_expiry_hours", "INT NULL"),
        ]
        with engine.begin() as conn:
            for col_name, col_type in alter_ddls:
                if col_name not in strat_cols:
                    conn.execute(text(f"ALTER TABLE strategies ADD COLUMN {col_name} {col_type}"))
    if "scan_runs" in table_names:
        run_cols = {c["name"] for c in inspector.get_columns("scan_runs")}
        if "settings_snapshot" not in run_cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE scan_runs ADD COLUMN settings_snapshot JSON NULL"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize MySQL schema, seed defaults, and optionally launch schedulers."""
    log.info("Initializing database tables...")
    Base.metadata.create_all(bind=engine)
    _ensure_schema_columns()
    db = SessionLocal()
    try:
        seed_all(db)
    finally:
        db.close()

    tasks: list[asyncio.Task] = []
    if settings.auto_start_scheduler:
        log.info("Starting background scan & tracker schedulers...")
        tasks.append(asyncio.create_task(_scheduler_scan_loop()))
        tasks.append(asyncio.create_task(_scheduler_tracker_loop()))

    yield

    for task in tasks:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
    log.info("Application shut down.")


app = FastAPI(
    title="MEXC AI Setup Scanner",
    version="1.0.0",
    description="Local Crypto Futures setup scanner & manual execution tracker with AI analysis",
    lifespan=lifespan,
)

# CORS Middleware (matching simple-cash-flow pattern)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8001",
        "http://127.0.0.1:8001",
    ],
    allow_origin_regex=r".*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@app.exception_handler(SQLAlchemyError)
async def sqlalchemy_exception_handler(request: Request, exc: SQLAlchemyError):
    log.exception("Database error occurred: %s", exc)
    return JSONResponse(status_code=500, content={"detail": f"Database error: {exc}"})


# --- Health & Scanner Endpoints ---


@app.get("/api/health")
def health(db: Session = Depends(get_db)):
    """Health check with active LLM provider/model info."""
    llm_cfg = resolve_active_llm_config(db)
    return {
        "status": "online",
        "app": "mexc-ai-setup-scanner",
        "active_provider": llm_cfg["provider"],
        "active_model_id": llm_cfg["model_id"],
        "has_api_key": bool(llm_cfg["api_key"]),
        "scanner_running": scan_pipeline.is_running,
    }


@app.get("/api/scanner/status")
def get_scanner_status(db: Session = Depends(get_db)):
    """Return current scanner state, mode (AUTO/MANUAL), and recent scan runs."""
    recent_runs = db.query(ScanRun).order_by(desc(ScanRun.id)).limit(10).all()
    llm_cfg = resolve_active_llm_config(db)
    rt_cfg = resolve_runtime_settings(db)
    return {
        "is_running": scan_pipeline.is_running,
        "auto_start_scheduler": settings.auto_start_scheduler,
        "auto_scan_enabled": rt_cfg["auto_scan_enabled"],
        "scan_mode": rt_cfg["scan_mode"],
        "scan_interval_minutes": rt_cfg["scan_interval_minutes"],
        "top_n_pairs": rt_cfg["top_n_pairs"],
        "tracker_interval_seconds": rt_cfg["tracker_interval_seconds"],
        "mexc_base_url": rt_cfg["mexc_base_url"],
        "active_strategies": rt_cfg["active_strategies"],
        "active_provider": llm_cfg["provider"],
        "active_model_id": llm_cfg["model_id"],
        "last_run_summary": scan_pipeline.last_run_summary,
        "last_tracker_error": _last_tracker_error,
        "recent_runs": [ScanRunOut.model_validate(r) for r in recent_runs],
    }


@app.get("/api/scanner/runs", response_model=ScanRunListResponse)
def list_scan_runs(
    limit: int = Query(default=10, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    """List persisted scan runs with limit/offset pagination."""
    query = db.query(ScanRun)
    total = query.count()
    rows = query.order_by(desc(ScanRun.id)).offset(offset).limit(limit).all()
    return ScanRunListResponse(
        items=[ScanRunOut.model_validate(r) for r in rows],
        total=total,
    )


@app.get("/api/scanner/settings", response_model=ScannerSettingsOut)
def get_scanner_settings(db: Session = Depends(get_db)):
    """Get all persistent scanner, MEXC API, LLM runtime, and risk-guard settings."""
    return ScannerSettingsOut(**resolve_runtime_settings(db))


@app.post("/api/scanner/settings", response_model=ScannerSettingsOut)
def update_scanner_settings(body: ScannerSettingsUpdate, db: Session = Depends(get_db)):
    """Persist scanner, MEXC API, LLM runtime, and risk-guard settings in MySQL."""
    if body.llm_timeout_seconds is not None:
        _upsert_setting(db, "llm_timeout_seconds", str(body.llm_timeout_seconds))
    if body.llm_max_concurrency is not None:
        _upsert_setting(db, "llm_max_concurrency", str(body.llm_max_concurrency))
    if body.llm_max_tokens is not None:
        _upsert_setting(db, "llm_max_tokens", str(body.llm_max_tokens))
    if body.mexc_base_url is not None:
        _upsert_setting(db, "mexc_base_url", body.mexc_base_url.strip().rstrip("/"))
    if body.mexc_proxy_url is not None:
        _upsert_setting(db, "mexc_proxy_url", body.mexc_proxy_url.strip())
    if body.mexc_max_concurrency is not None:
        _upsert_setting(db, "mexc_max_concurrency", str(body.mexc_max_concurrency))
    if body.auto_scan_enabled is not None:
        _upsert_setting(db, "auto_scan_enabled", "true" if body.auto_scan_enabled else "false")
    if body.top_n_pairs is not None:
        _upsert_setting(db, "top_n_pairs", str(body.top_n_pairs))
    if body.scan_interval_minutes is not None:
        _upsert_setting(db, "scan_interval_minutes", str(body.scan_interval_minutes))
    if body.tracker_interval_seconds is not None:
        _upsert_setting(db, "tracker_interval_seconds", str(body.tracker_interval_seconds))
    if body.active_strategies is not None:
        selected_upper = [s.strip().upper() for s in body.active_strategies if s.strip()]
        if not selected_upper:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Minimal satu strategi aktif harus dipilih.",
            )
        selected_set = set(selected_upper)
        db_strats = db.query(Strategy).all()
        if db_strats:
            known = {row.name for row in db_strats}
            unknown = [s for s in selected_upper if s not in known]
            if unknown:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Strategi tidak ditemukan di database: {', '.join(unknown)}",
                )
            for row in db_strats:
                row.is_active = row.name in selected_set
        _upsert_setting(db, "active_strategies", ",".join(selected_upper))
    if body.min_24h_quote_volume is not None or body.max_24h_quote_volume is not None:
        current_rt = resolve_runtime_settings(db)
        eff_min_vol = (
            body.min_24h_quote_volume
            if body.min_24h_quote_volume is not None
            else current_rt["min_24h_quote_volume"]
        )
        eff_max_vol = (
            body.max_24h_quote_volume
            if body.max_24h_quote_volume is not None
            else current_rt["max_24h_quote_volume"]
        )
        if eff_max_vol > 0 and eff_min_vol > eff_max_vol:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Min 24h Quote Volume tidak boleh lebih besar dari Max 24h Quote Volume.",
            )
    if body.min_24h_quote_volume is not None:
        _upsert_setting(db, "min_24h_quote_volume", str(body.min_24h_quote_volume))
    if body.max_24h_quote_volume is not None:
        _upsert_setting(db, "max_24h_quote_volume", str(body.max_24h_quote_volume))
    if body.min_atr_pct is not None:
        _upsert_setting(db, "min_atr_pct", str(body.min_atr_pct))
    if body.max_atr_pct is not None:
        _upsert_setting(db, "max_atr_pct", str(body.max_atr_pct))
    if body.min_confidence is not None:
        _upsert_setting(db, "min_confidence", str(body.min_confidence))

    db.commit()
    return ScannerSettingsOut(**resolve_runtime_settings(db))


@app.post("/api/scanner/run")
async def trigger_scan_now(
    background_tasks: BackgroundTasks,
    body: Optional[ScanTriggerRequest] = None,
    db: Session = Depends(get_db),
):
    """Trigger an immediate market scan cycle."""
    if scan_pipeline.is_running:
        return {"started": False, "message": "Scan sedang berjalan, harap tunggu selesai."}

    llm_cfg = resolve_active_llm_config(db)
    if not llm_cfg.get("api_key"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"LLM API key untuk provider '{llm_cfg['provider']}' belum diisi. "
                "Klik 'AI Models & Settings' untuk mengisi API key terlebih dahulu."
            ),
        )

    latest = db.query(ScanRun.id).order_by(desc(ScanRun.id)).first()
    prev_run_id = latest[0] if latest else 0

    strategies = body.strategies if body and body.strategies else None
    top_n = body.top_n if body and body.top_n else None
    background_tasks.add_task(scan_pipeline.run_once, strategies=strategies, top_n=top_n)
    return {
        "started": True,
        "prev_run_id": prev_run_id,
        "message": "Scan market MEXC Futures dimulai di background.",
    }


@app.get("/api/scanner/runs/{run_id}/evaluations", response_model=ScanRunEvaluationsResponse)
def get_scan_run_evaluations(run_id: int, db: Session = Depends(get_db)):
    """Return full evaluation reasons and created setups for a specific scan run."""
    run = db.query(ScanRun).filter(ScanRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scan run tidak ditemukan.")
    evals = (
        db.query(ScanEvaluation)
        .filter(ScanEvaluation.scan_run_id == run_id)
        .order_by(ScanEvaluation.id.asc())
        .all()
    )
    setups = (
        db.query(TradeSetup)
        .filter(TradeSetup.scan_run_id == run_id)
        .order_by(TradeSetup.id.asc())
        .all()
    )
    strat_map = _build_strategy_map(db)
    return ScanRunEvaluationsResponse(
        run=ScanRunOut.model_validate(run),
        evaluations=[ScanEvaluationOut.model_validate(e) for e in evals],
        setups=[_setup_to_out(s, strategy_map=strat_map) for s in setups],
    )


@app.post("/api/tracker/run")
async def trigger_tracker_now(db: Session = Depends(get_db)):
    """Manually evaluate all OPEN setups against live MEXC prices."""
    global _last_tracker_error
    rt_cfg = resolve_runtime_settings(db)
    try:
        async with MexcPublicClient(
            base_url=rt_cfg["mexc_base_url"],
            proxy_url=rt_cfg["mexc_proxy_url"],
            max_concurrency=rt_cfg["mexc_max_concurrency"],
        ) as mexc:
            stats = await check_open_setups(db, mexc)
        _last_tracker_error = None
        return {"status": "COMPLETED", **stats}
    except Exception as exc:
        _last_tracker_error = f"Tracker gagal memeriksa MEXC ({rt_cfg['mexc_base_url']}): {exc}"
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=_last_tracker_error) from exc


# --- Trade Setups Endpoints ---


@app.get("/api/setups", response_model=SetupListResponse)
async def list_setups(
    status_filter: Optional[str] = Query(default=None, alias="status"),
    strategy: Optional[str] = Query(default=None),
    decision: Optional[str] = Query(default=None),
    symbol: Optional[str] = Query(default=None),
    date_filter: Optional[str] = Query(default=None, alias="date"),
    tz_offset_minutes: int = Query(default=-420, alias="tz_offset"),
    include_live_price: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    """List persisted trade setups with optional status, strategy, symbol, and date filters."""
    query = db.query(TradeSetup)
    if status_filter and status_filter != "ALL":
        query = query.filter(TradeSetup.status == status_filter)
    if strategy and strategy != "ALL":
        query = query.filter(TradeSetup.strategy_used == strategy)
    if decision and decision != "ALL":
        query = query.filter(TradeSetup.decision == decision)
    if symbol:
        query = query.filter(TradeSetup.symbol.ilike(f"%{symbol.strip().upper()}%"))
    if date_filter and date_filter.strip():
        try:
            local_day = datetime.strptime(date_filter.strip(), "%Y-%m-%d")
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Format tanggal harus YYYY-MM-DD.",
            ) from exc
        utc_start = local_day + timedelta(minutes=tz_offset_minutes)
        utc_end = utc_start + timedelta(days=1)
        query = query.filter(TradeSetup.created_at >= utc_start, TradeSetup.created_at < utc_end)

    total = query.count()
    rows = (
        query.options(joinedload(TradeSetup.scan_run))
        .order_by(desc(TradeSetup.created_at), desc(TradeSetup.id))
        .offset(offset)
        .limit(limit)
        .all()
    )

    ticker_map: dict[str, float] = {}
    if include_live_price and rows:
        try:
            async with MexcPublicClient() as mexc:
                tickers = await mexc.get_all_tickers()
                for sym, t in tickers.items():
                    if t.get("lastPrice"):
                        ticker_map[sym] = float(t["lastPrice"])
        except Exception as exc:
            log.warning("Could not attach live prices: %s", exc)

    strat_map = _build_strategy_map(db)
    items = [_setup_to_out(r, live_price=ticker_map.get(r.symbol), strategy_map=strat_map) for r in rows]
    return SetupListResponse(items=items, total=total)


@app.get("/api/setups/{setup_id}", response_model=SetupOut)
def get_setup_detail(setup_id: int, db: Session = Depends(get_db)):
    """Get full detail of a single setup."""
    row = db.query(TradeSetup).options(joinedload(TradeSetup.scan_run)).filter(TradeSetup.id == setup_id).first()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Setup tidak ditemukan")
    return _setup_to_out(row, db=db)


@app.patch("/api/setups/{setup_id}/status", response_model=SetupOut)
def update_setup_manual_status(
    setup_id: int,
    body: SetupStatusUpdate,
    db: Session = Depends(get_db),
):
    """Update setup status manually (including custom actual entry, SL, TP, and close prices)."""
    row = db.query(TradeSetup).filter(TradeSetup.id == setup_id).first()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Setup tidak ditemukan")

    if body.status in ("CLOSED_MANUAL_TP", "CLOSED_MANUAL_CL") and body.resolved_price is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Harga close (TP / CL) wajib diisi saat menutup posisi secara manual.",
        )

    eff_entry = float(
        body.manual_entry_price
        if body.manual_entry_price is not None
        else (row.manual_entry_price if row.manual_entry_price is not None else row.entry_price)
    )
    eff_sl = float(body.stop_loss if body.stop_loss is not None else row.stop_loss)
    eff_tp = float(body.take_profit if body.take_profit is not None else row.take_profit)

    if body.stop_loss is not None or body.take_profit is not None:
        if row.decision == "LONG" and not (eff_sl < eff_entry < eff_tp):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Geometri LONG tidak valid: wajib SL ({eff_sl}) < Entry ({eff_entry}) < TP ({eff_tp}).",
            )
        if row.decision == "SHORT" and not (eff_tp < eff_entry < eff_sl):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Geometri SHORT tidak valid: wajib TP ({eff_tp}) < Entry ({eff_entry}) < SL ({eff_sl}).",
            )
        risk = abs(eff_entry - eff_sl)
        if risk > 0:
            row.risk_reward_ratio = Decimal(f"{round(abs(eff_tp - eff_entry) / risk, 4):.4f}")
        if body.stop_loss is not None:
            row.stop_loss = Decimal(f"{eff_sl:.8f}")
        if body.take_profit is not None:
            row.take_profit = Decimal(f"{eff_tp:.8f}")
    elif body.manual_entry_price is not None:
        valid_geo = (
            (row.decision == "LONG" and eff_sl < eff_entry < eff_tp)
            or (row.decision == "SHORT" and eff_tp < eff_entry < eff_sl)
        )
        if valid_geo and abs(eff_entry - eff_sl) > 0:
            row.risk_reward_ratio = Decimal(f"{round(abs(eff_tp - eff_entry) / abs(eff_entry - eff_sl), 4):.4f}")

    now = utcnow()
    row.status = body.status
    note_clean = body.manual_notes.strip() if body.manual_notes is not None else (row.manual_notes or "")

    def _append_hist(event: str, price: float | None, desc: str) -> None:
        hist = ensure_created_history(row)
        hist.append(
            {
                "at": now.isoformat(),
                "event": event,
                "status": body.status,
                "price": round(float(price), 8) if price is not None else None,
                "stop_loss": float(row.stop_loss),
                "take_profit": float(row.take_profit),
                "note": f"{desc} | {note_clean}".strip(" |") if note_clean else desc,
            }
        )
        row.status_history = hist

    if body.status == "OPEN":
        row.manual_action_at = None
        row.manual_entry_price = None
        row.resolved_price = None
        row.resolved_at = None
        row.entry_hit_at = None
        row.missed_tp_at = None
        row.missed_tp_price = None
        if row.expires_at and row.expires_at <= now:
            row.expires_at = now + timedelta(hours=12)
        _append_hist("RESET_OPEN", float(row.entry_price), "Reset manual ke OPEN untuk pantau ulang")
    elif body.status == "ENTRY_HIT":
        row.entry_hit_at = row.entry_hit_at or now
        row.resolved_price = None
        row.resolved_at = None
        if row.expires_at and row.expires_at <= now:
            row.expires_at = now + timedelta(hours=12)
        _append_hist("MANUAL_ENTRY_HIT", float(row.entry_price), "Ditandai ENTRY_HIT manual")
    elif body.status == "MANUAL_TAKEN":
        row.manual_action_at = now
        row.resolved_price = None
        row.resolved_at = None
        if body.manual_entry_price is not None:
            row.manual_entry_price = Decimal(f"{body.manual_entry_price:.8f}")
        if row.expires_at and row.expires_at <= now:
            row.expires_at = now + timedelta(hours=12)
        _append_hist(
            "MANUAL_TAKEN",
            eff_entry,
            f"Eksekusi manual (Entry {eff_entry}, SL {float(row.stop_loss)}, TP {float(row.take_profit)})",
        )
    elif body.status == "MANUAL_SKIPPED":
        row.manual_action_at = now
        row.resolved_price = None
        row.resolved_at = None
        _append_hist("MANUAL_SKIPPED", None, "Setup dilewati manual (SKIP)")
    elif body.status in ("CLOSED_MANUAL_TP", "CLOSED_MANUAL_CL"):
        row.manual_action_at = row.manual_action_at or now
        if body.manual_entry_price is not None:
            row.manual_entry_price = Decimal(f"{body.manual_entry_price:.8f}")
        row.resolved_price = Decimal(f"{body.resolved_price:.8f}")
        row.resolved_at = now
        _append_hist(body.status, body.resolved_price, f"Tutup posisi manual ({body.status})")
    elif body.status == "EXPIRED":
        row.resolved_at = row.resolved_at or now
        _append_hist("EXPIRED", float(row.resolved_price) if row.resolved_price is not None else None, "Ditandai EXPIRED")

    if body.manual_notes is not None:
        row.manual_notes = body.manual_notes.strip()
    db.commit()
    db.refresh(row)
    return _setup_to_out(row, db=db)


# --- Chart & Strategy Analytics Endpoints ---


@app.get("/api/charts/{symbol}", response_model=ChartDataResponse)
async def get_symbol_chart_data(
    symbol: str,
    interval: str = Query(default="Min15"),
    limit: int = Query(default=200, ge=30, le=300),
    db: Session = Depends(get_db),
):
    """Fetch public MEXC kline candles and compute EMA 21/50/200 overlays for charting."""
    clean_symbol = symbol.strip().upper()
    rt_cfg = resolve_runtime_settings(db)
    try:
        async with MexcPublicClient(
            base_url=rt_cfg["mexc_base_url"],
            proxy_url=rt_cfg["mexc_proxy_url"],
            max_concurrency=rt_cfg["mexc_max_concurrency"],
        ) as mexc:
            candles = await mexc.get_kline(clean_symbol, interval=interval, limit=max(limit, 220))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Gagal mengambil chart {clean_symbol} dari MEXC ({rt_cfg['mexc_base_url']}): {exc}",
        ) from exc

    if not candles:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Data candle MEXC untuk {clean_symbol} tidak tersedia.",
        )

    df = compute_indicators_df(candles).tail(limit)
    candle_points = [
        CandlePoint(
            time=int(r["time"]),
            open=float(r["open"]),
            high=float(r["high"]),
            low=float(r["low"]),
            close=float(r["close"]),
            volume=float(r["volume"]),
        )
        for _, r in df.iterrows()
    ]
    ema21 = [EMAPoint(time=int(r["time"]), value=round(float(r["ema21"]), 8)) for _, r in df.iterrows()]
    ema50 = [EMAPoint(time=int(r["time"]), value=round(float(r["ema50"]), 8)) for _, r in df.iterrows()]
    ema200 = [EMAPoint(time=int(r["time"]), value=round(float(r["ema200"]), 8)) for _, r in df.iterrows()]
    dss = [EMAPoint(time=int(r["time"]), value=round(float(r["dss"]), 2)) for _, r in df.iterrows()]
    dss_signal = [EMAPoint(time=int(r["time"]), value=round(float(r["dss_signal"]), 2)) for _, r in df.iterrows()]

    return ChartDataResponse(
        symbol=clean_symbol,
        interval=interval,
        candles=candle_points,
        ema21=ema21,
        ema50=ema50,
        ema200=ema200,
        dss=dss,
        dss_signal=dss_signal,
    )


@app.get("/api/analytics/strategies", response_model=AnalyticsSummaryResponse)
def get_strategy_analytics(db: Session = Depends(get_db)):
    """Aggregate win-rate, status counts, and average R:R per strategy."""
    rows = db.query(TradeSetup).all()
    strat_names = [s.name for s in db.query(Strategy).order_by(Strategy.id.asc()).all()]
    buckets: dict[str, list[TradeSetup]] = {k: [] for k in (strat_names or list(STRATEGY_MIN_RR.keys()))}
    for r in rows:
        buckets.setdefault(r.strategy_used, []).append(r)

    items: list[StrategyAnalyticsItem] = []
    total_tp = 0
    total_sl = 0
    total_open = 0
    all_rrs: list[float] = []

    for strat_name, group in buckets.items():
        open_c = sum(1 for s in group if s.status in ("OPEN", "ENTRY_HIT"))
        tp_c = sum(1 for s in group if s.status in ("HIT_TP", "CLOSED_MANUAL_TP"))
        sl_c = sum(1 for s in group if s.status in ("HIT_SL", "CLOSED_MANUAL_CL"))
        exp_c = sum(1 for s in group if s.status == "EXPIRED")
        taken_c = sum(1 for s in group if s.status == "MANUAL_TAKEN")
        skip_c = sum(1 for s in group if s.status == "MANUAL_SKIPPED")

        decided = tp_c + sl_c
        win_rate = round((tp_c / decided) * 100.0, 2) if decided > 0 else 0.0
        avg_rr = round(sum(float(s.risk_reward_ratio) for s in group) / len(group), 2) if group else 0.0

        total_tp += tp_c
        total_sl += sl_c
        total_open += open_c
        all_rrs.extend(float(s.risk_reward_ratio) for s in group)

        items.append(
            StrategyAnalyticsItem(
                strategy_used=strat_name,
                total_setups=len(group),
                open_count=open_c,
                hit_tp_count=tp_c,
                hit_sl_count=sl_c,
                expired_count=exp_c,
                manual_taken_count=taken_c,
                manual_skipped_count=skip_c,
                decided_count=decided,
                win_rate_pct=win_rate,
                avg_rr=avg_rr,
            )
        )

    overall_decided = total_tp + total_sl
    overall_wr = round((total_tp / overall_decided) * 100.0, 2) if overall_decided > 0 else 0.0
    overall_rr = round(sum(all_rrs) / len(all_rrs), 2) if all_rrs else 0.0

    return AnalyticsSummaryResponse(
        total_setups=len(rows),
        open_count=total_open,
        overall_win_rate_pct=overall_wr,
        overall_avg_rr=overall_rr,
        strategies=items,
    )


# --- Strategy Registry Endpoints (MySQL-backed) ---


def _sync_active_strategies_setting(db: Session) -> None:
    """Keep app_settings['active_strategies'] aligned with strategies.is_active."""
    active_names = [
        s.name
        for s in db.query(Strategy).filter(Strategy.is_active.is_(True)).order_by(Strategy.id.asc()).all()
    ]
    _upsert_setting(db, "active_strategies", ",".join(active_names), "Daftar strategi aktif dipisah koma")


@app.get("/api/strategies", response_model=list[StrategyOut])
def list_strategies(db: Session = Depends(get_db)):
    """List all trading strategies and prompt rules stored in MySQL."""
    rows = db.query(Strategy).order_by(Strategy.id.asc()).all()
    return [StrategyOut.model_validate(r) for r in rows]


@app.post("/api/strategies", response_model=StrategyOut, status_code=status.HTTP_201_CREATED)
def create_strategy(body: StrategyCreate, db: Session = Depends(get_db)):
    """Create a new AI trading strategy in MySQL."""
    exists = db.query(Strategy).filter(Strategy.name == body.name).first()
    if exists:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Strategi dengan kode '{body.name}' sudah terdaftar.",
        )

    row = Strategy(
        name=body.name,
        display_name=(body.display_name or body.name).strip(),
        description=body.description.strip() if body.description else None,
        trade_style=body.trade_style.strip().upper() if body.trade_style else None,
        holding_period=body.holding_period.strip() if body.holding_period else None,
        suggested_htf=body.suggested_htf.strip() if body.suggested_htf else None,
        suggested_ltf=body.suggested_ltf.strip() if body.suggested_ltf else None,
        suggested_kline_limit=body.suggested_kline_limit,
        suggested_expiry_hours=body.suggested_expiry_hours,
        prompt_text=body.prompt_text.strip(),
        min_rr=Decimal(f"{body.min_rr:.2f}"),
        is_active=body.is_active,
        is_builtin=False,
    )
    db.add(row)
    db.flush()
    _sync_active_strategies_setting(db)
    db.commit()
    db.refresh(row)
    return StrategyOut.model_validate(row)


@app.put("/api/strategies/{strategy_id}", response_model=StrategyOut)
def update_strategy(strategy_id: int, body: StrategyUpdate, db: Session = Depends(get_db)):
    """Update strategy code/name, metadata, timeframe suggestions, prompt rules, min R:R, or active state."""
    row = db.query(Strategy).filter(Strategy.id == strategy_id).first()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Strategi tidak ditemukan.")

    if body.name is not None and body.name != row.name:
        clash = db.query(Strategy).filter(Strategy.name == body.name, Strategy.id != strategy_id).first()
        if clash:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Kode strategi '{body.name}' sudah digunakan.",
            )
        old_name = row.name
        row.name = body.name
        db.query(TradeSetup).filter(TradeSetup.strategy_used == old_name).update(
            {TradeSetup.strategy_used: body.name}
        )
        db.query(ScanEvaluation).filter(ScanEvaluation.strategy_used == old_name).update(
            {ScanEvaluation.strategy_used: body.name}
        )

    if body.display_name is not None:
        row.display_name = body.display_name.strip()
    if body.description is not None:
        row.description = body.description.strip() or None
    if body.trade_style is not None:
        row.trade_style = body.trade_style.strip().upper() or None
    if body.holding_period is not None:
        row.holding_period = body.holding_period.strip() or None
    if body.suggested_htf is not None:
        row.suggested_htf = body.suggested_htf.strip() or None
    if body.suggested_ltf is not None:
        row.suggested_ltf = body.suggested_ltf.strip() or None
    if body.suggested_kline_limit is not None:
        row.suggested_kline_limit = body.suggested_kline_limit
    if body.suggested_expiry_hours is not None:
        row.suggested_expiry_hours = body.suggested_expiry_hours
    if body.prompt_text is not None:
        row.prompt_text = body.prompt_text.strip()
    if body.min_rr is not None:
        row.min_rr = Decimal(f"{body.min_rr:.2f}")
    if body.is_active is not None:
        row.is_active = body.is_active

    _sync_active_strategies_setting(db)
    db.commit()
    db.refresh(row)
    return StrategyOut.model_validate(row)


@app.post("/api/strategies/{strategy_id}/toggle", response_model=StrategyOut)
def toggle_strategy(strategy_id: int, db: Session = Depends(get_db)):
    """Toggle active/inactive state of a strategy."""
    row = db.query(Strategy).filter(Strategy.id == strategy_id).first()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Strategi tidak ditemukan.")

    row.is_active = not bool(row.is_active)
    _sync_active_strategies_setting(db)
    db.commit()
    db.refresh(row)
    return StrategyOut.model_validate(row)


@app.delete("/api/strategies/{strategy_id}")
def delete_strategy(strategy_id: int, db: Session = Depends(get_db)):
    """Delete a custom strategy from MySQL."""
    row = db.query(Strategy).filter(Strategy.id == strategy_id).first()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Strategi tidak ditemukan.")
    if row.is_builtin:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Strategi bawaan tidak dapat dihapus; cukup nonaktifkan jika tidak ingin dipakai.",
        )

    db.delete(row)
    db.flush()
    _sync_active_strategies_setting(db)
    db.commit()
    return {"deleted": True, "id": strategy_id}


# --- AI Models & Provider Settings Endpoints (MySQL-backed) ---


@app.get("/api/ai/models")
def list_ai_models(db: Session = Depends(get_db)):
    """List all registered AI models and current provider settings."""
    models = (
        db.query(AIModel)
        .order_by(AIModel.is_active.desc(), AIModel.provider.asc(), AIModel.id.asc())
        .all()
    )
    return {
        "models": [AIModelOut.model_validate(m) for m in models],
        "settings": _build_ai_settings_out(db),
    }


@app.post("/api/ai/models", response_model=AIModelOut, status_code=status.HTTP_201_CREATED)
def create_ai_model(body: AIModelCreate, db: Session = Depends(get_db)):
    """Register a new selectable AI model in MySQL."""
    clean_model_id = body.model_id.strip()
    exists = (
        db.query(AIModel)
        .filter(AIModel.provider == body.provider, AIModel.model_id == clean_model_id)
        .first()
    )
    if exists:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Model '{clean_model_id}' untuk provider '{body.provider}' sudah terdaftar.",
        )

    row = AIModel(
        name=body.name.strip(),
        model_id=clean_model_id,
        provider=body.provider,
        description=body.description.strip() if body.description else None,
        is_active=False,
        is_custom=True,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return AIModelOut.model_validate(row)


@app.put("/api/ai/models/{model_pk}", response_model=AIModelOut)
def update_ai_model(model_pk: int, body: AIModelUpdate, db: Session = Depends(get_db)):
    """Edit an existing AI model entry."""
    row = db.query(AIModel).filter(AIModel.id == model_pk).first()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Model AI tidak ditemukan.")

    target_provider = body.provider or row.provider
    target_model_id = body.model_id.strip() if body.model_id is not None else row.model_id

    clash = (
        db.query(AIModel)
        .filter(
            AIModel.provider == target_provider,
            AIModel.model_id == target_model_id,
            AIModel.id != model_pk,
        )
        .first()
    )
    if clash:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Model '{target_model_id}' untuk provider '{target_provider}' sudah digunakan.",
        )

    if body.name is not None:
        row.name = body.name.strip()
    row.model_id = target_model_id
    row.provider = target_provider
    if body.description is not None:
        row.description = body.description.strip()

    if row.is_active:
        _upsert_setting(db, "active_model_id", row.model_id)
        _upsert_setting(db, "llm_active_provider", row.provider)

    db.commit()
    db.refresh(row)
    return AIModelOut.model_validate(row)


@app.delete("/api/ai/models/{model_pk}")
def delete_ai_model(model_pk: int, db: Session = Depends(get_db)):
    """Delete a non-active AI model from MySQL."""
    row = db.query(AIModel).filter(AIModel.id == model_pk).first()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Model AI tidak ditemukan.")
    if row.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tidak dapat menghapus model yang sedang aktif. Aktifkan model lain terlebih dahulu.",
        )
    db.delete(row)
    db.commit()
    return {"deleted": True, "id": model_pk}


@app.post("/api/ai/models/{model_pk}/activate")
def activate_ai_model(model_pk: int, db: Session = Depends(get_db)):
    """Select an AI model as active and sync active provider in app_settings."""
    target = db.query(AIModel).filter(AIModel.id == model_pk).first()
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Model AI tidak ditemukan.")

    db.query(AIModel).update({AIModel.is_active: False})
    target.is_active = True
    _upsert_setting(db, "active_model_id", target.model_id, "Model ID AI aktif")
    _upsert_setting(db, "llm_active_provider", target.provider, "Provider LLM aktif")

    db.commit()
    db.refresh(target)
    return {
        "message": f"Model '{target.name}' ({target.provider}) diaktifkan.",
        "active_model": AIModelOut.model_validate(target),
        "settings": _build_ai_settings_out(db),
    }


@app.get("/api/ai/settings", response_model=AISettingsOut)
def get_ai_settings(db: Session = Depends(get_db)):
    """Return persistent provider settings stored in MySQL."""
    return _build_ai_settings_out(db)


@app.post("/api/ai/settings", response_model=AISettingsOut)
def update_ai_settings(body: AISettingsUpdate, db: Session = Depends(get_db)):
    """Persist OpenRouter / Command Code AI / Custom provider settings & API keys to MySQL."""
    if body.active_provider is not None:
        _upsert_setting(db, "llm_active_provider", body.active_provider, "Provider LLM aktif")
    if body.commandcode_base_url is not None:
        _upsert_setting(db, "commandcode_base_url", body.commandcode_base_url.strip())
    if body.commandcode_api_key is not None and body.commandcode_api_key.strip():
        _upsert_setting(db, "commandcode_api_key", body.commandcode_api_key.strip())
    if body.openrouter_base_url is not None:
        _upsert_setting(db, "openrouter_base_url", body.openrouter_base_url.strip())
    if body.openrouter_api_key is not None and body.openrouter_api_key.strip():
        _upsert_setting(db, "openrouter_api_key", body.openrouter_api_key.strip())
    if body.custom_llm_base_url is not None:
        _upsert_setting(db, "custom_llm_base_url", body.custom_llm_base_url.strip())
    if body.custom_llm_api_key is not None and body.custom_llm_api_key.strip():
        _upsert_setting(db, "custom_llm_api_key", body.custom_llm_api_key.strip())

    db.commit()
    return _build_ai_settings_out(db)


@app.post("/api/ai/test", response_model=AITestResponse)
async def test_ai_provider_connection(
    body: Optional[AITestRequest] = None,
    db: Session = Depends(get_db),
):
    """Test live connectivity to active (or overridden) LLM provider & model."""
    resolved = resolve_active_llm_config(db)
    setting_rows = {r.key: (r.value or "") for r in db.query(AppSetting).all()}

    provider = (body.provider if body and body.provider else resolved["provider"]).strip()
    model_id = (body.model_id if body and body.model_id else resolved["model_id"]).strip()

    if body and body.base_url:
        base_url = body.base_url.strip()
    elif provider == "openrouter":
        base_url = setting_rows.get("openrouter_base_url") or DEFAULT_OPENROUTER_BASE_URL
    elif provider == "custom":
        base_url = setting_rows.get("custom_llm_base_url") or resolved["base_url"]
    else:
        base_url = setting_rows.get("commandcode_base_url") or DEFAULT_COMMANDCODE_BASE_URL

    if body and body.api_key and body.api_key.strip():
        api_key = body.api_key.strip()
    elif provider == "openrouter":
        api_key = setting_rows.get("openrouter_api_key") or resolved["api_key"]
    elif provider == "custom":
        api_key = setting_rows.get("custom_llm_api_key") or resolved["api_key"]
    else:
        api_key = setting_rows.get("commandcode_api_key") or resolved["api_key"]

    result = await test_llm_connection(
        provider=provider,
        base_url=base_url,
        api_key=api_key,
        model_id=model_id,
    )
    return AITestResponse(**result)


# --- Frontend Serving ---


if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


@app.get("/", include_in_schema=False)
def serve_dashboard():
    """Serve local HTML/JS trading dashboard."""
    index_file = FRONTEND_DIR / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file), headers={"Cache-Control": "no-store"})
    return {"status": "online", "app": "mexc-ai-setup-scanner", "docs_url": "/docs"}


@app.get("/flow", include_in_schema=False)
def serve_flow_page():
    """Serve interactive scan architecture & prompt audit page."""
    flow_file = FRONTEND_DIR / "flow.html"
    if flow_file.exists():
        return FileResponse(str(flow_file))
    raise HTTPException(status_code=404, detail="Halaman /flow tidak ditemukan.")
