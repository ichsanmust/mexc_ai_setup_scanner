"""BTC_USDT Market Mover scanner and strategy/settings advisor."""

import asyncio
from datetime import datetime, timezone
import json
import logging
from typing import Any, Optional

from sqlalchemy.orm import Session

from ..models import AppSetting, Strategy
from ..scanner.features import filter_closed_candles, summarize_timeframe
from ..scanner.mexc_public import MexcPublicClient
from .runtime_settings import resolve_runtime_settings

log = logging.getLogger(__name__)

BTC_SYMBOL = "BTC_USDT"
LATEST_BTC_MOVER_KEY = "latest_btc_market_mover"

# Timeframe pairs per trading style: Scalp, Intraday (Harian), Swing (Beberapa Hari)
BTC_STYLE_PROFILES: dict[str, dict[str, str]] = {
    "SCALP": {
        "label": "Scalp (1–6 Jam)",
        "htf": "Min30",
        "ltf": "Min5",
    },
    "INTRADAY": {
        "label": "Intraday / Harian (4–24 Jam)",
        "htf": "Min60",
        "ltf": "Min15",
    },
    "SWING": {
        "label": "Swing (1–5 Hari)",
        "htf": "Hour4",
        "ltf": "Min60",
    },
}

BTC_SCAN_INTERVALS: list[tuple[str, int]] = [
    ("Min5", 250),
    ("Min15", 250),
    ("Min30", 250),
    ("Min60", 250),
    ("Hour4", 220),
    ("Day1", 120),
]


def _classify_volatility(atr_pct: float, interval: str) -> str:
    """Classify BTC volatility state normalized to the timeframe."""
    if interval == "Min5":
        low, elevated, extreme = 0.14, 0.55, 0.95
    elif interval == "Min15":
        low, elevated, extreme = 0.22, 0.95, 1.50
    elif interval == "Min30":
        low, elevated, extreme = 0.32, 1.25, 2.00
    elif interval == "Min60":
        low, elevated, extreme = 0.45, 1.75, 2.80
    else:
        low, elevated, extreme = 0.90, 3.20, 5.00

    if atr_pct < low:
        return "LOW"
    if atr_pct >= extreme:
        return "EXTREME"
    if atr_pct >= elevated:
        return "ELEVATED"
    return "NORMAL"


def _compact_tf(summary: dict[str, Any]) -> dict[str, Any]:
    """Extract compact technical metrics from a timeframe summary."""
    return {
        "interval": summary["interval"],
        "close": summary["close"],
        "ema_bias": summary["ema_bias"],
        "ema21_slope_pct": summary["ema21_slope_pct"],
        "ema50_slope_pct": summary["ema50_slope_pct"],
        "rsi14": summary["rsi14"],
        "dss": summary["dss"],
        "dss_signal": summary["dss_signal"],
        "atr_pct": summary["atr_pct"],
        "volume_ratio": summary["volume_ratio"],
        "compression_ratio": summary["compression_ratio"],
        "structure_bias": summary["structure_bias"],
        "nearest_support": summary["nearest_support"],
        "nearest_resistance": summary["nearest_resistance"],
        "dist_to_support_pct": summary["dist_to_support_pct"],
        "dist_to_resistance_pct": summary["dist_to_resistance_pct"],
    }


