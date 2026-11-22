"""Entry point for running MEXC AI Setup Scanner dashboard & scheduler or one-off CLI scan."""

import argparse
import asyncio
import json
import logging

import uvicorn

from app.config import settings
from app.core.pipeline import scan_pipeline
from app.database import Base, SessionLocal, engine
from app.seed import seed_all

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)


def run_cli_scan_once(strategies: list[str] | None, top_n: int | None) -> None:
    """Initialize DB/seed and execute a single scan cycle via CLI."""
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed_all(db)
    finally:
        db.close()

    result = asyncio.run(scan_pipeline.run_once(strategies=strategies, top_n=top_n))
    print(json.dumps(result, indent=2, default=str))


def main() -> None:
    parser = argparse.ArgumentParser(description="MEXC AI Setup Scanner")
    parser.add_argument("--scan-once", action="store_true", help="Run one market scan cycle and exit")
    parser.add_argument("--strategies", nargs="*", help="Optional strategies to run in --scan-once mode")
    parser.add_argument("--top-n", type=int, default=None, help="Override TOP_N_PAIRS for --scan-once")
    parser.add_argument("--host", default=settings.app_host, help="FastAPI bind host")
    parser.add_argument("--port", type=int, default=settings.app_port, help="FastAPI bind port")
    parser.add_argument("--reload", action="store_true", help="Enable uvicorn auto-reload")
    args = parser.parse_args()

    if args.scan_once:
        run_cli_scan_once(strategies=args.strategies, top_n=args.top_n)
        return

    uvicorn.run(
        "app.web.dashboard:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )


if __name__ == "__main__":
    main()
