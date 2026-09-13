import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from peer_comps import collect_peer_comps, configuration_status
from financial_scraper import _peer_subject_market_cap_usd


class Client:
    def peers(self, ticker):
        return [ticker, "MSFT", "GOOG", "DELL", "HPQ", "MSFT"]

    def metrics(self, ticker):
        metric = {
            # Current Finnhub /stock/metric field spelling.
            "MSFT": {"evEbitdaTTM": 24.0, "priceToSalesTTM": 9.0},
            "GOOG": {"currentEv/ebitdaTTM": 18.0, "psTTM": 7.0},
            "DELL": {"enterpriseValueOverEBITDATTM": 12.0, "price/salesTTM": 1.0},
            "HPQ": {"evToEbitdaTTM": -1.0, "priceToSalesTTM": 0.6},
        }[ticker]
        metric["marketCapitalization"] = {
            "MSFT": 3_000_000, "GOOG": 2_500_000,
            "DELL": 2_000_000, "HPQ": 1_500_000,
        }[ticker]
        metric["operatingMarginTTM"] = 20.0
        metric["revenueGrowthTTMYoy"] = 10.0
        return metric


def test_real_peer_medians_exclude_the_subject_and_deduplicate(monkeypatch):
    monkeypatch.setenv("PEER_COMPS_MIN_SIZE_RATIO", "0.05")
    out = collect_peer_comps(
        "AAPL", client=Client(), max_peers=10,
        subject_market_cap=2_000_000_000_000,
        subject_operating_margin=.20,
        subject_revenue_growth=.10,
    )
    assert out["requested_peers"] == ["MSFT", "GOOG", "DELL", "HPQ"]
    assert out["median_ev_ebitda"] == 18.0
    assert out["median_price_sales"] == 4.0
    assert out["ev_ebitda_peer_count"] == 3
    assert out["source"] == "finnhub"
    assert out["status"] == "ready"
    assert out["selected_method"] == "ev_ebitda"
    assert out["selected_peer_count"] == 3
    assert out["confidence"] == "moderate"
    assert out["included_in_blended_value"] is True
    assert out["size_screen_applied"] is True


def test_unverified_peer_set_is_context_only_even_when_subindustry_matches():
    out = collect_peer_comps("AAPL", client=Client(), max_peers=10)

    assert out["status"] == "ready"
    assert out["confidence"] == "low"
    assert out["role"] == "unverified_peer_cross_check"
    assert out["size_screen_applied"] is False
    assert out["included_in_blended_value"] is False


def test_same_subindustry_outliers_fail_operating_comparability():
    class Payments:
        def peers(self, _ticker):
            return ["AFRM", "CPAY", "FISV", "MA", "V", "XYZ"]

        def metrics(self, ticker):
            rows = {
                "AFRM": (44.7, 24_000, 9.8, 32.2),
                "CPAY": (13.0, 27_000, 43.6, 20.4),
                "FISV": (8.0, 27_000, 23.1, -1.2),
                "MA": (23.5, 495_000, 58.3, 16.0),
                "V": (25.0, 600_000, 66.0, 12.0),
                "XYZ": (12.0, 40_000, 12.0, 8.0),
            }
            multiple, cap, margin, growth = rows[ticker]
            return {
                "evEbitdaTTM": multiple,
                "marketCapitalization": cap,
                "operatingMarginTTM": margin,
                "revenueGrowthTTMYoy": growth,
            }

    out = collect_peer_comps(
        "PYPL", client=Payments(), subject_market_cap=46_000_000_000,
        subject_operating_margin=.174, subject_revenue_growth=.057,
        max_peers=6,
    )

    assert out["status"] == "insufficient_observations"
    assert out["selected_method"] is None
    assert out["comparability_thresholds"] == {
        "max_operating_margin_gap_pct": 15.0,
        "max_revenue_growth_gap_pct": 20.0,
    }
    assert "At least three screened" in out["reason"]
    assert out["included_in_blended_value"] is False
    assert set(out["fundamental_excluded_symbols"]) == {"AFRM", "CPAY", "MA", "V"}
    assert [row["symbol"] for row in out["observations"]] == ["FISV", "XYZ"]


