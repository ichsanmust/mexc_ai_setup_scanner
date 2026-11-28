import pytest

from app.scanner.mexc_public import score_auto_candidate


def _ticker(**kw):
    base = {
        "lastPrice": 100.0,
        "amount24": 50_000_000.0,
        "high24Price": 110.0,
        "lower24Price": 95.0,
        "riseFallRate": 0.05,
        "fundingRate": 0.0001,
        "bid1": 99.99,
        "ask1": 100.01,
    }
    base.update(kw)
    return base


def test_score_rejects_low_volume():
    assert score_auto_candidate(_ticker(amount24=1_000.0), 2_000_000.0) is None


def test_score_rejects_dead_range():
    assert score_auto_candidate(_ticker(high24Price=100.3, lower24Price=100.0), 2_000_000.0) is None


def test_score_rejects_wide_spread():
    assert score_auto_candidate(_ticker(bid1=99.0, ask1=100.5), 2_000_000.0) is None


def test_score_rejects_invalid_price():
    assert score_auto_candidate(_ticker(lastPrice=0), 0.0) is None


def test_more_volatile_momentum_pair_scores_higher():
    calm = score_auto_candidate(_ticker(high24Price=102.0, lower24Price=99.0, riseFallRate=0.001), 2_000_000.0)
    hot = score_auto_candidate(_ticker(high24Price=115.0, lower24Price=92.0, riseFallRate=0.08, lastPrice=114.0), 2_000_000.0)
    assert calm is not None and hot is not None
    assert hot[0] > calm[0]


def test_score_bounded_0_100():
    res = score_auto_candidate(
        _ticker(amount24=9e9, high24Price=130.0, lower24Price=70.0, riseFallRate=0.3, fundingRate=0.01, lastPrice=130.0),
        2_000_000.0,
    )
    assert res is not None
    assert 0.0 <= res[0] <= 100.0


@pytest.mark.asyncio
async def test_get_auto_pairs_ranks_and_limits(monkeypatch):
    from app.scanner.mexc_public import MexcPublicClient

    async def fake_contracts(self):
        return [{"symbol": s} for s in ("A_USDT", "B_USDT", "C_USDT", "D_USDT")]

    async def fake_tickers(self):
        return {
            "A_USDT": _ticker(),
            "B_USDT": _ticker(high24Price=130.0, lower24Price=90.0, riseFallRate=0.1, lastPrice=128.0),
            "C_USDT": _ticker(amount24=10.0),  # filtered out
            "D_USDT": _ticker(high24Price=100.2, lower24Price=100.0),  # dead range
        }

    monkeypatch.setattr(MexcPublicClient, "get_active_usdt_contracts", fake_contracts)
    monkeypatch.setattr(MexcPublicClient, "get_all_tickers", fake_tickers)

    client = MexcPublicClient(base_url="http://x", proxy_url="", max_concurrency=1)
    total, picked = await client.get_auto_pairs(top_n=5, min_quote_volume=2_000_000.0)
    assert total == 4
    assert [p["symbol"] for p in picked] == ["B_USDT", "A_USDT"]
    assert picked[0]["auto_score"] >= picked[1]["auto_score"]
    assert picked[0]["auto_reasons"]


class _FakeResp:
    def __init__(self, content, status=200):
        self.status_code = status
        self.is_error = status >= 400
        self.text = str(content)
        self._content = content

    def json(self):
        return {"choices": [{"message": {"content": self._content}, "finish_reason": "stop"}]}


class _FakeClient:
    def __init__(self, content, status=200):
        self.resp = _FakeResp(content, status)
        self.calls = 0

    async def post(self, url, headers=None, json=None):
        self.calls += 1
        return self.resp


_LLM = {"provider": "commandcode", "base_url": "http://llm", "api_key": "k", "model_id": "m"}


def _cands(*syms):
    return [
        {"symbol": s, "auto_score": 50.0, "ticker": _ticker(), "auto_reasons": []}
        for s in syms
    ]


@pytest.mark.asyncio
async def test_rank_pairs_with_ai_filters_hallucinated_and_duplicates():
    from app.ai.analyzer import rank_pairs_with_ai

    content = '```json\n{"picks":[{"symbol":"b_usdt","reason":"bagus"},{"symbol":"FAKE_USDT","reason":"x"},{"symbol":"B_USDT","reason":"dup"},{"symbol":"A_USDT","reason":"ok"}]}\n```'
    picks, _ = await rank_pairs_with_ai(_cands("A_USDT", "B_USDT", "C_USDT"), 2, _LLM, client=_FakeClient(content))
    assert [p["symbol"] for p in picks] == ["B_USDT", "A_USDT"]
    assert picks[0]["reason"] == "bagus"


@pytest.mark.asyncio
async def test_rank_pairs_with_ai_raises_on_invalid_output():
    from app.ai.analyzer import rank_pairs_with_ai

    with pytest.raises(RuntimeError):
        await rank_pairs_with_ai(_cands("A_USDT"), 1, _LLM, client=_FakeClient("bukan json"))
    with pytest.raises(RuntimeError):
        await rank_pairs_with_ai(_cands("A_USDT"), 1, _LLM, client=_FakeClient('{"picks":[{"symbol":"ZZZ"}]}'))
    with pytest.raises(RuntimeError):
        await rank_pairs_with_ai(_cands("A_USDT"), 1, {**_LLM, "api_key": ""}, client=_FakeClient("{}"))


def test_btc_context_for_ranking_from_saved_report(db_session):
    import json

    from app.core.market_mover import LATEST_BTC_MOVER_KEY, load_btc_context_for_ranking
    from app.models import AppSetting

    db, _, _ = db_session
    assert load_btc_context_for_ranking(db) is None

    report = {
        "btc": {
            "overall_regime": "TRENDING_UP",
            "overall_bias": "BULLISH",
            "volatility_state": "NORMAL",
            "funding_extreme": False,
            "last_price": 90000,
            "change_24h_pct": 1.2,
            "scanned_at": "2026-11-28T00:00:00+00:00",
            "styles": {"INTRADAY": {"regime": "TRENDING_UP", "bias": "BULLISH", "htf": {"big": "x"}}},
        },
        "advisor": {"suggested_settings": {"recommended_styles": ["INTRADAY"]}},
    }
    db.add(AppSetting(key=LATEST_BTC_MOVER_KEY, value=json.dumps(report)))
    db.commit()

    ctx = load_btc_context_for_ranking(db)
    assert ctx["overall_regime"] == "TRENDING_UP"
    assert ctx["styles"]["INTRADAY"] == {"regime": "TRENDING_UP", "bias": "BULLISH"}
    assert ctx["suggested_styles"] == ["INTRADAY"]