def _evaluate_style(
    style_key: str,
    label: str,
    htf_sum: dict[str, Any] | None,
    ltf_sum: dict[str, Any] | None,
) -> dict[str, Any]:
    """Determine regime, bias, volatility, and Indonesian summary for one trading style."""
    primary = htf_sum or ltf_sum
    exec_tf = ltf_sum or htf_sum
    if not primary or not exec_tf:
        return {
            "style": style_key,
            "label": label,
            "available": False,
            "regime": "UNKNOWN",
            "bias": "NEUTRAL",
            "volatility_state": "NORMAL",
            "htf": None,
            "ltf": None,
            "summary": "Data candle BTC_USDT belum mencukupi untuk timeframe ini.",
        }

    vol_state = _classify_volatility(float(exec_tf["atr_pct"]), exec_tf["interval"])
    htf_ema = primary["ema_bias"]
    htf_struct = primary["structure_bias"]
    htf_slope = float(primary["ema21_slope_pct"])
    ltf_ema = exec_tf["ema_bias"]
    ltf_slope = float(exec_tf["ema21_slope_pct"])
    ltf_rsi = float(exec_tf["rsi14"])
    comp = float(exec_tf["compression_ratio"])

    bull_score = 0
    bear_score = 0
    if htf_ema == "BULLISH_ALIGNED":
        bull_score += 2
    elif htf_ema == "BEARISH_ALIGNED":
        bear_score += 2
    if htf_struct == "BULLISH":
        bull_score += 1
    elif htf_struct == "BEARISH":
        bear_score += 1
    if htf_slope > 0.08:
        bull_score += 1
    elif htf_slope < -0.08:
        bear_score += 1
    if ltf_ema == "BULLISH_ALIGNED" or ltf_slope > 0.06:
        bull_score += 1
    elif ltf_ema == "BEARISH_ALIGNED" or ltf_slope < -0.06:
        bear_score += 1

    if vol_state == "EXTREME":
        regime = "HIGH_VOLATILITY"
        bias = "BULLISH" if bull_score > bear_score + 1 else ("BEARISH" if bear_score > bull_score + 1 else "NEUTRAL")
    elif htf_ema == "FLAT_RANGING" or (abs(htf_slope) < 0.05 and abs(ltf_slope) < 0.05):
        regime = "RANGING"
        bias = "NEUTRAL"
    elif bull_score >= 3 and bull_score > bear_score + 1:
        regime = "TRENDING_UP"
        bias = "BULLISH"
    elif bear_score >= 3 and bear_score > bull_score + 1:
        regime = "TRENDING_DOWN"
        bias = "BEARISH"
    else:
        regime = "MIXED"
        bias = "BULLISH" if bull_score > bear_score else ("BEARISH" if bear_score > bull_score else "NEUTRAL")

    if regime == "TRENDING_UP":
        summary = (
            f"BTC tren naik pada {primary['interval']}/{exec_tf['interval']} "
            f"(EMA {htf_ema}, RSI {ltf_rsi:.1f}). Fokus setup searah tren / pullback LONG."
        )
    elif regime == "TRENDING_DOWN":
        summary = (
            f"BTC tren turun pada {primary['interval']}/{exec_tf['interval']} "
            f"(EMA {htf_ema}, RSI {ltf_rsi:.1f}). Waspadai LONG altcoin; utamakan pullback SHORT."
        )
    elif regime == "HIGH_VOLATILITY":
        summary = (
            f"Volatilitas BTC ekstrem (ATR {exec_tf['atr_pct']:.2f}% di {exec_tf['interval']}). "
            "Risiko sweep/whipsaw tinggi — perketat filter & hindari entry agresif."
        )
    elif regime == "RANGING":
        squeeze_note = " Ada kompresi range (potensi breakout)." if comp <= 0.48 else ""
        summary = (
            f"BTC bergerak sideways/ranging (slope {htf_slope:+.2f}%, RSI {ltf_rsi:.1f})."
            f"{squeeze_note} Cocok untuk mean-reversion di area S/R."
        )
    else:
        summary = (
            f"Struktur BTC transisi/mixed ({htf_ema} vs {ltf_ema}, RSI {ltf_rsi:.1f}). "
            "Pilih setup dengan konfirmasi volume & R:R ketat."
        )

    return {
        "style": style_key,
        "label": label,
        "available": True,
        "regime": regime,
        "bias": bias,
        "volatility_state": vol_state,
        "htf": _compact_tf(primary),
        "ltf": _compact_tf(exec_tf),
        "summary": summary,
    }