def test_peer_size_screen_uses_listing_currency_not_reporting_currency():
    london_reporting_usd = {
        "basic_info": {"listing_currency": "GBp", "currency": "USD"},
        "market_data": {"market_cap": 150_000_000_000},
    }
    us_listing = {
        "basic_info": {"listing_currency": "USD", "currency": "USD"},
        "market_data": {"market_cap": 150_000_000_000},
    }

    assert _peer_subject_market_cap_usd(london_reporting_usd) is None
    assert _peer_subject_market_cap_usd(us_listing) == 150_000_000_000.0


def test_too_few_observations_do_not_create_a_fake_comps_view():
    class Sparse(Client):
        def peers(self, ticker):
            return ["A", "B"]

        def metrics(self, ticker):
            return {"evToEbitdaTTM": 10.0}

    result = collect_peer_comps("X", client=Sparse())
    assert result["status"] == "insufficient_observations"
    assert result["ev_ebitda_peer_count"] == 2
    assert result["included_in_blended_value"] is False


def test_default_scan_does_not_stop_before_late_qualified_peers(monkeypatch):
    class LatePeers:
        def peers(self, _ticker):
            return [f"P{index}" for index in range(10)]

        def metrics(self, ticker):
            index = int(ticker[1:])
            return {
                "evEbitdaTTM": 10.0 + index,
                # Finnhub marketCapitalization is USD millions. The first
                # seven fail the 5% subject-size floor; the last three are the
                # usable cohort that the old six-symbol default never saw.
                "marketCapitalization": 1.0 if index < 7 else 100.0,
            }

    monkeypatch.delenv("PEER_COMPS_MAX_PEERS", raising=False)
    out = collect_peer_comps(
        "SUBJECT", client=LatePeers(), subject_market_cap=1_000_000_000,
    )
    assert out["status"] == "ready"
    assert out["requested_peers"] == [f"P{index}" for index in range(10)]
    assert out["selected_peer_symbols"] == ["P7", "P8", "P9"]


def test_tiny_peers_cannot_validate_a_dominant_company(monkeypatch):
    class Sized(Client):
        def metrics(self, ticker):
            metric = super().metrics(ticker)
            metric["marketCapitalization"] = {
                "MSFT": 300_000, "GOOG": 200_000, "DELL": 100_000, "HPQ": 40_000,
            }[ticker]
            return metric

    monkeypatch.setenv("PEER_COMPS_MIN_SIZE_RATIO", "0.05")
    # Subject is $4.9T; every returned peer is below 5% of its size except MSFT,
    # leaving fewer than three usable observations.
    result = collect_peer_comps(
        "AAPL", client=Sized(), max_peers=10, subject_market_cap=4_900_000_000_000,
    )
    assert result["status"] == "insufficient_observations"
    assert result["size_excluded_symbols"] == ["GOOG", "DELL", "HPQ"]


def test_peer_provider_failure_is_observable_without_leaking_details():
    class Broken:
        def peers(self, _ticker):
            raise RuntimeError("secret-bearing provider detail")

    result = collect_peer_comps("AAPL", client=Broken())

    assert result == {
        "source": "finnhub",
        "captured_at": result["captured_at"],
        "status": "provider_error",
        "error_type": "RuntimeError",
        "included_in_blended_value": False,
    }


def test_bank_uses_screened_price_to_book_peers_not_price_sales():
    class Banks:
        def peers(self, _ticker):
            return ["JPM", "BAC", "WFC", "C", "USB", "PNC"]

        def metrics(self, ticker):
            pb, pe, cap, roe = {
                "BAC": (1.3, 13.0, 400_000, 11.0),
                "WFC": (1.8, 14.0, 280_000, 13.0),
                "C": (0.9, 12.0, 180_000, 9.0),
                "USB": (1.4, 12.5, 85_000, 14.0),
                "PNC": (1.5, 13.5, 80_000, 15.0),
            }[ticker]
            return {
                "pbQuarterly": pb,
                "peTTM": pe,
                "marketCapitalization": cap,
                "roeTTM": roe,
                # Must never be selected for a balance-sheet financial.
                "priceToSalesTTM": 99.0,
            }

    result = collect_peer_comps(
        "JPM", client=Banks(), valuation_method="justified_pb_roe",
        subject_market_cap=950_000_000_000,
        subject_return_on_equity=.16,
    )

    assert result["status"] == "ready"
    assert result["selected_method"] == "price_to_book"
    assert result["median_price_to_book"] == 1.4
    assert result["selected_peer_count"] == 5
    assert result["included_in_blended_value"] is True
    assert result["fundamental_screen_applied"] is True


