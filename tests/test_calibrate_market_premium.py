"""The premium calibration replays the workbook DCF and centres the median."""
import importlib.util
import os
import statistics
import sys

import pytest

_PATH = os.path.join(os.path.dirname(__file__), "..", "scripts", "calibrate_market_premium.py")
_SPEC = importlib.util.spec_from_file_location("calibrate_market_premium", _PATH)
calib = importlib.util.module_from_spec(_SPEC)
sys.modules["calibrate_market_premium"] = calib
_SPEC.loader.exec_module(calib)


def _company(price, fcf1=10.0):
    return {
        "fcf": [fcf1, fcf1 * 1.08, fcf1 * 1.16, fcf1 * 1.24, fcf1 * 1.32],
        "rf": 0.0495, "erp": 0.0446, "beta": 1.0, "kd": 0.05, "tax": 0.2,
        "ew": 0.9, "dw": 0.1, "g": 0.025, "cash": 20.0, "debt": 30.0,
        "investments": 0.0, "shares": 1.0, "price": price, "g5": 0.07, "mid_year": 0.0,
    }


def test_a_lower_premium_raises_every_value():
    company = _company(200.0)
    assert calib.value_per_share(company, -0.01) > calib.value_per_share(company, 0.0)


def test_calibration_puts_the_median_company_at_its_price():
    # Five companies priced 20% above what the published premium supports.
    samples = [_company(1.2 * calib.value_per_share(_company(1.0, f)), f) for f in (8, 9, 10, 11, 12)]
    shift = calib.calibrate(samples)
    assert shift < 0
    ratios = [calib.value_per_share(d, shift) / d["price"] for d in samples]
    assert statistics.median(ratios) == pytest.approx(1.0, abs=1e-6)


def test_a_company_the_model_values_below_zero_counts_as_below_price():
    samples = [_company(100.0, f) for f in (8, 9, 10)] + [_company(100.0, -50.0)] * 2
    shift = calib.calibrate(samples)
    ratios = [
        (calib.value_per_share(d, shift) or float("-inf")) / d["price"] for d in samples
    ]
    assert statistics.median(ratios) == pytest.approx(1.0, abs=1e-6)