def build_btc_context_for_ranking(report: dict[str, Any] | None) -> dict[str, Any] | None:
    """Compact BTC regime summary for AI pair ranking, from a persisted market mover report."""
    if not isinstance(report, dict):
        return None
    btc = report.get("btc") or {}
    if not btc or not btc.get("overall_regime"):
        return None
    advisor = report.get("advisor") or {}
    suggested = advisor.get("suggested_settings") or {}
    styles = btc.get("styles") or {}
    return {
        "scanned_at": btc.get("scanned_at"),
        "last_price": btc.get("last_price"),
        "change_24h_pct": btc.get("change_24h_pct"),
        "overall_regime": btc.get("overall_regime"),
        "overall_bias": btc.get("overall_bias"),
        "volatility_state": btc.get("volatility_state"),
        "funding_extreme": btc.get("funding_extreme"),
        "styles": {
            key: {"regime": (v or {}).get("regime"), "bias": (v or {}).get("bias")}
            for key, v in styles.items()
        },
        "suggested_styles": suggested.get("recommended_styles"),
    }


def load_btc_context_for_ranking(db: Session) -> dict[str, Any] | None:
    """Load the latest persisted BTC market mover scan (no network call) for AI pair ranking."""
    row = db.query(AppSetting).filter(AppSetting.key == LATEST_BTC_MOVER_KEY).first()
    if not row or not row.value:
        return None
    try:
        report = json.loads(row.value)
    except (ValueError, TypeError):
        return None
    return build_btc_context_for_ranking(report)


def analyze_btc_market_mover(
    candles_by_iv: dict[str, list[dict[str, Any]]],
    ticker: dict[str, Any] | None = None,
    now_ts: int | None = None,
) -> dict[str, Any]:
    """Build deterministic multi-timeframe BTC_USDT Market Mover analysis."""
    tf_summaries: dict[str, dict[str, Any]] = {}
    for iv, candles in candles_by_iv.items():
        if not candles:
            continue
        closed, _ = filter_closed_candles(candles, iv, now_ts=now_ts)
        if len(closed) >= 35:
            tf_summaries[iv] = summarize_timeframe(candles, iv, now_ts=now_ts)

    styles: dict[str, dict[str, Any]] = {}
    for style_key, meta in BTC_STYLE_PROFILES.items():
        styles[style_key] = _evaluate_style(
            style_key=style_key,
            label=meta["label"],
            htf_sum=tf_summaries.get(meta["htf"]),
            ltf_sum=tf_summaries.get(meta["ltf"]),
        )

    intraday = styles.get("INTRADAY") or {}
    swing = styles.get("SWING") or {}
    scalp = styles.get("SCALP") or {}

    # Primary market-mover regime anchors on Intraday (Min60/Min15), falling back to Scalp or Swing
    anchor = (
        intraday
        if intraday.get("available")
        else (scalp if scalp.get("available") else swing)
    )
    overall_regime = anchor.get("regime", "UNKNOWN")
    overall_bias = anchor.get("bias", "NEUTRAL")
    volatility_state = anchor.get("volatility_state", "NORMAL")

    # If Swing & Intraday agree on direction while anchor was MIXED, elevate clarity
    if overall_regime == "MIXED" and swing.get("available") and swing.get("regime") in {"TRENDING_UP", "TRENDING_DOWN"}:
        overall_bias = swing.get("bias", overall_bias)

    t = ticker or {}
    last_price = float(t.get("lastPrice") or 0.0)
    if last_price <= 0:
        for iv in ("Min5", "Min15", "Min30", "Min60", "Hour4", "Day1"):
            if iv in tf_summaries:
                last_price = float(tf_summaries[iv]["close"])
                break

    change_24h_pct = round(float(t.get("riseFallRate") or 0.0) * 100.0, 2)
    quote_vol_24h = round(float(t.get("amount24") or 0.0), 2)
    funding_rate = float(t.get("fundingRate") or 0.0)
    funding_rate_pct = round(funding_rate * 100.0, 4)

    macro_day = _compact_tf(tf_summaries["Day1"]) if "Day1" in tf_summaries else None

    return {
        "symbol": BTC_SYMBOL,
        "scanned_at": datetime.now(timezone.utc).isoformat(),
        "last_price": round(last_price, 2) if last_price > 100 else round(last_price, 6),
        "change_24h_pct": change_24h_pct,
        "quote_volume_24h": quote_vol_24h,
        "funding_rate_pct": funding_rate_pct,
        "funding_extreme": abs(funding_rate) >= 0.0005,
        "overall_regime": overall_regime,
        "overall_bias": overall_bias,
        "volatility_state": volatility_state,
        "styles": styles,
        "macro_day1": macro_day,
    }


