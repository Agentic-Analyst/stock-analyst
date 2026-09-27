"""The equity risk premium implied by today's prices under this model's convention.

Damodaran's implied premium is solved from the S&P 500 assuming cash flows
grow at the analysts' five-year rate and then at the Treasury yield forever.
This engine's companies grow at two years of consensus, fade over eight
years, and then grow at 2.5%. The same prices imply a lower premium under the
slower growth, so pairing his premium with this engine's growth valued the
median S&P 500 company about 15% below its price for a reason that had
nothing to do with any company (measured 2026-09-26 on 72 names).

The calibrated premium removes that level bias the way Damodaran's method
does: it is the premium at which this engine, run on a fixed sample of
S&P 500 companies at their market prices, values the median one at its price.
It is recomputed by ``scripts/calibrate_market_premium.py`` from a model-canary
run and recorded here with its date, sample and the published reference.

``EQUITY_RISK_PREMIUM`` (a number) still overrides everything, and
``EQUITY_RISK_PREMIUM_SOURCE=published`` returns to Damodaran's figure
without a deploy.
"""
from __future__ import annotations

import os
from typing import Any, Dict, Optional

# Filled from scripts/calibrate_market_premium.py; see the module docstring.
CALIBRATION: Dict[str, Any] = {
    "mature_erp": 0.0324,
    "measured_on": "2026-09-27",
    "sample_size": 74,
    "median_value_to_price_at_published": 0.851,
    "published_reference": {
        "source": "Damodaran implied ERP (monthly)",
        "as_of": "2026-09-01",
        "value": 0.0409,
    },
}

_BAND = (0.02, 0.09)


def calibrated_premium() -> Optional[Dict[str, Any]]:
    """The calibrated mature-market premium, or None when disabled or unset."""
    if os.getenv("EQUITY_RISK_PREMIUM_SOURCE", "calibrated").strip().lower() == "published":
        return None
    value = CALIBRATION.get("mature_erp")
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not _BAND[0] <= float(value) <= _BAND[1]):
        return None
    reference = CALIBRATION.get("published_reference") or {}
    label = (
        f"implied by {CALIBRATION.get('sample_size')} S&P 500 prices under this "
        "model's growth convention"
    )
    if isinstance(reference.get("value"), (int, float)):
        label += (
            f"; Damodaran's published implied premium "
            f"{float(reference['value']) * 100:.2f}% assumes growth at the Treasury yield"
        )
    return {**CALIBRATION, "mature_erp": float(value), "label": label}
