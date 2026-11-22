"""SQLAlchemy engine and session management for MySQL (and SQLite in tests)."""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings


def build_engine(database_url: str):
    """Create SQLAlchemy engine with appropriate pooling options."""
    engine_kwargs: dict = {}
    if database_url.startswith("sqlite"):
        engine_kwargs["connect_args"] = {"check_same_thread": False}
    else:
        engine_kwargs["pool_pre_ping"] = True
        engine_kwargs["pool_recycle"] = 3600
    return create_engine(database_url, **engine_kwargs)


engine = build_engine(settings.database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


def get_db() -> Generator[Session, None, None]:
    """Yield a database session per request and close it safely."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
