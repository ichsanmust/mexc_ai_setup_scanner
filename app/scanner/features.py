"""Deterministic technical indicators, S/R structure detection, and pre-filter."""

from typing import Any, Optional

import numpy as np
import pandas as pd

from ..config import settings


def compute_indicators_df(candles: list[dict[str, Any]]) -> pd.DataFrame:
    """Compute deterministic EMA 21/50/200, RSI 14, ATR 14, and Volume MA20."""
    df = pd.DataFrame(candles)
    if df.empty:
        return df

    df = df.sort_values("time").reset_index(drop=True)
    close = df["close"].astype(float)
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    volume = df["volume"].astype(float)

    df["ema21"] = close.ewm(span=21, adjust=False).mean()
    df["ema50"] = close.ewm(span=50, adjust=False).mean()
    df["ema200"] = close.ewm(span=200, adjust=False).mean()

    # Wilder RSI 14
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    # Handle zero-loss (all gains) and zero-gain (all losses) edge cases cleanly
    rsi = rsi.where(avg_loss != 0.0, 100.0)
    rsi = rsi.where(~((avg_gain == 0.0) & (avg_loss == 0.0)), 50.0)
    df["rsi14"] = rsi.fillna(50.0)

    # Wilder ATR 14
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    df["atr14"] = tr.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean().bfill()

    df["vol_ma20"] = volume.rolling(window=20, min_periods=1).mean()
    df["volume_ratio"] = volume / df["vol_ma20"].replace(0.0, np.nan)
    df["volume_ratio"] = df["volume_ratio"].fillna(1.0)

    # DSS Bressert (Double Smoothed Stochastic: Stoch 10, EMA 9, Signal 5)
    pds = 10
    slw = 9
    trig = 5
    low_min = low.rolling(window=pds, min_periods=1).min()
    high_max = high.rolling(window=pds, min_periods=1).max()
    denom1 = (high_max - low_min).replace(0.0, np.nan)
    x_pre1 = (((close - low_min) / denom1) * 100.0).fillna(50.0)
    x_dss = x_pre1.ewm(span=slw, adjust=False).mean()

    x_low = x_dss.rolling(window=pds, min_periods=1).min()
    x_high = x_dss.rolling(window=pds, min_periods=1).max()
    denom2 = (x_high - x_low).replace(0.0, np.nan)
    x_pre2 = (((x_dss - x_low) / denom2) * 100.0).fillna(50.0)
    df["dss"] = x_pre2.ewm(span=slw, adjust=False).mean().clip(0.0, 100.0)
    df["dss_signal"] = df["dss"].ewm(span=trig, adjust=False).mean().clip(0.0, 100.0)
    return df


def detect_swings_and_sr(
    df: pd.DataFrame,
    pivot_radius: int = 3,
    lookback_bars: int = 100,
) -> dict[str, float]:
    """Identify recent swing high/low and nearest support/resistance deterministically."""
    sub = df.tail(lookback_bars).reset_index(drop=True)
    current_close = float(sub["close"].iloc[-1])
    highs = sub["high"].to_numpy(dtype=float)
    lows = sub["low"].to_numpy(dtype=float)

    pivot_highs: list[float] = []
    pivot_lows: list[float] = []

    n = len(sub)
    for i in range(pivot_radius, max(pivot_radius, n - pivot_radius)):
        window_h = highs[i - pivot_radius : i + pivot_radius + 1]
        window_l = lows[i - pivot_radius : i + pivot_radius + 1]
        if highs[i] == np.max(window_h):
            pivot_highs.append(float(highs[i]))
        if lows[i] == np.min(window_l):
            pivot_lows.append(float(lows[i]))

    recent_swing_high = pivot_highs[-1] if pivot_highs else float(np.max(highs[-min(20, n) :]))
    recent_swing_low = pivot_lows[-1] if pivot_lows else float(np.min(lows[-min(20, n) :]))

    supports_below = [lvl for lvl in pivot_lows if lvl < current_close]
    resistances_above = [lvl for lvl in pivot_highs if lvl > current_close]

    nearest_support = max(supports_below) if supports_below else float(np.min(lows))
    nearest_resistance = min(resistances_above) if resistances_above else float(np.max(highs))

    return {
        "recent_swing_high": round(recent_swing_high, 8),
        "recent_swing_low": round(recent_swing_low, 8),
        "nearest_support": round(nearest_support, 8),
        "nearest_resistance": round(nearest_resistance, 8),
    }


def _candle_metrics(row: pd.Series) -> dict[str, Any]:
    """Summarize body and wick proportions of a single candle."""
    o = float(row["open"])
    h = float(row["high"])
    l = float(row["low"])
    c = float(row["close"])
    full_range = max(h - l, 1e-12)
    body = abs(c - o)
    upper_wick = h - max(o, c)
    lower_wick = min(o, c) - l
    return {
        "open": round(o, 8),
        "high": round(h, 8),
        "low": round(l, 8),
        "close": round(c, 8),
        "direction": "BULLISH" if c >= o else "BEARISH",
        "body_pct": round((body / full_range) * 100.0, 2),
        "upper_wick_pct": round((upper_wick / full_range) * 100.0, 2),
        "lower_wick_pct": round((lower_wick / full_range) * 100.0, 2),
    }


