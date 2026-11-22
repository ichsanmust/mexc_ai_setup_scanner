"""SQLAlchemy ORM models for setups, scan runs, AI models, and provider settings."""

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> datetime:
    """Return naive UTC datetime compatible with both MySQL DATETIME and SQLite."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class AIModel(Base):
    """Selectable AI model registry stored in MySQL."""

    __tablename__ = "ai_models"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    model_id: Mapped[str] = mapped_column(String(150), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(32), default="commandcode", nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_custom: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow, server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("provider", "model_id", name="uq_ai_models_provider_model_id"),
    )


class AppSetting(Base):
    """Persistent key-value settings (active LLM provider, URLs, API keys)."""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow, server_default=func.now(), nullable=False
    )


class Strategy(Base):
    """AI trading strategy definition, prompt rules, min R:R, and active toggle stored in MySQL."""

    __tablename__ = "strategies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    trade_style: Mapped[str | None] = mapped_column(String(40), nullable=True)
    holding_period: Mapped[str | None] = mapped_column(String(80), nullable=True)
    suggested_htf: Mapped[str | None] = mapped_column(String(20), nullable=True)
    suggested_ltf: Mapped[str | None] = mapped_column(String(20), nullable=True)
    suggested_kline_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    suggested_expiry_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)
    prompt_text: Mapped[str] = mapped_column(Text, nullable=False)
    min_rr: Mapped[Decimal] = mapped_column(Numeric(6, 2), default=Decimal("1.50"), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow, server_default=func.now(), nullable=False
    )


class ScanRun(Base):
    """Execution log for each scanner cycle."""

    __tablename__ = "scan_runs"

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    strategy: Mapped[str] = mapped_column(String(80), default="ALL", nullable=False)
    llm_provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    llm_model: Mapped[str | None] = mapped_column(String(150), nullable=True)
    total_contracts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    top_pairs_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    prefiltered_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    ai_analyzed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    setups_created_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="RUNNING", nullable=False, index=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    settings_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    setups: Mapped[list["TradeSetup"]] = relationship("TradeSetup", back_populates="scan_run")
    evaluations: Mapped[list["ScanEvaluation"]] = relationship("ScanEvaluation", back_populates="scan_run")


class TradeSetup(Base):
    """Validated actionable trading setup persisted for manual execution and tracking."""

    __tablename__ = "trade_setups"

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    scan_run_id: Mapped[int | None] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("scan_runs.id", ondelete="SET NULL"),
        nullable=True,
    )
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    strategy_used: Mapped[str] = mapped_column(String(40), nullable=False)
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    market_regime: Mapped[str] = mapped_column(String(32), nullable=False)
    entry_type: Mapped[str] = mapped_column(String(16), nullable=False)

    entry_price: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    stop_loss: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    take_profit: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    risk_reward_ratio: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    confidence: Mapped[int] = mapped_column(Integer, nullable=False)

    llm_provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    llm_model: Mapped[str | None] = mapped_column(String(150), nullable=True)
    invalidation_reason: Mapped[str] = mapped_column(Text, nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)

    status: Mapped[str] = mapped_column(String(24), default="OPEN", nullable=False)
    manual_action_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    manual_entry_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    manual_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    features_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    ai_payload: Mapped[dict] = mapped_column(JSON, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    scan_run: Mapped[ScanRun | None] = relationship("ScanRun", back_populates="setups")

    __table_args__ = (
        Index("idx_trade_setups_symbol_status", "symbol", "status"),
        Index("idx_trade_setups_created_at", "created_at"),
        Index("idx_trade_setups_strategy_status", "strategy_used", "status"),
    )


class ScanEvaluation(Base):
    """Audit log of pairs evaluated as NO_TRADE or rejected by the Risk & Math Guard."""

    __tablename__ = "scan_evaluations"

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    scan_run_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("scan_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    strategy_used: Mapped[str] = mapped_column(String(40), nullable=False)
    raw_decision: Mapped[str] = mapped_column(String(16), nullable=False)
    rejection_reason: Mapped[str] = mapped_column(String(255), nullable=False)
    confidence: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False, index=True)

    scan_run: Mapped[ScanRun] = relationship("ScanRun", back_populates="evaluations")