def _classify_strategy_bucket(strat_name: str, trade_style: str | None) -> str:
    """Map strategy name or trade_style to SCALP, TREND, or BREAKOUT bucket."""
    name_up = (strat_name or "").strip().upper()
    style_up = (trade_style or "").strip().upper()
    if "MEAN_REVERSION" in name_up or "SCALP" in name_up or style_up == "SCALP":
        return "SCALP"
    if "BREAKOUT" in name_up:
        return "BREAKOUT"
    if "TREND" in name_up or "PULLBACK" in name_up:
        return "TREND"
    if "SWING" in style_up:
        return "TREND"
    return "TREND"


def build_btc_strategy_advisor(
    btc_analysis: dict[str, Any],
    runtime_settings: dict[str, Any],
    db_strategies: list[Strategy] | None = None,
) -> dict[str, Any]:
    """Conclude current scan strategy settings and generate BTC-aligned setting suggestions."""
    regime = btc_analysis.get("overall_regime", "UNKNOWN")
    vol_state = btc_analysis.get("volatility_state", "NORMAL")
    funding_extreme = bool(btc_analysis.get("funding_extreme", False))
    styles = btc_analysis.get("styles") or {}
    scalp_info = styles.get("SCALP") or {}
    intraday_info = styles.get("INTRADAY") or {}
    swing_info = styles.get("SWING") or {}

    ltf_intraday = intraday_info.get("ltf") or {}
    comp_ratio = float(ltf_intraday.get("compression_ratio") or 0.6)
    vol_ratio = float(ltf_intraday.get("volume_ratio") or 1.0)
    intraday_atr = float(ltf_intraday.get("atr_pct") or 0.5)

    active_list = [str(s).strip().upper() for s in (runtime_settings.get("active_strategies") or []) if str(s).strip()]
    curr_risk = str(runtime_settings.get("risk_profile") or "CONSERVATIVE").upper()
    curr_conf = int(runtime_settings.get("min_confidence") or 75)
    curr_min_atr = float(runtime_settings.get("min_atr_pct") or 0.25)
    curr_max_atr = float(runtime_settings.get("max_atr_pct") or 8.0)
    curr_interval = int(runtime_settings.get("scan_interval_minutes") or 15)
    curr_top_n = int(runtime_settings.get("top_n_pairs") or 30)

    # Determine ideal regime posture
    recommended_buckets: set[str] = set()
    recommended_styles: list[str] = []
    suggested_risk = "CONSERVATIVE"
    suggested_conf = 75
    suggested_min_atr = 0.25
    suggested_max_atr = 8.0
    suggested_interval = curr_interval

    if regime in {"TRENDING_UP", "TRENDING_DOWN"}:
        recommended_buckets.add("TREND")
        recommended_styles.append("INTRADAY")
        if swing_info.get("regime") == regime:
            recommended_styles.append("SWING")
        if comp_ratio <= 0.62 or vol_ratio >= 1.2:
            recommended_buckets.add("BREAKOUT")
        suggested_risk = "MODERATE" if (vol_state == "NORMAL" and not funding_extreme) else "CONSERVATIVE"
        suggested_conf = 75 if vol_state == "NORMAL" else 80
        suggested_min_atr = 0.25
        suggested_max_atr = 8.0
        suggested_interval = 15
        regime_headline = (
            f"BTC sedang {regime.replace('_', ' ')} — market mover searah. "
            "Strategi Trend Pullback & Breakout searah tren paling efektif."
        )
    elif regime == "RANGING":
        recommended_buckets.add("SCALP")
        recommended_styles.append("SCALP")
        if comp_ratio <= 0.48:
            recommended_buckets.add("BREAKOUT")
            recommended_styles.append("INTRADAY")
        suggested_risk = "CONSERVATIVE" if vol_state in {"ELEVATED", "EXTREME"} else "MODERATE"
        suggested_conf = 78
        suggested_min_atr = 0.20 if vol_state == "LOW" else 0.25
        suggested_max_atr = 7.0
        suggested_interval = 10 if curr_interval > 15 else curr_interval
        regime_headline = (
            "BTC sedang RANGING / sideways — peluang terbaik ada di Scalp / Mean Reversion pada area S/R"
            + (" (waspadai squeeze breakout)." if comp_ratio <= 0.48 else ".")
        )
    elif regime == "HIGH_VOLATILITY" or vol_state == "EXTREME" or funding_extreme:
        recommended_buckets.add("TREND")
        recommended_styles.append("INTRADAY")
        suggested_risk = "CONSERVATIVE"
        suggested_conf = 82
        suggested_min_atr = 0.35
        suggested_max_atr = 10.0
        suggested_interval = 15
        regime_headline = (
            "BTC dalam kondisi volatilitas tinggi / funding ekstrem — "
            "gunakan mode CONSERVATIVE, Min Confidence tinggi, dan hindari over-trading."
        )
    else:
        # MIXED / UNKNOWN
        recommended_buckets.update({"TREND", "SCALP"})
        recommended_styles.extend(["SCALP", "INTRADAY"])
        suggested_risk = "CONSERVATIVE"
        suggested_conf = 78
        suggested_min_atr = 0.20 if vol_state == "LOW" else 0.25
        suggested_max_atr = 8.0
        suggested_interval = 15
        regime_headline = (
            "BTC sedang transisi / mixed antar timeframe — "
            "gunakan filter CONSERVATIVE dan pilih setup dengan konfirmasi S/R & volume jelas."
        )

    if vol_state == "LOW" and intraday_atr > 0:
        suggested_min_atr = min(suggested_min_atr, 0.18)

    # Evaluate every strategy registered in DB (or fallback to active_list)
    strat_recs: list[dict[str, Any]] = []
    suggested_active_strategies: list[str] = []

    if db_strategies:
        for row in db_strategies:
            s_name = row.name.strip().upper()
            bucket = _classify_strategy_bucket(s_name, row.trade_style)
            should_be_active = bucket in recommended_buckets
            is_currently_active = s_name in active_list
            if should_be_active:
                suggested_active_strategies.append(s_name)

            if should_be_active and is_currently_active:
                action = "PERTAHANKAN"
                reason = f"Selaras dengan kondisi BTC ({regime})."
            elif should_be_active and not is_currently_active:
                action = "AKTIFKAN"
                reason = f"Direkomendasikan aktif karena BTC sedang {regime}."
            elif not should_be_active and is_currently_active:
                action = "NONAKTIFKAN_SEMENTARA"
                reason = (
                    f"Kurang ideal saat BTC {regime} "
                    f"(risiko whipsaw/counter-trend untuk tipe {row.trade_style or bucket})."
                )
            else:
                action = "TETAP_NONAKTIF"
                reason = f"Belum diperlukan pada regime BTC {regime}."

            strat_recs.append(
                {
                    "name": s_name,
                    "display_name": row.display_name,
                    "trade_style": row.trade_style or bucket,
                    "holding_period": row.holding_period or "-",
                    "currently_active": is_currently_active,
                    "recommended_active": should_be_active,
                    "action": action,
                    "reason": reason,
                }
            )
    else:
        suggested_active_strategies = list(active_list)

    # Guarantee at least 1 active strategy in suggestion
    if not suggested_active_strategies and db_strategies:
        first_name = db_strategies[0].name.strip().upper()
        suggested_active_strategies = [first_name]
        for rec in strat_recs:
            if rec["name"] == first_name:
                rec["recommended_active"] = True
                rec["action"] = "PERTAHANKAN" if rec["currently_active"] else "AKTIFKAN"

    # Build diffs between current settings and suggested settings
    diffs: list[dict[str, Any]] = []
    if set(active_list) != set(suggested_active_strategies):
        diffs.append(
            {
                "field": "active_strategies",
                "label": "Strategi Aktif",
                "current": ", ".join(active_list) or "-",
                "suggested": ", ".join(suggested_active_strategies),
                "reason": regime_headline,
            }
        )
    if curr_risk != suggested_risk:
        diffs.append(
            {
                "field": "risk_profile",
                "label": "Risk Profile",
                "current": curr_risk,
                "suggested": suggested_risk,
                "reason": (
                    "Lebih aman menghadapi volatilitas/transisi BTC."
                    if suggested_risk == "CONSERVATIVE"
                    else "Tren BTC cukup bersih untuk toleransi pullback moderat."
                ),
            }
        )
    if curr_conf != suggested_conf:
        diffs.append(
            {
                "field": "min_confidence",
                "label": "Min Confidence (%)",
                "current": curr_conf,
                "suggested": suggested_conf,
                "reason": "Menjaga kualitas sinyal sesuai tingkat kejelasan struktur BTC.",
            }
        )
    if round(curr_min_atr, 2) != round(suggested_min_atr, 2):
        diffs.append(
            {
                "field": "min_atr_pct",
                "label": "Min ATR (%)",
                "current": curr_min_atr,
                "suggested": suggested_min_atr,
                "reason": (
                    "Turunkan batas ATR agar pair likuid tetap lolos saat market sepi."
                    if suggested_min_atr < curr_min_atr
                    else "Naikkan batas ATR minimum untuk menghindari pair stagnan saat BTC volatil."
                ),
            }
        )
    if round(curr_max_atr, 2) != round(suggested_max_atr, 2):
        diffs.append(
            {
                "field": "max_atr_pct",
                "label": "Max ATR (%)",
                "current": curr_max_atr,
                "suggested": suggested_max_atr,
                "reason": "Menyesuaikan toleransi volatilitas ekstrem.",
            }
        )
    if curr_interval != suggested_interval:
        diffs.append(
            {
                "field": "scan_interval_minutes",
                "label": "Interval Scan (Menit)",
                "current": curr_interval,
                "suggested": suggested_interval,
                "reason": "Menyesuaikan frekuensi scan dengan fokus Scalp/Intraday.",
            }
        )

    alignment = "SELARAS" if not diffs else ("PERLU_PENYESUAIAN" if len(diffs) <= 2 else "KURANG_OPTIMAL")
    current_conclusion = (
        f"Run scan saat ini memakai strategi [{', '.join(active_list) or '-'}], "
        f"Risk Profile {curr_risk}, Min Confidence {curr_conf}%, "
        f"ATR {curr_min_atr}%–{curr_max_atr}%, Top {curr_top_n} pair (interval {curr_interval}m). "
        + (
            "Settingan sudah selaras dengan kondisi BTC_USDT saat ini."
            if not diffs
            else f"Terdapat {len(diffs)} penyesuaian yang disarankan agar selaras dengan kondisi BTC_USDT."
        )
    )

    patch_payload: dict[str, Any] = {
        "active_strategies": suggested_active_strategies,
        "risk_profile": suggested_risk,
        "min_confidence": suggested_conf,
        "min_atr_pct": suggested_min_atr,
        "max_atr_pct": suggested_max_atr,
        "scan_interval_minutes": suggested_interval,
    }

    return {
        "alignment": alignment,
        "current_summary": {
            "active_strategies": active_list,
            "risk_profile": curr_risk,
            "min_confidence": curr_conf,
            "min_atr_pct": curr_min_atr,
            "max_atr_pct": curr_max_atr,
            "top_n_pairs": curr_top_n,
            "scan_interval_minutes": curr_interval,
            "conclusion": current_conclusion,
        },
        "suggested_settings": {
            "headline": regime_headline,
            "recommended_styles": recommended_styles,
            "active_strategies": suggested_active_strategies,
            "risk_profile": suggested_risk,
            "min_confidence": suggested_conf,
            "min_atr_pct": suggested_min_atr,
            "max_atr_pct": suggested_max_atr,
            "scan_interval_minutes": suggested_interval,
            "strategy_recommendations": strat_recs,
            "diffs": diffs,
            "patch_payload": patch_payload,
        },
    }


