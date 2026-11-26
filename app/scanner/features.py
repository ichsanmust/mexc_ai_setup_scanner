"""Deterministic technical indicators, S/R structure detection, and pre-filter."""

import time
from typing import Any, Optional

import numpy as np
import pandas as pd

from ..config import settings
from .mexc_public import INTERVAL_SECONDS_MAP


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
) -> dict[str, Any]:
    """Identify swing pivots, S/R levels, market structure (HH/HL/LH/LL), and sweep flags."""
    sub = df.tail(lookback_bars).reset_index(drop=True)
    current_close = float(sub["close"].iloc[-1])
    highs = sub["high"].to_numpy(dtype=float)
    lows = sub["low"].to_numpy(dtype=float)
    closes = sub["close"].to_numpy(dtype=float)

    pivot_high_pts: list[tuple[int, float]] = []
    pivot_low_pts: list[tuple[int, float]] = []

    n = len(sub)
    for i in range(pivot_radius, max(pivot_radius, n - pivot_radius)):
        window_h = highs[i - pivot_radius : i + pivot_radius + 1]
        window_l = lows[i - pivot_radius : i + pivot_radius + 1]
        if highs[i] == np.max(window_h):
            pivot_high_pts.append((i, float(highs[i])))
        if lows[i] == np.min(window_l):
            pivot_low_pts.append((i, float(lows[i])))

    pivot_highs = [p for _, p in pivot_high_pts]
    pivot_lows = [p for _, p in pivot_low_pts]

    recent_swing_high = pivot_highs[-1] if pivot_highs else float(np.max(highs[-min(20, n) :]))
    recent_swing_low = pivot_lows[-1] if pivot_lows else float(np.min(lows[-min(20, n) :]))

    # Prior swings strictly before the last 3 bars (so sweep detection doesn't confuse the sweep bar itself)
    prior_highs = [p for idx, p in pivot_high_pts if idx < max(0, n - 3)]
    prior_lows = [p for idx, p in pivot_low_pts if idx < max(0, n - 3)]
    prior_swing_high = round(prior_highs[-1], 8) if prior_highs else None
    prior_swing_low = round(prior_lows[-1], 8) if prior_lows else None

    tail_start = max(0, n - 3)
    swept_prior_low = bool(
        prior_swing_low is not None
        and any(lows[k] < prior_swing_low and closes[k] > prior_swing_low for k in range(tail_start, n))
    )
    swept_prior_high = bool(
        prior_swing_high is not None
        and any(highs[k] > prior_swing_high and closes[k] < prior_swing_high for k in range(tail_start, n))
    )

    if len(pivot_highs) >= 2 and len(pivot_lows) >= 2:
        if pivot_highs[-1] > pivot_highs[-2] and pivot_lows[-1] > pivot_lows[-2]:
            structure_bias = "HH_HL"
        elif pivot_highs[-1] < pivot_highs[-2] and pivot_lows[-1] < pivot_lows[-2]:
            structure_bias = "LH_LL"
        else:
            structure_bias = "MIXED_RANGE"
    else:
        structure_bias = "INSUFFICIENT"

    supports_below = [lvl for lvl in pivot_lows if lvl < current_close]
    resistances_above = [lvl for lvl in pivot_highs if lvl > current_close]

    support_is_fallback = not bool(supports_below)
    resistance_is_fallback = not bool(resistances_above)
    nearest_support = max(supports_below) if supports_below else float(np.min(lows))
    nearest_resistance = min(resistances_above) if resistances_above else float(np.max(highs))

    return {
        "recent_swing_high": round(recent_swing_high, 8),
        "recent_swing_low": round(recent_swing_low, 8),
        "prior_swing_high": prior_swing_high,
        "prior_swing_low": prior_swing_low,
        "swept_prior_high": swept_prior_high,
        "swept_prior_low": swept_prior_low,
        "structure_bias": structure_bias,
        "nearest_support": round(nearest_support, 8),
        "nearest_resistance": round(nearest_resistance, 8),
        "support_is_fallback": support_is_fallback,
        "resistance_is_fallback": resistance_is_fallback,
        "pivot_highs_recent": [
            {"price": round(p, 8), "bars_ago": (n - 1) - idx} for idx, p in pivot_high_pts[-4:]
        ],
        "pivot_lows_recent": [
            {"price": round(p, 8), "bars_ago": (n - 1) - idx} for idx, p in pivot_low_pts[-4:]
        ],
    }


