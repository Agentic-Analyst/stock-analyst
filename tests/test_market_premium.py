"""Which equity risk premium wins, and whether the workbook says so."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.agents.fm import market_premium  # noqa: E402
from src.agents.fm.assumption_grounding import (  # noqa: E402
    _mature_erp,
    _mature_erp_provenance,
)

PUBLISHED = {"mature_erp": 0.0423, "source": "Damodaran January 2026 update", "as_of": "2026-01-05"}
CALIBRATED = {
    "mature_erp": 0.0320, "measured_on": "2026-09-27", "sample_size": 75,
    "median_value_to_price_at_published": 0.85,
    "published_reference": {"source": "Damodaran implied ERP", "as_of": "2026-09-01", "value": 0.0409},
}


@pytest.fixture
def calibrated(monkeypatch):
    monkeypatch.setattr(market_premium, "CALIBRATION", dict(CALIBRATED))
    monkeypatch.delenv("EQUITY_RISK_PREMIUM", raising=False)
    monkeypatch.delenv("EQUITY_RISK_PREMIUM_SOURCE", raising=False)


def test_calibrated_premium_wins_over_the_published_one_and_says_so(calibrated):
    selected = _mature_erp(PUBLISHED)
    assert selected == pytest.approx(0.0320)
    provenance = _mature_erp_provenance(selected, PUBLISHED)
    assert provenance["resolution"] == "calibrated"
    assert provenance["as_of"] == "2026-09-27"
    assert "implied by 75 S&P 500 prices under this model's growth convention" in provenance["selected_source"]
    assert "Damodaran's published implied premium 4.09%" in provenance["selected_source"]


def test_published_switch_restores_damodaran_without_a_deploy(calibrated, monkeypatch):
    monkeypatch.setenv("EQUITY_RISK_PREMIUM_SOURCE", "published")
    selected = _mature_erp(PUBLISHED)
    assert selected == pytest.approx(0.0423)
    assert _mature_erp_provenance(selected, PUBLISHED)["resolution"] == "published"


def test_an_explicit_number_still_overrides_everything(calibrated, monkeypatch):
    monkeypatch.setenv("EQUITY_RISK_PREMIUM", "0.05")
    selected = _mature_erp(PUBLISHED)
    assert selected == pytest.approx(0.05)
    assert _mature_erp_provenance(selected, PUBLISHED)["resolution"] == "operator_override"


def test_an_unset_or_absurd_calibration_falls_back_to_published(monkeypatch):
    monkeypatch.delenv("EQUITY_RISK_PREMIUM", raising=False)
    monkeypatch.delenv("EQUITY_RISK_PREMIUM_SOURCE", raising=False)
    for value in (None, 0.5, 0.001, True):
        monkeypatch.setattr(market_premium, "CALIBRATION", {**CALIBRATED, "mature_erp": value})
        assert _mature_erp(PUBLISHED) == pytest.approx(0.0423)
