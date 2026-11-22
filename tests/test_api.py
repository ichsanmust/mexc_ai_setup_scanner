"""Integration tests for FastAPI dashboard, setups, analytics, and MySQL AI models/settings APIs."""

from datetime import timedelta
from decimal import Decimal

from app.models import TradeSetup, utcnow


def test_health_and_ai_models_crud_and_settings(api_client):
    # 1. Health check
    resp = api_client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "online"

    # 2. List seeded AI models
    models_resp = api_client.get("/api/ai/models")
    assert models_resp.status_code == 200
    payload = models_resp.json()
    assert len(payload["models"]) >= 4

    # 3. Create custom model for openrouter
    create_resp = api_client.post(
        "/api/ai/models",
        json={
            "name": "My Custom Qwen",
            "model_id": "qwen/qwen-2.5-72b-instruct",
            "provider": "openrouter",
            "description": "Custom test model",
        },
    )
    assert create_resp.status_code == 201
    created = create_resp.json()
    assert created["is_custom"] is True

    # 4. Activate the newly created model -> syncs active_provider to openrouter
    act_resp = api_client.post(f"/api/ai/models/{created['id']}/activate")
    assert act_resp.status_code == 200
    assert act_resp.json()["active_model"]["is_active"] is True
    assert act_resp.json()["settings"]["active_provider"] == "openrouter"

    # 5. Update provider API keys and switch provider back to commandcode
    set_resp = api_client.post(
        "/api/ai/settings",
        json={
            "active_provider": "commandcode",
            "commandcode_api_key": "sk-cmd-1234567890abcd",
            "openrouter_api_key": "sk-or-1234567890wxyz",
        },
    )
    assert set_resp.status_code == 200
    s_data = set_resp.json()
    assert s_data["active_provider"] == "commandcode"
    assert s_data["has_commandcode_api_key"] is True
    assert s_data["has_openrouter_api_key"] is True
    assert "sk-cmd-1" in s_data["commandcode_api_key_masked"]
    assert "abcd" in s_data["commandcode_api_key_masked"]

    # 6. Deleting an active model is blocked; activating another allows deletion
    del_blocked = api_client.delete(f"/api/ai/models/{created['id']}")
    assert del_blocked.status_code == 400

    first_other = next(m for m in payload["models"] if m["id"] != created["id"])
    api_client.post(f"/api/ai/models/{first_other['id']}/activate")
    del_ok = api_client.delete(f"/api/ai/models/{created['id']}")
    assert del_ok.status_code == 200