def _candle_metrics(row: pd.Series) -> dict[str, Any]:
    """Summarize body, wick proportions, volume, and direction of a single candle."""
    o = float(row["open"])
    h = float(row["high"])
    l = float(row["low"])
    c = float(row["close"])
    v = float(row.get("volume", 0.0))
    full_range = max(h - l, 1e-12)
    body = abs(c - o)
    upper_wick = h - max(o, c)
    lower_wick = min(o, c) - l
    is_bullish = c >= o
    return {
        "open": round(o, 8),
        "high": round(h, 8),
        "low": round(l, 8),
        "close": round(c, 8),
        "volume": round(v, 4),
        "is_bullish": is_bullish,
        "direction": "BULLISH" if is_bullish else "BEARISH",
        "body_pct": round((body / full_range) * 100.0, 2),
        "upper_wick_pct": round((upper_wick / full_range) * 100.0, 2),
        "lower_wick_pct": round((lower_wick / full_range) * 100.0, 2),
    }


def filter_closed_candles(
    candles: list[dict[str, Any]],
    interval: str,
    now_ts: int | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Drop in-progress (unclosed) candles where time + interval_seconds > now_ts.

    Returns (closed_candles, forming_candle_metrics_or_none).
    """
    step_sec = INTERVAL_SECONDS_MAP.get(interval)
    if not candles or step_sec is None:
        return candles, None

    ref_ts = int(now_ts if now_ts is not None else time.time())
    ordered = sorted(candles, key=lambda c: int(c["time"]))
    closed = [c for c in ordered if int(c["time"]) + step_sec <= ref_ts]
    unclosed = [c for c in ordered if int(c["time"]) + step_sec > ref_ts]

    forming: dict[str, Any] | None = None
    if unclosed:
        forming = _candle_metrics(pd.Series(unclosed[-1]))
        forming["is_closed"] = False
    return closed, forming


def summarize_timeframe(
    candles: list[dict[str, Any]],
    interval: str,
    now_ts: int | None = None,
) -> dict[str, Any]:
    """Compute structured feature summary for a single timeframe using closed candles only."""
    closed_candles, forming_candle = filter_closed_candles(candles, interval, now_ts=now_ts)
    target_candles = closed_candles if closed_candles else candles
    df = compute_indicators_df(target_candles)
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
    compact_candles = [
        {
            "o": round(float(df.iloc[idx]["open"]), 8),
            "h": round(float(df.iloc[idx]["high"]), 8),
            "l": round(float(df.iloc[idx]["low"]), 8),
            "c": round(float(df.iloc[idx]["close"]), 8),
            "vr": round(float(df.iloc[idx]["volume_ratio"]), 2),
        }
        for idx in range(max(0, len(df) - 15), len(df))
    ]

    dss_now = float(last["dss"])
    dss_sig_now = float(last["dss_signal"])
    prev_dss = float(prev["dss"])
    prev_dss_sig = float(prev["dss_signal"])

    slope_idx = max(0, len(df) - 6)
    ema21_prev5 = float(df.iloc[slope_idx]["ema21"])
    ema50_prev5 = float(df.iloc[slope_idx]["ema50"])
    ema21_slope_pct = round(((ema21 - ema21_prev5) / ema21_prev5 * 100.0) if ema21_prev5 else 0.0, 3)
    ema50_slope_pct = round(((ema50 - ema50_prev5) / ema50_prev5 * 100.0) if ema50_prev5 else 0.0, 3)

    summary = {
        "interval": interval,
        "bars_count": len(df),
        "close": round(close, 8),
        "ema21": round(ema21, 8),
        "ema50": round(ema50, 8),
        "ema200": round(ema200, 8),
        "ema_bias": ema_bias,
        "ema21_slope_pct": ema21_slope_pct,
        "ema50_slope_pct": ema50_slope_pct,
        "dist_to_ema21_pct": round(((close - ema21) / ema21 * 100.0) if ema21 else 0.0, 3),
        "dist_to_ema50_pct": round(((close - ema50) / ema50 * 100.0) if ema50 else 0.0, 3),
        "dist_to_ema200_pct": round(((close - ema200) / ema200 * 100.0) if ema200 else 0.0, 3),
        "rsi14": round(rsi14, 2),
        "prev_rsi14": round(prev_rsi14, 2),
        "dss": round(dss_now, 2),
        "prev_dss": round(prev_dss, 2),
        "dss_signal": round(dss_sig_now, 2),
        "prev_dss_signal": round(prev_dss_sig, 2),
        "dss_cross_up": bool(prev_dss <= prev_dss_sig and dss_now > dss_sig_now),
        "dss_cross_down": bool(prev_dss >= prev_dss_sig and dss_now < dss_sig_now),
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
        "compact_candles_15": compact_candles,
    }
    if forming_candle is not None:
        summary["forming_candle"] = forming_candle
    return summary


def _build_level_candidates(
    htf_summary: dict[str, Any],
    ltf_summary: dict[str, Any],
    last_price: float,
    is_scalp: bool = False,
) -> dict[str, Any]:
    """Pre-compute deterministic SL/TP candidates and resulting R:R ratios from market_price."""
    ltf_atr = float(ltf_summary.get("atr14") or 0.0)
    htf_atr = float(htf_summary.get("atr14") or 0.0)
    ref = last_price if last_price > 0 else float(ltf_summary.get("close") or 0.0)

    # Scalp buffer: 0.8-1.2x ATR, Default/Swing: 0.5-1.0x ATR
    atr_tight = 0.8 if is_scalp else 0.5
    atr_swing = 1.2 if is_scalp else 1.0

    def _rr(entry: float, sl: float, tp: float) -> Optional[float]:
        risk = abs(entry - sl)
        if risk <= 0:
            return None
        return round(abs(tp - entry) / risk, 2)

    long_sl_tight = round(float(ltf_summary["recent_swing_low"]) - atr_tight * ltf_atr, 8)
    long_sl_swing = round(float(ltf_summary["recent_swing_low"]) - atr_swing * ltf_atr, 8)
    long_tp_1 = round(float(ltf_summary["nearest_resistance"]), 8)
    long_tp_2 = round(float(htf_summary["nearest_resistance"]), 8)
    long_tp_3 = round(ref + 3.0 * htf_atr, 8) if htf_atr > 0 else long_tp_2

    short_sl_tight = round(float(ltf_summary["recent_swing_high"]) + atr_tight * ltf_atr, 8)
    short_sl_swing = round(float(ltf_summary["recent_swing_high"]) + atr_swing * ltf_atr, 8)
    short_tp_1 = round(float(ltf_summary["nearest_support"]), 8)
    short_tp_2 = round(float(htf_summary["nearest_support"]), 8)
    short_tp_3 = round(max(1e-8, ref - 3.0 * htf_atr), 8) if htf_atr > 0 else short_tp_2

    return {
        "reference_price": round(ref, 8),
        "long": {
            "entry_limit_ema21": ltf_summary["ema21"],
            "sl_candidates": {"swing_tight": long_sl_tight, "swing_swing": long_sl_swing},
            "tp_candidates": {"ltf_res": long_tp_1, "htf_res": long_tp_2, "htf_3atr": long_tp_3},
            "rr_from_market_vs_sl": {
                "tp_ltf_res": _rr(ref, long_sl_tight, long_tp_1) if long_sl_tight < ref < long_tp_1 else None,
                "tp_htf_res": _rr(ref, long_sl_tight, long_tp_2) if long_sl_tight < ref < long_tp_2 else None,
                "tp_htf_3atr": _rr(ref, long_sl_tight, long_tp_3) if long_sl_tight < ref < long_tp_3 else None,
            },
        },
        "short": {
            "entry_limit_ema21": ltf_summary["ema21"],
            "sl_candidates": {"swing_tight": short_sl_tight, "swing_swing": short_sl_swing},
            "tp_candidates": {"ltf_sup": short_tp_1, "htf_sup": short_tp_2, "htf_3atr": short_tp_3},
            "rr_from_market_vs_sl": {
                "tp_ltf_sup": _rr(ref, short_sl_tight, short_tp_1) if short_tp_1 < ref < short_sl_tight else None,
                "tp_htf_sup": _rr(ref, short_sl_tight, short_tp_2) if short_tp_2 < ref < short_sl_tight else None,
                "tp_htf_3atr": _rr(ref, short_sl_tight, short_tp_3) if short_tp_3 < ref < short_sl_tight else None,
            },
        },
    }


def prescreen_for_strategy(
    strategy: str,
    htf_summary: dict[str, Any],
    ltf_summary: dict[str, Any],
    risk_profile: str = "CONSERVATIVE",
) -> tuple[bool, str]:
    """Deterministic fast-fail rules mirroring hard NO_TRADE conditions in each strategy prompt.

    Runs before the LLM call so obviously non-qualifying pairs don't consume tokens.
    Only rules that the prompts already treat as mandatory NO_TRADE are enforced here.
    Volume thresholds are relaxed for MODERATE/AGGRESSIVE because those risk profiles
    explicitly override secondary volume requirements in the LLM instructions.
    """
    strat = strategy.strip().upper()
    profile = (risk_profile or "CONSERVATIVE").strip().upper()
    if strat == "TREND_PULLBACK":
        if htf_summary.get("ema_bias") == "FLAT_RANGING":
            return False, "HTF FLAT_RANGING: tidak ada arah tren untuk pullback"
    elif strat == "BREAKOUT_MOMENTUM":
        min_vr = {"MODERATE": 1.0, "AGGRESSIVE": 0.8}.get(profile, 1.2)
        vr = float(ltf_summary.get("volume_ratio") or 0.0)
        if vr < min_vr:
            return False, f"LTF volume_ratio {vr:.2f} < {min_vr:.2f} (syarat konfirmasi breakout)"
    elif strat == "MEAN_REVERSION_SCALP":
        vr = float(ltf_summary.get("volume_ratio") or 0.0)
        if vr >= 1.8:
            return False, f"LTF volume_ratio {vr:.2f} >= 1.80 (ekspansi bervolume, bukan kondisi range)"
    return True, "OK"


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
    now_ts: int | None = None,
    contract: dict[str, Any] | None = None,
    market_context: dict[str, Any] | None = None,
) -> tuple[bool, str, Optional[dict[str, Any]]]:
    """Run lightweight pre-filters and build structured multi-timeframe AI snapshot."""
    min_atr = settings.min_atr_pct if min_atr_pct is None else min_atr_pct
    max_atr = settings.max_atr_pct if max_atr_pct is None else max_atr_pct
    htf_iv = htf_interval or settings.htf_interval
    ltf_iv = ltf_interval or settings.ltf_interval

    htf_closed, _ = filter_closed_candles(htf_candles, htf_iv, now_ts=now_ts)
    ltf_closed, _ = filter_closed_candles(ltf_candles, ltf_iv, now_ts=now_ts)
    if len(htf_closed) < min_candles or len(ltf_closed) < min_candles:
        return False, f"Insufficient closed candles (htf={len(htf_closed)}, ltf={len(ltf_closed)})", None

    htf_summary = summarize_timeframe(htf_candles, htf_iv, now_ts=now_ts)
    ltf_summary = summarize_timeframe(ltf_candles, ltf_iv, now_ts=now_ts)

    ltf_atr_pct = ltf_summary["atr_pct"]
    if ltf_atr_pct < min_atr:
        return False, f"Low volatility pre-filter (LTF ATR% {ltf_atr_pct:.3f} < {min_atr})", None
    if ltf_atr_pct > max_atr:
        return False, f"Extreme volatility pre-filter (LTF ATR% {ltf_atr_pct:.3f} > {max_atr})", None

    vol_24h_quote = float(ticker.get("amount24") or 0.0)
    if vol_24h_quote <= 0:
        return False, "Zero 24h quote volume", None

    last_price = float(ticker.get("lastPrice") or ltf_summary["close"])
    funding_rate = float(ticker.get("fundingRate") or 0.0)
    hold_vol = float(ticker.get("holdVol") or 0.0)
    contract_size = float((contract or {}).get("contractSize") or 0.0)
    oi_usdt = round(hold_vol * contract_size * last_price, 2) if (contract_size > 0 and last_price > 0) else None
    oi_to_vol = round(oi_usdt / vol_24h_quote, 3) if (oi_usdt is not None and vol_24h_quote > 0) else None

    market_ticker: dict[str, Any] = {
        "last_price": last_price,
        "fair_price": float(ticker.get("fairPrice") or 0.0),
        "index_price": float(ticker.get("indexPrice") or 0.0),
        "change_24h_pct": round(float(ticker.get("riseFallRate") or 0.0) * 100.0, 3),
        "quote_volume_24h": round(vol_24h_quote, 2),
        "funding_rate": funding_rate,
        "funding_rate_pct": round(funding_rate * 100.0, 4),
        "funding_extreme": abs(funding_rate) >= 0.0005,
        "open_interest_hold_vol": hold_vol,
        "high_24h": float(ticker.get("high24Price") or 0.0),
        "low_24h": float(ticker.get("lower24Price") or 0.0),
    }
    if oi_usdt is not None:
        market_ticker["open_interest_usdt"] = oi_usdt
        market_ticker["oi_to_volume_ratio"] = oi_to_vol

    snapshot: dict[str, Any] = {
        "symbol": symbol,
        "market_ticker": market_ticker,
        "htf_1h": htf_summary,
        "ltf_15m": ltf_summary,
        "level_candidates": _build_level_candidates(
            htf_summary,
            ltf_summary,
            last_price,
            # LTF <= Min5 dipakai strategi scalp: wick/stop-hunt lebih sering, SL butuh buffer ATR lebih lebar.
            is_scalp=INTERVAL_SECONDS_MAP.get(ltf_iv, 900) <= 300,
        ),
    }
    if market_context is not None:
        snapshot["market_context"] = market_context
    return True, "OK", snapshot