def summarize_timeframe(candles: list[dict[str, Any]], interval: str) -> dict[str, Any]:
    """Compute structured feature summary for a single timeframe."""
    df = compute_indicators_df(candles)
    last = df.iloc[-1]
    prev = df.iloc[-2] if len(df) > 1 else last

    close = float(last["close"])
    ema21 = float(last["ema21"])
    ema50 = float(last["ema50"])
    ema200 = float(last["ema200"])
    atr14 = float(last["atr14"])
    rsi14 = float(last["rsi14"])
    prev_rsi14 = float(prev["rsi14"])

    atr_pct = (atr14 / close * 100.0) if close > 0 else 0.0
    levels = detect_swings_and_sr(df)

    if close > ema50 > ema200 and ema21 > ema50:
        ema_bias = "BULLISH_ALIGNED"
    elif close < ema50 < ema200 and ema21 < ema50:
        ema_bias = "BEARISH_ALIGNED"
    elif abs(ema21 - ema50) / max(close, 1e-12) < 0.004:
        ema_bias = "FLAT_RANGING"
    else:
        ema_bias = "MIXED"

    # Range compression check over last 12 bars vs 40 bars
    recent_12 = df.tail(12)
    recent_40 = df.tail(40)
    range_12 = float(recent_12["high"].max() - recent_12["low"].min())
    range_40 = max(float(recent_40["high"].max() - recent_40["low"].min()), 1e-12)
    compression_ratio = round(range_12 / range_40, 3)

    recent_candles = [_candle_metrics(df.iloc[idx]) for idx in range(max(0, len(df) - 3), len(df))]

    return {
        "interval": interval,
        "bars_count": len(df),
        "close": round(close, 8),
        "ema21": round(ema21, 8),
        "ema50": round(ema50, 8),
        "ema200": round(ema200, 8),
        "ema_bias": ema_bias,
        "dist_to_ema21_pct": round(((close - ema21) / ema21 * 100.0) if ema21 else 0.0, 3),
        "dist_to_ema50_pct": round(((close - ema50) / ema50 * 100.0) if ema50 else 0.0, 3),
        "dist_to_ema200_pct": round(((close - ema200) / ema200 * 100.0) if ema200 else 0.0, 3),
        "rsi14": round(rsi14, 2),
        "prev_rsi14": round(prev_rsi14, 2),
        "atr14": round(atr14, 8),
        "atr_pct": round(atr_pct, 3),
        "vol_ma20": round(float(last["vol_ma20"]), 4),
        "current_volume": round(float(last["volume"]), 4),
        "volume_ratio": round(float(last["volume_ratio"]), 3),
        "compression_ratio": compression_ratio,
        **levels,
        "dist_to_support_pct": round(((close - levels["nearest_support"]) / close * 100.0) if close else 0.0, 3),
        "dist_to_resistance_pct": round(
            ((levels["nearest_resistance"] - close) / close * 100.0) if close else 0.0, 3
        ),
        "recent_candles": recent_candles,
    }


def prefilter_and_build_snapshot(
    symbol: str,
    ticker: dict[str, Any],
    htf_candles: list[dict[str, Any]],
    ltf_candles: list[dict[str, Any]],
    min_atr_pct: float | None = None,
    max_atr_pct: float | None = None,
    htf_interval: str | None = None,
    ltf_interval: str | None = None,
    min_candles: int = 60,
) -> tuple[bool, str, Optional[dict[str, Any]]]:
    """Run lightweight pre-filters and build structured multi-timeframe AI snapshot."""
    min_atr = settings.min_atr_pct if min_atr_pct is None else min_atr_pct
    max_atr = settings.max_atr_pct if max_atr_pct is None else max_atr_pct
    htf_iv = htf_interval or settings.htf_interval
    ltf_iv = ltf_interval or settings.ltf_interval

    if len(htf_candles) < min_candles or len(ltf_candles) < min_candles:
        return False, f"Insufficient candles (htf={len(htf_candles)}, ltf={len(ltf_candles)})", None

    htf_summary = summarize_timeframe(htf_candles, htf_iv)
    ltf_summary = summarize_timeframe(ltf_candles, ltf_iv)

    ltf_atr_pct = ltf_summary["atr_pct"]
    if ltf_atr_pct < min_atr:
        return False, f"Low volatility pre-filter (LTF ATR% {ltf_atr_pct:.3f} < {min_atr})", None
    if ltf_atr_pct > max_atr:
        return False, f"Extreme volatility pre-filter (LTF ATR% {ltf_atr_pct:.3f} > {max_atr})", None

    vol_24h_quote = float(ticker.get("amount24") or 0.0)
    if vol_24h_quote <= 0:
        return False, "Zero 24h quote volume", None

    snapshot = {
        "symbol": symbol,
        "market_ticker": {
            "last_price": float(ticker.get("lastPrice") or ltf_summary["close"]),
            "fair_price": float(ticker.get("fairPrice") or 0.0),
            "index_price": float(ticker.get("indexPrice") or 0.0),
            "change_24h_pct": round(float(ticker.get("riseFallRate") or 0.0) * 100.0, 3),
            "quote_volume_24h": round(vol_24h_quote, 2),
            "funding_rate": float(ticker.get("fundingRate") or 0.0),
            "open_interest_hold_vol": float(ticker.get("holdVol") or 0.0),
            "high_24h": float(ticker.get("high24Price") or 0.0),
            "low_24h": float(ticker.get("lower24Price") or 0.0),
        },
        "htf_1h": htf_summary,
        "ltf_15m": ltf_summary,
    }
    return True, "OK", snapshot
