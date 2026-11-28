"""Async public REST client for MEXC Crypto Futures (no API key / public data only)."""

import asyncio
import logging
import math
import random
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


AUTO_DEFAULT_MIN_QUOTE_VOLUME = 2_000_000.0
AUTO_MIN_RANGE_PCT = 1.5  # skip pairs with a dead 24h range
AUTO_MAX_SPREAD_PCT = 0.3  # skip pairs with a wide bid/ask spread


def _clip01(x: float) -> float:
    return max(0.0, min(1.0, x))


def score_auto_candidate(ticker: dict[str, Any], min_quote_volume: float) -> tuple[float, list[str]] | None:
    """Score a ticker 0-100 for trading opportunity; return None if it fails hard filters.

    Components (weights): liquidity 25, 24h range volatility 30, momentum 20,
    range-position (near extremes = breakout/reversal zone) 15, funding extremity 10.
    Wide spread and extreme (>40%) ranges are penalized.
    """
    try:
        last = float(ticker.get("lastPrice") or 0.0)
        amount = float(ticker.get("amount24") or 0.0)
        high = float(ticker.get("high24Price") or 0.0)
        low = float(ticker.get("lower24Price") or 0.0)
        change_pct = abs(float(ticker.get("riseFallRate") or 0.0)) * 100.0
        funding = abs(float(ticker.get("fundingRate") or 0.0))
        bid = float(ticker.get("bid1") or 0.0)
        ask = float(ticker.get("ask1") or 0.0)
    except (TypeError, ValueError):
        return None

    if last <= 0 or amount < max(min_quote_volume, 0.0) or high <= 0 or low <= 0 or high < low:
        return None

    range_pct = (high - low) / last * 100.0
    if range_pct < AUTO_MIN_RANGE_PCT:
        return None

    spread_pct = 0.0
    if bid > 0 and ask > 0 and ask >= bid:
        spread_pct = (ask - bid) / last * 100.0
        if spread_pct > AUTO_MAX_SPREAD_PCT:
            return None

    # Liquidity: log-scaled between min volume and $500M
    lo_v = math.log10(max(min_quote_volume, 1_000_000.0))
    hi_v = math.log10(500_000_000.0)
    liquidity = _clip01((math.log10(max(amount, 1.0)) - lo_v) / (hi_v - lo_v))

    # Volatility: 10% range is full score; over 40% is penalized (likely pump/dump)
    volatility = _clip01(range_pct / 10.0)
    if range_pct > 40.0:
        volatility *= _clip01(1.0 - (range_pct - 40.0) / 40.0)

    momentum = _clip01(change_pct / 6.0)

    span = high - low
    pos = _clip01((last - low) / span) if span > 0 else 0.5
    extremity = max(pos, 1.0 - pos)  # 0.5 (mid) .. 1.0 (at high/low)
    range_position = _clip01((extremity - 0.5) / 0.5)

    funding_score = _clip01(funding / 0.0005)

    score = (
        liquidity * 25.0
        + volatility * 30.0
        + momentum * 20.0
        + range_position * 15.0
        + funding_score * 10.0
    )
    score *= 1.0 - min(spread_pct / AUTO_MAX_SPREAD_PCT, 1.0) * 0.2

    reasons = [
        f"range24 {range_pct:.1f}%",
        f"chg24 {change_pct:.1f}%",
        f"pos {pos * 100:.0f}%",
    ]
    if funding_score >= 0.5:
        reasons.append(f"funding {funding * 100:.3f}%")
    return round(score, 2), reasons


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
        self._kline_pace_lock = asyncio.Lock()
        self._next_kline_at = 0.0
        self._kline_min_interval = 0.08

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
                    err_code = payload.get("code")
                    err_msg = str(payload.get("message") or "").lower()
                    extend = payload.get("_extend") if isinstance(payload.get("_extend"), dict) else {}
                    is_rate_limit = (
                        err_code == 510
                        or bool(extend.get("rateLimitType"))
                        or "rate limit" in err_msg
                    )
                    last_exc = RuntimeError(f"MEXC API error on {path}: {payload}")
                    if not is_rate_limit or is_last:
                        raise last_exc
                    wait_s = min(8.0, (2**attempt) * 1.2 + random.uniform(0.15, 0.45))
                    log.warning(
                        "MEXC rate limit (code=%s) on %s (attempt %s/%s); retrying in %.2fs",
                        err_code,
                        path,
                        attempt + 1,
                        retries,
                        wait_s,
                    )
                    await asyncio.sleep(wait_s)
                    continue
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

    async def get_auto_pairs(
        self,
        top_n: int | None = None,
        min_quote_volume: float | None = None,
    ) -> tuple[int, list[dict[str, Any]]]:
        """Return (total_active_contracts, top_n_pairs_ranked_by_opportunity_score).

        Uses only ticker data already fetched (no extra requests): liquidity, 24h range
        volatility, momentum, range position, funding extremity, minus a spread penalty.
        """
        limit_n = top_n or settings.top_n_pairs
        min_vol = min_quote_volume if min_quote_volume is not None else AUTO_DEFAULT_MIN_QUOTE_VOLUME

        contracts, tickers = await asyncio.gather(
            self.get_active_usdt_contracts(),
            self.get_all_tickers(),
        )

        scored: list[dict[str, Any]] = []
        for contract in contracts:
            sym = contract.get("symbol")
            if not sym or sym not in tickers:
                continue
            ticker = tickers[sym]
            result = score_auto_candidate(ticker, min_vol)
            if result is None:
                continue
            score, reasons = result
            scored.append(
                {
                    "symbol": sym,
                    "contract": contract,
                    "ticker": ticker,
                    "amount24": float(ticker.get("amount24") or 0.0),
                    "auto_score": score,
                    "auto_reasons": reasons,
                }
            )

        scored.sort(key=lambda x: x["auto_score"], reverse=True)
        return len(contracts), scored[:limit_n]

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

    async def _pace_kline_request(self) -> None:
        """Space out kline requests slightly to avoid triggering MEXC IP burst rate limits (code 510)."""
        if self._kline_min_interval <= 0:
            return
        async with self._kline_pace_lock:
            now = time.monotonic()
            scheduled = max(now, self._next_kline_at)
            self._next_kline_at = scheduled + self._kline_min_interval
            delay = scheduled - now
        if delay > 0:
            await asyncio.sleep(delay)

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

        await self._pace_kline_request()
        data = await self._get_json(
            f"/api/v1/contract/kline/{symbol}",
            params={"interval": interval, "start": calc_start, "end": now_sec},
            retries=5,
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