def test_setups_listing_manual_status_and_analytics(api_client, db_session):
    db, _, _ = db_session
    now = utcnow()
    from app.models import ScanEvaluation, ScanRun

    run = ScanRun(
        strategy="TREND_PULLBACK",
        llm_provider="commandcode",
        llm_model="google/gemini-2.5-flash",
        total_contracts=50,
        top_pairs_count=2,
        prefiltered_count=2,
        ai_analyzed_count=2,
        setups_created_count=1,
        status="COMPLETED",
        settings_snapshot={
            "scan_mode": "MANUAL",
            "top_n_pairs": 15,
            "strategy_timeframes": {
                "TREND_PULLBACK": {"htf": "Min60", "ltf": "Min15", "kline_limit": 250, "expiry_hours": 12}
            },
        },
        started_at=now,
        finished_at=now,
    )
    db.add(run)
    db.flush()
    db.add(
        ScanEvaluation(
            scan_run_id=run.id,
            symbol="XRP_USDT",
            strategy_used="TREND_PULLBACK",
            raw_decision="NO_TRADE",
            rejection_reason="AI returned NO_TRADE",
            confidence=40,
        )
    )
    db.add_all(
        [
            TradeSetup(
                scan_run_id=run.id,
                symbol="BTC_USDT",
                strategy_used="TREND_PULLBACK",
                decision="LONG",
                market_regime="TRENDING_UP",
                entry_type="LIMIT",
                entry_price=Decimal("90000.0"),
                stop_loss=Decimal("89000.0"),
                take_profit=Decimal("92000.0"),
                risk_reward_ratio=Decimal("2.0"),
                confidence=86,
                llm_provider="commandcode",
                llm_model="google/gemini-2.5-flash",
                invalidation_reason="Break below 89k",
                rationale="Clean pullback",
                status="OPEN",
                expires_at=now + timedelta(hours=10),
                features_snapshot={"ltf_15m": {"rsi14": 48}},
                ai_payload={"decision": "LONG"},
            ),
            TradeSetup(
                symbol="SOL_USDT",
                strategy_used="BREAKOUT_MOMENTUM",
                decision="SHORT",
                market_regime="TRENDING_DOWN",
                entry_type="MARKET",
                entry_price=Decimal("200.0"),
                stop_loss=Decimal("205.0"),
                take_profit=Decimal("188.0"),
                risk_reward_ratio=Decimal("2.4"),
                confidence=82,
                llm_provider="openrouter",
                llm_model="openai/gpt-4o-mini",
                invalidation_reason="Reclaim 205",
                rationale="Breakdown with 2x vol",
                status="HIT_TP",
                expires_at=now + timedelta(hours=10),
                features_snapshot={},
                ai_payload={},
            ),
        ]
    )
    db.commit()

    list_resp = api_client.get("/api/setups?status=OPEN")
    assert list_resp.status_code == 200
    items = list_resp.json()["items"]
    assert len(items) == 1
    assert items[0]["holding_period"] == "4 - 24 Jam (Intraday)"
    assert items[0]["strategy_profile"]["htf"] == "Min60"
    assert items[0]["scan_run_started_at"] is not None
    assert items[0]["scan_run_settings"]["top_n_pairs"] == 15
    btc_id = items[0]["id"]

    patch_resp = api_client.patch(
        f"/api/setups/{btc_id}/status",
        json={
            "status": "MANUAL_TAKEN",
            "manual_entry_price": 90010.5,
            "manual_notes": "Entered at 90010.5 on MEXC",
        },
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["status"] == "MANUAL_TAKEN"
    assert patch_resp.json()["manual_entry_price"] == 90010.5
    assert patch_resp.json()["manual_notes"] == "Entered at 90010.5 on MEXC"
    # MANUAL_TAKEN is actively tracked by Tracker, so it counts toward Active OPEN
    taken_analytics = api_client.get("/api/analytics/strategies").json()
    assert taken_analytics["open_count"] == 1

    # Closing manually without close price should return 400
    bad_close = api_client.patch(
        f"/api/setups/{btc_id}/status",
        json={"status": "CLOSED_MANUAL_TP"},
    )
    assert bad_close.status_code == 400

    # Close manually with TP price -> counts as Win in strategy analytics
    good_tp = api_client.patch(
        f"/api/setups/{btc_id}/status",
        json={"status": "CLOSED_MANUAL_TP", "resolved_price": 91800.0},
    )
    assert good_tp.status_code == 200
    assert good_tp.json()["status"] == "CLOSED_MANUAL_TP"
    assert good_tp.json()["resolved_price"] == 91800.0

    # Reset back to OPEN (e.g. accidental click recovery) clears manual entry & close prices
    reset_open = api_client.patch(
        f"/api/setups/{btc_id}/status",
        json={"status": "OPEN"},
    )
    assert reset_open.status_code == 200
    assert reset_open.json()["status"] == "OPEN"
    assert reset_open.json()["manual_entry_price"] is None
    assert reset_open.json()["resolved_price"] is None

    # Close manually with CL price -> counts as Loss in analytics (1 TP on SOL, 1 CL on BTC -> 50%)
    good_cl = api_client.patch(
        f"/api/setups/{btc_id}/status",
        json={"status": "CLOSED_MANUAL_CL", "manual_entry_price": 90010.5, "resolved_price": 89200.0},
    )
    assert good_cl.status_code == 200
    assert good_cl.json()["status"] == "CLOSED_MANUAL_CL"
    assert good_cl.json()["manual_entry_price"] == 90010.5
    assert good_cl.json()["resolved_price"] == 89200.0

    analytics = api_client.get("/api/analytics/strategies").json()
    assert analytics["total_setups"] == 2
    assert analytics["overall_win_rate_pct"] == 50.0

    # Verify date filter on /api/setups
    today_str = now.strftime("%Y-%m-%d")
    yesterday_str = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    assert len(api_client.get(f"/api/setups?date={today_str}&tz_offset=0").json()["items"]) == 2
    assert len(api_client.get(f"/api/setups?date={yesterday_str}&tz_offset=0").json()["items"]) == 0

    # Verify paginated /api/scanner/runs and /api/setups limit/offset
    runs_pag = api_client.get("/api/scanner/runs?limit=5&offset=0")
    assert runs_pag.status_code == 200
    assert runs_pag.json()["total"] == 1
    assert len(runs_pag.json()["items"]) == 1

    setups_pag1 = api_client.get("/api/setups?limit=1&offset=0").json()
    setups_pag2 = api_client.get("/api/setups?limit=1&offset=1").json()
    assert setups_pag1["total"] == 2
    assert len(setups_pag1["items"]) == 1
    assert len(setups_pag2["items"]) == 1
    assert setups_pag1["items"][0]["id"] != setups_pag2["items"][0]["id"]

    # Verify scan run evaluations endpoint
    runs = api_client.get("/api/scanner/status").json()["recent_runs"]
    assert len(runs) >= 1
    eval_resp = api_client.get(f"/api/scanner/runs/{runs[0]['id']}/evaluations")
    assert eval_resp.status_code == 200
    eval_data = eval_resp.json()
    assert len(eval_data["evaluations"]) == 1
    assert eval_data["evaluations"][0]["symbol"] == "XRP_USDT"
    assert len(eval_data["setups"]) == 1


def test_dashboard_html_and_chart_endpoint(api_client, monkeypatch):
    html_resp = api_client.get("/")
    assert html_resp.status_code == 200
    assert "MEXC AI Setup Scanner" in html_resp.text

    from app.web import dashboard

    async def fake_get_kline(self, symbol, interval="Min15", limit=250, start_ts=None, end_ts=None):
        return [
            {
                "time": 1_700_000_000 + i * 900,
                "open": 100.0 + i * 0.2,
                "high": 101.0 + i * 0.2,
                "low": 99.5 + i * 0.2,
                "close": 100.5 + i * 0.2,
                "volume": 1200.0,
            }
            for i in range(60)
        ]

    monkeypatch.setattr(dashboard.MexcPublicClient, "get_kline", fake_get_kline)
    chart_resp = api_client.get("/api/charts/BTC_USDT?interval=Min15&limit=50")
    assert chart_resp.status_code == 200
    chart_data = chart_resp.json()
    assert chart_data["symbol"] == "BTC_USDT"
    assert len(chart_data["candles"]) == 50
    assert len(chart_data["ema21"]) == 50
    assert len(chart_data["ema200"]) == 50
    assert len(chart_data["dss"]) == 50
    assert len(chart_data["dss_signal"]) == 50
    assert 0.0 <= chart_data["dss"][-1]["value"] <= 100.0
    assert 0.0 <= chart_data["dss_signal"][-1]["value"] <= 100.0

    # Verify tracker network error returns clean 502 JSON and surfaces in /api/scanner/status
    async def failing_check_open_setups(db, mexc):
        raise RuntimeError("Simulated MEXC connection error")

    monkeypatch.setattr(dashboard, "check_open_setups", failing_check_open_setups)
    tracker_resp = api_client.post("/api/tracker/run")
    assert tracker_resp.status_code == 502
    assert "Simulated MEXC connection error" in tracker_resp.json()["detail"]

    status_resp = api_client.get("/api/scanner/status")
    assert status_resp.status_code == 200
    assert "Simulated MEXC connection error" in status_resp.json()["last_tracker_error"]

    # Verify /api/scanner/run fails fast with HTTP 400 when LLM API key is missing
    scan_resp = api_client.post("/api/scanner/run")
    assert scan_resp.status_code == 400
    assert "API key" in scan_resp.json()["detail"]

    # Verify scanner settings toggle AUTO <-> MANUAL and TOP_N_PAIRS persistence
    get_cfg = api_client.get("/api/scanner/settings")
    assert get_cfg.status_code == 200
    assert get_cfg.json()["scan_mode"] in ("AUTO", "MANUAL")

    upd_cfg = api_client.post(
        "/api/scanner/settings",
        json={
            "auto_scan_enabled": False,
            "scan_interval_minutes": 30,
            "top_n_pairs": 12,
            "mexc_base_url": "https://contract.mexc.fm",
            "active_strategies": ["TREND_PULLBACK"],
            "min_24h_quote_volume": 2_000_000,
            "max_24h_quote_volume": 50_000_000,
            "min_atr_pct": 0.4,
            "min_confidence": 80,
            "llm_timeout_seconds": 60,
            "llm_max_tokens": 2048,
        },
    )
    assert upd_cfg.status_code == 200
    cfg_data = upd_cfg.json()
    assert cfg_data["auto_scan_enabled"] is False
    assert cfg_data["scan_mode"] == "MANUAL"
    assert cfg_data["scan_interval_minutes"] == 30
    assert cfg_data["top_n_pairs"] == 12
    assert cfg_data["mexc_base_url"] == "https://contract.mexc.fm"
    assert cfg_data["active_strategies"] == ["TREND_PULLBACK"]
    assert cfg_data["min_24h_quote_volume"] == 2_000_000
    assert cfg_data["max_24h_quote_volume"] == 50_000_000
    assert cfg_data["min_confidence"] == 80
    assert cfg_data["llm_timeout_seconds"] == 60
    assert cfg_data["llm_max_tokens"] == 2048
    assert "htf_interval" not in cfg_data
    assert "ltf_interval" not in cfg_data

    bad_vol = api_client.post(
        "/api/scanner/settings",
        json={"min_24h_quote_volume": 60_000_000, "max_24h_quote_volume": 10_000_000},
    )
    assert bad_vol.status_code == 400

    st_after = api_client.get("/api/scanner/status").json()
    assert st_after["auto_scan_enabled"] is False
    assert st_after["top_n_pairs"] == 12
    assert st_after["mexc_base_url"] == "https://contract.mexc.fm"


def test_strategies_db_crud_toggle_and_settings_sync(api_client, db_session):
    from app.ai.analyzer import load_strategy_prompt
    from app.core.validator import validate_and_guard_setup
    from app.models import Strategy
    from app.schemas import AISetupDecision

    db, _, _ = db_session

    # 1. Built-in strategies seeded from prompts/ into DB with style & HTF/LTF suggestions
    list_resp = api_client.get("/api/strategies")
    assert list_resp.status_code == 200
    rows = list_resp.json()
    names = {r["name"] for r in rows}
    assert {"TREND_PULLBACK", "BREAKOUT_MOMENTUM", "MEAN_REVERSION_SCALP"}.issubset(names)
    tp_row = next(r for r in rows if r["name"] == "TREND_PULLBACK")
    assert tp_row["trade_style"] == "INTRADAY"
    assert tp_row["suggested_htf"] == "Min60"
    assert tp_row["suggested_ltf"] == "Min15"
    assert tp_row["holding_period"]

    # 2. Create a new custom strategy via API (and check validator/prompt loader use it)
    create_resp = api_client.post(
        "/api/strategies",
        json={
            "name": "scalping rsi",
            "display_name": "Scalping RSI Divergence",
            "description": "Cari divergensi RSI di 15m",
            "trade_style": "SCALP",
            "holding_period": "1 - 4 Jam",
            "suggested_htf": "Min30",
            "suggested_ltf": "Min5",
            "suggested_kline_limit": 250,
            "suggested_expiry_hours": 6,
            "prompt_text": "Anda analis Scalping RSI Divergence. Kembalikan strategy_used='SCALPING_RSI'. Min RR 2.2.",
            "min_rr": 2.2,
            "is_active": True,
        },
    )
    assert create_resp.status_code == 201
    created = create_resp.json()
    assert created["name"] == "SCALPING_RSI"
    assert created["trade_style"] == "SCALP"
    assert created["suggested_htf"] == "Min30"
    assert created["suggested_ltf"] == "Min5"
    assert created["min_rr"] == 2.2
    assert created["is_active"] is True
    assert created["is_builtin"] is False

    # 3. Scanner settings automatically includes newly created active strategy
    cfg = api_client.get("/api/scanner/settings").json()
    assert "SCALPING_RSI" in cfg["active_strategies"]

    # 4. Prompt loader reads from DB and validator enforces custom min_rr (2.2)
    loaded_prompt = load_strategy_prompt("SCALPING_RSI", db=db)
    assert "Scalping RSI Divergence" in loaded_prompt

    low_rr_decision = AISetupDecision(
        symbol="SOL_USDT",
        strategy_used="SCALPING_RSI",
        decision="LONG",
        market_regime="RANGING",
        entry_type="LIMIT",
        entry_price=100.0,
        stop_loss=98.0,
        take_profit=103.5,  # RR = 1.75 < 2.2
        risk_reward_ratio=1.75,
        confidence=85,
        invalidation_reason="Break below 98",
        rationale="Bullish divergence",
    )
    ok, _, reason = validate_and_guard_setup(low_rr_decision, db=db, min_confidence=75)
    assert ok is False
    assert "2.20" in reason

    # 5. Direct SQL insert into strategies table also shows up in Settings & Analytics
    direct_row = Strategy(
        name="ICT_LIQUIDITY",
        display_name="ICT Liquidity Sweep",
        description="Sweep low/high + MSS",
        prompt_text="Evaluasi sweep likuiditas ICT dan kembalikan JSON.",
        min_rr=1.7,
        is_active=True,
        is_builtin=False,
    )
    db.add(direct_row)
    db.commit()

    cfg_after_sql = api_client.get("/api/scanner/settings").json()
    assert "ICT_LIQUIDITY" in cfg_after_sql["active_strategies"]
    analytics = api_client.get("/api/analytics/strategies").json()
    assert any(item["strategy_used"] == "ICT_LIQUIDITY" for item in analytics["strategies"])

    # 6. Rename strategy (e.g. add _SWING) & toggle inactive -> synced cleanly
    upd_resp = api_client.put(
        f"/api/strategies/{created['id']}",
        json={
            "name": "scalping_rsi_swing",
            "trade_style": "SWING",
            "holding_period": "2 - 5 Hari",
            "suggested_htf": "Hour4",
            "suggested_ltf": "Min60",
        },
    )
    assert upd_resp.status_code == 200
    assert upd_resp.json()["name"] == "SCALPING_RSI_SWING"
    assert upd_resp.json()["trade_style"] == "SWING"
    assert "SCALPING_RSI_SWING" in api_client.get("/api/scanner/settings").json()["active_strategies"]

    tog_resp = api_client.post(f"/api/strategies/{created['id']}/toggle")
    assert tog_resp.status_code == 200
    assert tog_resp.json()["is_active"] is False
    cfg_after_toggle = api_client.get("/api/scanner/settings").json()
    assert "SCALPING_RSI_SWING" not in cfg_after_toggle["active_strategies"]

    builtin = next(r for r in rows if r["name"] == "TREND_PULLBACK")
    assert api_client.delete(f"/api/strategies/{builtin['id']}").status_code == 400
    assert api_client.delete(f"/api/strategies/{created['id']}").status_code == 200


def test_manual_reentry_overrides_sl_tp_on_hit_sl_setup(api_client, db_session):
    db, _, _ = db_session
    now = utcnow()
    sl_setup = TradeSetup(
        symbol="SUI_USDT",
        strategy_used="TREND_PULLBACK",
        decision="LONG",
        market_regime="TRENDING_UP",
        entry_type="LIMIT",
        entry_price=Decimal("3.20"),
        stop_loss=Decimal("3.00"),
        take_profit=Decimal("3.60"),
        risk_reward_ratio=Decimal("2.0"),
        confidence=82,
        invalidation_reason="Break 3.00",
        rationale="Pullback test",
        status="HIT_SL",
        resolved_price=Decimal("3.00"),
        resolved_at=now - timedelta(minutes=10),
        expires_at=now - timedelta(minutes=1),
        features_snapshot={},
        ai_payload={},
    )
    db.add(sl_setup)
    db.commit()
    db.refresh(sl_setup)

    # Invalid geometry (SL >= Entry for LONG) should return HTTP 400
    bad_geo = api_client.patch(
        f"/api/setups/{sl_setup.id}/status",
        json={"status": "MANUAL_TAKEN", "manual_entry_price": 2.98, "stop_loss": 3.05, "take_profit": 3.40},
    )
    assert bad_geo.status_code == 400

    # Valid manual re-entry at SL level with new SL=2.85 and new TP=3.50 -> resets resolved & recomputes R:R
    ok_resp = api_client.patch(
        f"/api/setups/{sl_setup.id}/status",
        json={
            "status": "MANUAL_TAKEN",
            "manual_entry_price": 3.00,
            "stop_loss": 2.85,
            "take_profit": 3.45,
            "manual_notes": "Re-entry manual di SL sebelumnya dengan SL & TP baru",
        },
    )
    assert ok_resp.status_code == 200
    body = ok_resp.json()
    assert body["status"] == "MANUAL_TAKEN"
    assert body["manual_entry_price"] == 3.00
    assert body["stop_loss"] == 2.85
    assert body["take_profit"] == 3.45
    assert body["resolved_price"] is None
    assert body["resolved_at"] is None
    assert body["risk_reward_ratio"] == 3.0
    assert body["status_history"][-1]["event"] == "MANUAL_TAKEN"