def test_bank_peers_without_subject_roe_are_context_only():
    class Banks:
        def peers(self, _ticker):
            return ["BAC", "WFC", "C"]

        def metrics(self, _ticker):
            return {
                "pbQuarterly": 1.4,
                "marketCapitalization": 100_000,
                "roeTTM": 12.0,
            }

    result = collect_peer_comps(
        "JPM", client=Banks(), valuation_method="justified_pb_roe",
        subject_market_cap=950_000_000_000,
    )

    assert result["status"] == "insufficient_observations"
    assert result["included_in_blended_value"] is False


def test_megacap_can_use_bounded_sector_leaders_when_subindustry_is_too_small(monkeypatch):
    class SectorLeaders(Client):
        def peers(self, ticker):
            return ["DELL", "HPQ"]

        def metrics(self, ticker):
            return {
                "MSFT": {"evEbitdaTTM": 25.0, "priceToSalesTTM": 10.0,
                         "marketCapitalization": 3_500_000},
                "NVDA": {"evEbitdaTTM": 30.0, "priceToSalesTTM": 20.0,
                         "marketCapitalization": 4_000_000},
                "GOOGL": {"evEbitdaTTM": 20.0, "priceToSalesTTM": 8.0,
                          "marketCapitalization": 3_000_000},
            }.get(ticker, {"evEbitdaTTM": 10.0, "marketCapitalization": 100_000})

    monkeypatch.setenv("PEER_COMPS_MIN_SIZE_RATIO", "0.05")
    out = collect_peer_comps(
        "AAPL", client=SectorLeaders(), max_peers=3,
        subject_market_cap=4_900_000_000_000, sector="Technology",
        fallback_symbols=["AAPL", "MSFT", "NVDA", "GOOGL"],
    )
    assert out["grouping"] == "sector_leaders"
    assert out["peer_universe_source"] == "yahoo_sector_leaders"
    assert out["median_ev_ebitda"] == 25.0
    assert out["ev_ebitda_peer_count"] == 3
    assert out["selected_peer_symbols"] == ["GOOGL", "MSFT", "NVDA"]
    assert out["confidence"] == "low"
    assert out["role"] == "broad_sector_cross_check"
    assert out["included_in_blended_value"] is False
    assert [stage["grouping"] for stage in out["screening_stages"]] == [
        "subIndustry", "sector_leaders"
    ]
    first = out["screening_stages"][0]
    assert first["requested_peers"] == ["DELL", "HPQ"]
    assert first["ev_ebitda_peer_count"] == 0
    assert first["size_excluded_symbols"] == ["DELL", "HPQ"]


def test_other_share_class_cannot_count_as_an_independent_peer(monkeypatch):
    class AlphabetPeers:
        def peers(self, _ticker):
            return ["GOOGL", "GOOG", "META", "NFLX"]

        def metrics(self, ticker):
            return {
                "GOOG": {"evEbitdaTTM": 20.0},
                "META": {"evEbitdaTTM": 18.0},
                "NFLX": {"evEbitdaTTM": 22.0},
            }[ticker]

    out = collect_peer_comps("GOOGL", client=AlphabetPeers(), max_peers=4)

    assert out["requested_peers"] == ["META", "NFLX"]
    assert out["status"] == "insufficient_observations"
    assert out["ev_ebitda_peer_count"] == 2
    assert out["included_in_blended_value"] is False


def test_megacap_uses_qualified_subindustry_before_broad_fallback(monkeypatch):
    class QualifiedSubindustry(Client):
        def peers(self, _ticker):
            return ["CVX", "SHEL", "TTE"]

        def metrics(self, ticker):
            return {
                "CVX": {"evEbitdaTTM": 9.0, "marketCapitalization": 400_000,
                        "operatingMarginTTM": 14.0, "revenueGrowthTTMYoy": 4.0},
                "SHEL": {"evEbitdaTTM": 7.0, "marketCapitalization": 250_000,
                         "operatingMarginTTM": 13.0, "revenueGrowthTTMYoy": 3.0},
                "TTE": {"evEbitdaTTM": 8.0, "marketCapitalization": 180_000,
                        "operatingMarginTTM": 12.0, "revenueGrowthTTMYoy": 6.0},
            }[ticker]

    monkeypatch.setenv("PEER_COMPS_MIN_SIZE_RATIO", "0.05")
    out = collect_peer_comps(
        "XOM", client=QualifiedSubindustry(), max_peers=6,
        subject_market_cap=550_000_000_000, sector="Energy",
        subject_operating_margin=.15, subject_revenue_growth=.05,
        fallback_symbols=["COP", "MPC", "VLO"],
    )

    assert out["status"] == "ready"
    assert out["grouping"] == "subIndustry"
    assert out["selected_peer_symbols"] == ["CVX", "SHEL", "TTE"]
    assert out["included_in_blended_value"] is True
    assert [stage["grouping"] for stage in out["screening_stages"]] == [
        "subIndustry"
    ]


