from datetime import datetime, timezone

import pytest

from agents.tools import crypto_research as module


def setup_function():
    module._cache.clear()


def test_bitcoin_network_context_keeps_fee_units_and_source(monkeypatch):
    responses = {
        "/mempool": {"count": 123, "vsize": 456789, "total_fee": 9000},
        "/v1/fees/recommended": {
            "fastestFee": 8, "halfHourFee": 6, "hourFee": 4,
            "economyFee": 2, "minimumFee": 1,
        },
        "/blocks/tip/height": 900001,
    }
    monkeypatch.setattr(module, "_get_json", lambda url, **_kwargs: next(
        value for suffix, value in responses.items() if url.endswith(suffix)
    ))

    result = module.get_crypto_research("BTC-USD")

    network = result["network_context"]
    assert network["block_height"] == 900001
    assert network["mempool_total_fees_sats"] == 9000
    assert network["recommended_fees_sat_per_vbyte"]["high_priority"] == 8
    assert result["capabilities"]["network_activity"] is True
    assert result["capabilities"]["protocol_economics"] is False
    assert result["status"] == "complete"


def test_chain_tvl_uses_dated_history_and_labels_ecosystem_scope(monkeypatch):
    now = int(datetime(2026, 9, 12, tzinfo=timezone.utc).timestamp())

    def fetch(url, **_kwargs):
        if "historicalChainTvl" in url:
            return [{"date": now - 7 * 86400, "tvl": 100},
                    {"date": now, "tvl": 125}]
        return {"total24h": 10, "total48hto24h": 8,
                "total7d": 70, "total30d": 300}

    monkeypatch.setattr(module, "_get_json", fetch)
    result = module.get_crypto_research("ETH-USD")

    context = result["network_context"]
    assert context["defi_tvl_usd"] == 125
    assert context["defi_tvl_change_7d"] == pytest.approx(0.25)
    assert context["tracked_application_fees_usd"]["last_24h"] == 10
    assert "not issuer revenue" in context["warning"]
    assert result["capabilities"]["defi_ecosystem_activity"] is True
    assert result["capabilities"]["network_activity"] is False


def test_protocol_fees_and_holder_revenue_are_not_conflated(monkeypatch):
    def fetch(_url, *, params=None):
        if params and params.get("dataType") == "dailyHoldersRevenue":
            return {"name": "Uniswap", "total24h": 2, "total7d": 12,
                    "total30d": 40}
        return {"name": "Uniswap", "total24h": 100, "total7d": 700,
                "total30d": 3000}

    monkeypatch.setattr(module, "_get_json", fetch)
    result = module.get_crypto_research("UNI7083-USD")

    protocol = result["protocol_context"]
    assert protocol["gross_fees_usd"]["last_24h"] == 100
    assert protocol["token_holder_revenue_usd"]["last_24h"] == 2
    assert protocol["gross_fees_usd"] != protocol["token_holder_revenue_usd"]
    assert result["capabilities"]["token_holder_revenue"] is True


def test_protocol_fees_do_not_imply_token_holder_revenue(monkeypatch):
    def fetch(_url, *, params=None):
        if params and params.get("dataType") == "dailyHoldersRevenue":
            return {}
        return {"name": "Uniswap", "total24h": 100, "total7d": 700,
                "total30d": 3000}

    monkeypatch.setattr(module, "_get_json", fetch)
    result = module.get_crypto_research("UNI7083-USD")

    assert result["capabilities"]["protocol_economics"] is True
    assert result["capabilities"]["token_holder_revenue"] is False


def test_unsupported_coin_and_provider_failure_are_explicit(monkeypatch):
    unsupported = module.get_crypto_research("DOGE-USD")
    assert unsupported["status"] == "unsupported"
    assert unsupported["mapped_asset"] is False
    assert unsupported["capabilities"]["network_activity"] is False

    module._cache.clear()
    monkeypatch.setattr(module, "_get_json", lambda *_args, **_kwargs: (_ for _ in ()).throw(
        RuntimeError("sensitive upstream detail")
    ))
    failed = module.get_crypto_research("BTC-USD")
    assert failed["network_context"] is None
    assert failed["failures"] == ["bitcoin_network_source_unavailable"]
    assert failed["status"] == "unavailable"
    assert "sensitive upstream detail" not in str(failed)


def test_bitcoin_keeps_activity_when_fee_subsource_fails(monkeypatch):
    def fetch(url, **_kwargs):
        if url.endswith("/mempool"):
            return {"count": 123, "vsize": 456789, "total_fee": 9000}
        if url.endswith("/blocks/tip/height"):
            return 900001
        raise RuntimeError("fee endpoint down")

    monkeypatch.setattr(module, "_get_json", fetch)
    result = module.get_crypto_research("BTC-USD")

    assert result["status"] == "partial"
    assert result["network_context"]["block_height"] == 900001
    assert result["capabilities"]["network_activity"] is True
    assert result["failures"] == ["bitcoin_fee_source_unavailable"]


def test_chain_keeps_tvl_when_fee_subsource_fails(monkeypatch):
    now = int(datetime(2026, 9, 12, tzinfo=timezone.utc).timestamp())

    def fetch(url, **_kwargs):
        if "historicalChainTvl" in url:
            return [{"date": now, "tvl": 125}]
        raise RuntimeError("fee endpoint down")

    monkeypatch.setattr(module, "_get_json", fetch)
    result = module.get_crypto_research("ETH-USD")

    assert result["status"] == "partial"
    assert result["network_context"]["defi_tvl_usd"] == 125
    assert result["failures"] == ["chain_fee_source_unavailable"]


def test_crypto_research_rejects_oversized_upstream_documents(monkeypatch):
    import requests

    class Response:
        headers = {"Content-Length": str(module.MAX_UPSTREAM_BYTES + 1)}

        def raise_for_status(self):
            return None

        def close(self):
            return None

        def json(self):
            raise AssertionError("oversized body must not be parsed")

    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: Response())

    with pytest.raises(ValueError, match="size limit"):
        module._get_json("https://mempool.space/api/test")
