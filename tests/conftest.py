"""Pytest fixtures providing isolated temporary SQLite DB for tests."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.database import Base, get_db
from app.seed import seed_all
from app.web import dashboard


@pytest.fixture()
def db_session(tmp_path):
    db_file = tmp_path / "test_scanner.db"
    test_engine = create_engine(
        f"sqlite:///{db_file}",
        connect_args={"check_same_thread": False},
    )
    TestingSessionLocal = sessionmaker(bind=test_engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=test_engine)

    db = TestingSessionLocal()
    seed_all(db)
    try:
        yield db, TestingSessionLocal, test_engine
    finally:
        db.close()
        test_engine.dispose()


@pytest.fixture()
def api_client(db_session, monkeypatch):
    _, TestingSessionLocal, test_engine = db_session

    monkeypatch.setattr(settings, "auto_start_scheduler", False)
    monkeypatch.setattr(dashboard, "engine", test_engine)
    monkeypatch.setattr(dashboard, "SessionLocal", TestingSessionLocal)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    dashboard.app.dependency_overrides[get_db] = override_get_db
    with TestClient(dashboard.app) as client:
        yield client
    dashboard.app.dependency_overrides.clear()