def test_feature_is_off_by_default_without_an_injected_client(monkeypatch):
    monkeypatch.delenv("PEER_COMPS_ENABLED", raising=False)
    monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
    assert collect_peer_comps("AAPL") == {}


def test_legacy_auto_value_fails_closed_instead_of_enabling_from_an_analyst_key(monkeypatch):
    monkeypatch.setenv("FINNHUB_API_KEY", "secret")
    monkeypatch.setenv("PEER_COMPS_ENABLED", "auto")
    status = configuration_status()
    assert status == {
        "mode": "invalid",
        "enabled": False,
        "provider": "finnhub",
        "provider_key_configured": True,
        "ready": False,
        "blockers": [
            "PEER_COMPS_ENABLED must be explicitly true to enable peer comps"
        ],
    }


def test_provider_key_alone_does_not_enable_peer_comps(monkeypatch):
    monkeypatch.setenv("FINNHUB_API_KEY", "secret")
    monkeypatch.delenv("PEER_COMPS_ENABLED", raising=False)

    status = configuration_status()

    assert status["mode"] == "disabled"
    assert status["ready"] is False
    assert status["blockers"] == [
        "PEER_COMPS_ENABLED is unset; peer comps use the safe off default"
    ]


def test_explicit_false_still_disables_peer_comps(monkeypatch):
    monkeypatch.setenv("FINNHUB_API_KEY", "secret")
    monkeypatch.setenv("PEER_COMPS_ENABLED", "false")
    status = configuration_status()
    assert status["mode"] == "disabled"
    assert status["ready"] is False
    assert status["blockers"] == ["PEER_COMPS_ENABLED explicitly disables peer comps"]


def test_grounding_prefers_real_peer_median_over_self_multiple(monkeypatch):
    from src.agents.fm.assumption_grounding import ground_assumptions

    monkeypatch.setenv("RISK_FREE_USD", "0.04")
    data = {
        "company_data": {
            "basic_info": {"currency": "USD", "country": "United States"},
            "capital_structure": {"beta": 1.0, "total_debt": 0},
            "market_data": {"market_cap": 1e9},
            "valuation_metrics": {
                "enterprise_to_ebitda": 30.0,
                "price_to_sales": 10.0,
            },
        },
        "industry_data": {"peer_comps": {
            "source": "finnhub",
            "status": "ready",
            "median_ev_ebitda": 14.0,
            "median_price_sales": 4.0,
            "ev_ebitda_peer_count": 5,
            "price_sales_peer_count": 4,
            "selected_method": "ev_ebitda",
            "selected_peer_count": 5,
            "confidence": "high",
            "role": "comparable_company_valuation",
            "included_in_blended_value": True,
            "size_screen_applied": True,
            "fundamental_screen_applied": True,
        }},
    }
    grounded, notes = ground_assumptions(
        {"wacc": 0.09, "terminal_growth_rate": 0.025}, data)
    assert grounded["comps_ev_ebitda"] == 14.0
    assert grounded["comps_ps"] == 4.0
    assert grounded["comps_source"] == "finnhub_peer_median"
    assert grounded["comps_peer_count"] == 5
    assert grounded["comps_selected_method"] == "ev_ebitda"
    assert grounded["comps_included_in_blended_value"] is True
    assert any("5 ev_ebitda peers" in note for note in notes)