def save_latest_btc_market_mover(db: Session, report: dict[str, Any]) -> None:
    """Persist latest BTC Market Mover scan JSON in app_settings."""
    raw = json.dumps(report, ensure_ascii=False)
    row = db.query(AppSetting).filter(AppSetting.key == LATEST_BTC_MOVER_KEY).first()
    if row:
        row.value = raw
    else:
        db.add(
            AppSetting(
                key=LATEST_BTC_MOVER_KEY,
                value=raw,
                description="Hasil scan BTC_USDT Market Mover & sugesti settingan terbaru",
            )
        )
    db.commit()


def load_latest_btc_market_mover(db: Session) -> Optional[dict[str, Any]]:
    """Load latest persisted BTC Market Mover report and refresh advisor against current settings."""
    row = db.query(AppSetting).filter(AppSetting.key == LATEST_BTC_MOVER_KEY).first()
    if not row or not row.value:
        return None
    try:
        report = json.loads(row.value)
    except (ValueError, TypeError):
        return None
    if not isinstance(report, dict) or "btc" not in report:
        return None

    rt_cfg = resolve_runtime_settings(db)
    db_strats = db.query(Strategy).order_by(Strategy.id.asc()).all()
    report["advisor"] = build_btc_strategy_advisor(report["btc"], rt_cfg, db_strats)
    return report


