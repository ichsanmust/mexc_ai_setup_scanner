"""Async public REST client for MEXC Crypto Futures (no API key / public data only)."""

import asyncio
import logging
import time
from typing import Any, Optional

import httpx

from ..config import settings

log = logging.getLogger(__name__)

INTERVAL_SECONDS_MAP: dict[str, int] = {
    "Min1": 60,
    "Min5": 300,
    "Min15": 900,
    "Min30": 1800,
    "Min60": 3600,
    "Hour4": 14400,
    "Hour8": 28800,
    "Day1": 86400,
}


class MexcPublicClient:
    """Rate-limited async client for MEXC Futures public REST endpoints."""

    def __init__(
        self,
        base_url: str | None = None,
        proxy_url: str | None = None,
        max_concurrency: int | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        self.base_url = (base_url or settings.mexc_base_url).rstrip("/")
        raw_proxy = proxy_url if proxy_url is not None else settings.mexc_proxy_url
        self.proxy_url = raw_proxy.strip() or None
        self.semaphore = asyncio.Semaphore(max_concurrency or settings.mexc_max_concurrency)
        self.timeout = timeout_seconds or settings.mexc_request_timeout_seconds
        self._client: Optional[httpx.AsyncClient] = None

    def _build_client(self) -> httpx.AsyncClient:
        kwargs: dict[str, Any] = {
            "base_url": self.base_url,
            "timeout": httpx.Timeout(self.timeout),
            "headers": {"Accept": "application/json", "User-Agent": "mexc-ai-setup-scanner/1.0"},
        }
        if self.proxy_url:
            kwargs["proxy"] = self.proxy_url
        return httpx.AsyncClient(**kwargs)

    async def __aenter__(self) -> "MexcPublicClient":
        self._client = self._build_client()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _get_json(self, path: str, params: dict[str, Any] | None = None, retries: int = 3) -> Any:
        """Execute GET request with semaphore rate-limiting and exponential backoff."""
        own_client = False
        client = self._client
        if client is None:
            client = self._build_client()
            own_client = True

        try:
            last_exc: Exception | None = None
            for attempt in range(retries):
                is_last = attempt >= retries - 1
                # Semaphore hanya membatasi request in-flight; backoff sleep dilakukan di luar
                # agar slot concurrency tidak tertahan selama menunggu.
                try:
                    async with self.semaphore:
                        resp = await client.get(path, params=params)
                except httpx.RequestError as exc:
                    last_exc = exc
                    if is_last:
                        raise
                    log.warning("MEXC request error on %s (attempt %s/%s): %s", path, attempt + 1, retries, exc)
                    await asyncio.sleep((2**attempt) * 0.6)
                    continue

                if resp.status_code == 429 or resp.status_code >= 500:
                    last_exc = RuntimeError(f"MEXC HTTP {resp.status_code} on {path}")
                    if is_last:
                        raise last_exc
                    wait_s = (2**attempt) * 0.6
                    log.warning(
                        "MEXC HTTP %s on %s (attempt %s/%s); retrying in %.1fs",
                        resp.status_code,
                        path,
                        attempt + 1,
                        retries,
                        wait_s,
                    )
                    await asyncio.sleep(wait_s)
                    continue

                resp.raise_for_status()
                payload = resp.json()
                if isinstance(payload, dict) and payload.get("success") is False:
                    raise RuntimeError(f"MEXC API error on {path}: {payload}")
                return payload.get("data", payload) if isinstance(payload, dict) else payload

            # Tidak pernah tercapai: loop di atas selalu return atau raise.
            raise last_exc or RuntimeError(f"MEXC request failed on {path}")
        finally:
            if own_client:
                await client.aclose()

    async def get_active_usdt_contracts(self) -> list[dict[str, Any]]:
        """Fetch active USDT-M perpetual contracts from /api/v1/contract/detail."""
        data = await self._get_json("/api/v1/contract/detail")
        if not isinstance(data, list):
            return []
        return [
            item
            for item in data
            if item.get("quoteCoin") == "USDT" and int(item.get("state", 0)) == 0
        ]

    async def get_all_tickers(self) -> dict[str, dict[str, Any]]:
        """Fetch all futures tickers mapped by symbol from /api/v1/contract/ticker."""
        data = await self._get_json("/api/v1/contract/ticker")
        if not isinstance(data, list):
            return {}
        return {item["symbol"]: item for item in data if item.get("symbol")}

    async def get_top_pairs(
        self,
        top_n: int | None = None,
        min_quote_volume: float | None = None,
        max_quote_volume: float | None = None,
    ) -> tuple[int, list[dict[str, Any]]]:
        """Return (total_active_contracts, top_n_liquid_pairs_with_ticker)."""
        limit_n = top_n or settings.top_n_pairs
        min_vol = min_quote_volume if min_quote_volume is not None else settings.min_24h_quote_volume
        max_vol = max_quote_volume if max_quote_volume is not None else settings.max_24h_quote_volume

        contracts, tickers = await asyncio.gather(
            self.get_active_usdt_contracts(),
            self.get_all_tickers(),
        )

        merged: list[dict[str, Any]] = []
        for contract in contracts:
            sym = contract.get("symbol")
            if not sym or sym not in tickers:
                continue
            ticker = tickers[sym]
            amount_24 = float(ticker.get("amount24") or 0.0)
            last_price = float(ticker.get("lastPrice") or 0.0)
            if last_price <= 0 or amount_24 < min_vol:
                continue
            if max_vol > 0 and amount_24 > max_vol:
                continue
            merged.append({"symbol": sym, "contract": contract, "ticker": ticker, "amount24": amount_24})

        merged.sort(key=lambda x: x["amount24"], reverse=True)
        return len(contracts), merged[:limit_n]

    async def get_selected_pairs(
        self, symbols: list[str]
    ) -> tuple[int, list[dict[str, Any]], list[dict[str, str]]]:
        """Return (total_active_contracts, valid_pair_dicts, invalid_entries) preserving input order.

        invalid_entries lists every requested symbol that is not tradable on MEXC right now
        (unknown, delisted/not-active, no ticker, or non-positive price), with a reason.
        """
        contracts, tickers = await asyncio.gather(
            self.get_active_usdt_contracts(),
            self.get_all_tickers(),
        )
        contract_map = {c["symbol"]: c for c in contracts if c.get("symbol")}
        selected: list[dict[str, Any]] = []
        invalid: list[dict[str, str]] = []
        seen: set[str] = set()
        for raw_sym in symbols:
            sym = str(raw_sym or "").strip().upper()
            if not sym or sym in seen:
                continue
            seen.add(sym)
            contract = contract_map.get(sym)
            ticker = tickers.get(sym)
            if not contract:
                invalid.append({"symbol": sym, "reason": "Tidak ditemukan / tidak aktif di MEXC Futures"})
                continue
            if not ticker:
                invalid.append({"symbol": sym, "reason": "Ticker tidak tersedia"})
                continue
            last_price = float(ticker.get("lastPrice") or 0.0)
            if last_price <= 0:
                invalid.append({"symbol": sym, "reason": "Harga terakhir tidak valid (<= 0)"})
                continue
            amount_24 = float(ticker.get("amount24") or 0.0)
            selected.append({"symbol": sym, "contract": contract, "ticker": ticker, "amount24": amount_24})
        return len(contracts), selected, invalid

    async def get_kline(
        self,
        symbol: str,
        interval: str = "Min15",
        limit: int = 250,
        start_ts: int | None = None,
        end_ts: int | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch OHLCV candles from /api/v1/contract/kline/{symbol}."""
        now_sec = end_ts or int(time.time())
        step_sec = INTERVAL_SECONDS_MAP.get(interval, 900)
        calc_start = start_ts or (now_sec - step_sec * (limit + 5))

        data = await self._get_json(
            f"/api/v1/contract/kline/{symbol}",
            params={"interval": interval, "start": calc_start, "end": now_sec},
        )
        return parse_mexc_kline_payload(data, limit=limit)

    async def get_funding_rate(self, symbol: str) -> Optional[float]:
        """Fetch current funding rate from /api/v1/contract/funding_rate/{symbol}."""
        try:
            data = await self._get_json(f"/api/v1/contract/funding_rate/{symbol}")
            if isinstance(data, dict) and data.get("fundingRate") is not None:
                return float(data["fundingRate"])
        except Exception as exc:
            log.debug("Could not fetch funding rate for %s: %s", symbol, exc)
        return None


def parse_mexc_kline_payload(data: Any, limit: int | None = None) -> list[dict[str, Any]]:
    """Normalize MEXC array-of-arrays/dict kline format into sorted candle dicts."""
    if not isinstance(data, dict):
        return []

    times = data.get("time") or []
    opens = data.get("open") or []
    highs = data.get("high") or []
    lows = data.get("low") or []
    closes = data.get("close") or []
    vols = data.get("vol") or []

    count = min(len(times), len(opens), len(highs), len(lows), len(closes))
    candles: list[dict[str, Any]] = []
    for i in range(count):
        ts = int(times[i])
        if ts > 10_000_000_000:
            ts = ts // 1000
        candles.append(
            {
                "time": ts,
                "open": float(opens[i]),
                "high": float(highs[i]),
                "low": float(lows[i]),
                "close": float(closes[i]),
                "volume": float(vols[i]) if i < len(vols) else 0.0,
            }
        )

    candles.sort(key=lambda c: c["time"])
    if limit and len(candles) > limit:
        candles = candles[-limit:]
    return candles