def test_low_confidence_sector_comps_remain_visible_but_leave_the_blend(monkeypatch):
    from src.agents.fm.assumption_grounding import ground_assumptions
    from src.agents.fm.tabs.tab_summary import SummaryTabBuilder
    import openpyxl

    monkeypatch.setenv("RISK_FREE_USD", "0.04")
    data = {
        "company_data": {
            "basic_info": {"currency": "USD", "country": "United States"},
            "capital_structure": {"beta": 1.0, "total_debt": 0},
            "market_data": {"market_cap": 4.9e12},
            "valuation_metrics": {},
        },
        "industry_data": {"peer_comps": {
            "median_ev_ebitda": 22.9,
            "ev_ebitda_peer_count": 4,
            "confidence": "low",
            "role": "broad_sector_cross_check",
            "included_in_blended_value": False,
        }},
    }
    grounded, notes = ground_assumptions(
        {"wacc": .09, "terminal_growth_rate": .025}, data)
    assert grounded["comps_ev_ebitda"] == 22.9
    assert grounded["comps_included_in_blended_value"] is False
    assert any("excluded from blended fair value" in note for note in notes)

    workbook = openpyxl.Workbook()
    SummaryTabBuilder(
        comps_ev_ebitda=22.9,
        comps_included_in_blend=False,
    ).create_tab(workbook)
    assert "$B$30" not in workbook["Summary"]["B26"].value
    assert workbook["Summary"]["A26"].value == "DCF Fair Value (Per-Share)"


def test_grounding_omits_comps_when_real_peers_are_unavailable(monkeypatch):
    from src.agents.fm.assumption_grounding import ground_assumptions

    monkeypatch.setenv("RISK_FREE_USD", "0.04")
    data = {"company_data": {
        "basic_info": {"currency": "USD", "country": "United States"},
        "capital_structure": {"beta": 1.0, "total_debt": 0},
        "market_data": {"market_cap": 1e9},
        "valuation_metrics": {"enterprise_to_ebitda": 30.0, "price_to_sales": 10.0},
    }}
    grounded, _ = ground_assumptions(
        {"wacc": 0.09, "terminal_growth_rate": 0.025}, data)

    assert grounded["comps_ev_ebitda"] == grounded["comps_ps"] == 0.0
    assert grounded["comps_source"] == "unavailable"


def test_partial_peer_coverage_has_no_self_proxy_label(monkeypatch):
    from src.agents.fm.assumption_grounding import ground_assumptions

    monkeypatch.setenv("RISK_FREE_USD", "0.04")
    data = {
        "company_data": {
            "basic_info": {"currency": "USD", "country": "United States"},
            "capital_structure": {"beta": 1.0, "total_debt": 0},
            "market_data": {"market_cap": 1e9},
            "valuation_metrics": {},
        },
        "industry_data": {"peer_comps": {
            "median_ev_ebitda": 14.0,
            "ev_ebitda_peer_count": 4,
            "price_sales_peer_count": 0,
        }},
    }

    grounded, _ = ground_assumptions(
        {"wacc": 0.09, "terminal_growth_rate": 0.025}, data)

    assert grounded["comps_ev_source"] == "finnhub_peer_median"
    assert grounded["comps_ps_source"] == "unavailable"
    assert grounded["comps_source"] == "partial_finnhub_peer_median"


def test_legacy_subindustry_artifact_is_context_only_without_policy_contract(monkeypatch):
    from src.agents.fm.assumption_grounding import ground_assumptions

    monkeypatch.setenv("RISK_FREE_USD", "0.04")
    data = {
        "company_data": {
            "basic_info": {"currency": "USD", "country": "United States"},
            "capital_structure": {"beta": 1.0, "total_debt": 0},
            "market_data": {"market_cap": 4.9e12},
            "valuation_metrics": {},
        },
        "industry_data": {"peer_comps": {
            "source": "finnhub",
            "grouping": "subIndustry",
            "median_ev_ebitda": 22.5,
            "ev_ebitda_peer_count": 5,
        }},
    }

    grounded, _ = ground_assumptions(
        {"wacc": .09, "terminal_growth_rate": .025}, data
    )

    assert grounded["comps_ev_ebitda"] == 22.5
    assert grounded["comps_included_in_blended_value"] is False


def test_market_comps_are_discounted_to_the_dcf_valuation_date():
    source = (Path(__file__).resolve().parents[1] /
              "src/agents/fm/tabs/tab_summary.py").read_text()
    assert "(1+$B$4)^2" in source
    assert "'Valuation (DCF)'!$B$6)^2" in source
    assert "Present Value per Share (Market Comps)" in source