async def scan_btc_market_mover(
    db: Session,
    rt_cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Fetch live BTC_USDT multi-timeframe data from MEXC and produce Market Mover + Advisor report."""
    cfg = rt_cfg or resolve_runtime_settings(db)
    async with MexcPublicClient(
        base_url=cfg["mexc_base_url"],
        proxy_url=cfg["mexc_proxy_url"],
        max_concurrency=cfg["mexc_max_concurrency"],
    ) as mexc:
        tickers_task = mexc.get_all_tickers()
        kline_tasks = [mexc.get_kline(BTC_SYMBOL, interval=iv, limit=lim) for iv, lim in BTC_SCAN_INTERVALS]
        results = await asyncio.gather(tickers_task, *kline_tasks)

    tickers = results[0] if isinstance(results[0], dict) else {}
    btc_ticker = tickers.get(BTC_SYMBOL)
    candles_by_iv = {iv: candles for (iv, _), candles in zip(BTC_SCAN_INTERVALS, results[1:])}

    btc_analysis = analyze_btc_market_mover(candles_by_iv, ticker=btc_ticker)
    db_strats = db.query(Strategy).order_by(Strategy.id.asc()).all()
    advisor = build_btc_strategy_advisor(btc_analysis, cfg, db_strats)

    report = {
        "btc": btc_analysis,
        "advisor": advisor,
    }
    save_latest_btc_market_mover(db, report)
    return report
