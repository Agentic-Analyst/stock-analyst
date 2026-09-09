"""
THE BUG: the mega-cap sanity rail compared a market cap in the LISTING's own
currency against a bare 200e9 — a USD threshold.

So a 200bn KRW company, worth about $144M, cleared a bar meant for the forty
largest companies on earth and had its DCF suppressed as "a ~$200B mega-cap".
Every yen, won, rupee and rupiah listing was affected: any of them above 200bn
local units, which for KRW is a micro-cap and for JPY is about $1.3B.

The rail exists to stop the agent presenting a broken DCF as a headline number.
Firing it on genuine small caps suppressed valuations that were probably fine,
and printed a dollar sign on a figure that was never dollars.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agents.tools.analysis_tools import (
    _MEGACAP_USD,
    _megacap_threshold,
    _valuation_warning,
)

BIG_MISPRICING = -0.55          # a fraction, as the rail contracts


def fired(warning):
    return bool(warning and "mega-cap" in warning)


# ------------------------------------------------------------ thresholds

def test_the_usd_threshold_is_unchanged():
    assert _megacap_threshold("USD") == _MEGACAP_USD


def test_a_weak_currency_needs_far_more_local_units():
    """200bn KRW is ~$144M, nowhere near mega-cap."""
    assert _megacap_threshold("KRW") > 100 * _MEGACAP_USD


def test_a_strong_currency_needs_fewer():
    assert _megacap_threshold("GBP") < _MEGACAP_USD


def test_an_unknown_currency_keeps_the_usd_threshold():
    """Fails toward flagging rather than toward silently suppressing."""
    for code in (None, "", "ZZZ", "  "):
        assert _megacap_threshold(code) == _MEGACAP_USD


def test_pence_is_treated_as_pounds():
    assert _megacap_threshold("GBX") == _megacap_threshold("GBP")


def test_the_code_is_case_insensitive():
    assert _megacap_threshold("jpy") == _megacap_threshold("JPY")


# ----------------------------------------------------------------- the rail

def test_a_korean_micro_cap_no_longer_trips_the_mega_cap_rail():
    w = _valuation_warning(50.0, BIG_MISPRICING, market_cap=200e9, currency="KRW")
    assert not fired(w)


def test_an_indian_small_cap_no_longer_trips_it():
    w = _valuation_warning(50.0, BIG_MISPRICING, market_cap=300e9, currency="INR")
    assert not fired(w)


def test_a_real_japanese_mega_cap_still_trips_it():
    """Toyota, ~35 trillion JPY, about $234B."""
    w = _valuation_warning(1000.0, BIG_MISPRICING, market_cap=35e12, currency="JPY")
    assert fired(w)


def test_a_us_mega_cap_still_trips_it():
    w = _valuation_warning(50.0, BIG_MISPRICING, market_cap=2.1e12, currency="USD")
    assert fired(w)


def test_the_warning_prints_the_listings_own_symbol():
    w = _valuation_warning(1000.0, BIG_MISPRICING, market_cap=35e12, currency="JPY")
    assert "¥" in w and "$" not in w


def test_a_modest_mispricing_never_trips_it():
    w = _valuation_warning(50.0, -0.10, market_cap=2.1e12, currency="USD")
    assert not fired(w)


def test_a_non_positive_fair_value_still_wins():
    """The unreliable rail must keep priority over the mega-cap one."""
    w = _valuation_warning(-5.0, BIG_MISPRICING, market_cap=2.1e12, currency="USD")
    assert "UNRELIABLE" in w


def test_a_missing_market_cap_does_not_raise():
    # -55% is not past the -70% rail either, so no warning is the right answer.
    assert _valuation_warning(50.0, BIG_MISPRICING, market_cap=None, currency='JPY') is None


def test_deep_downside_still_warns_without_a_market_cap():
    w = _valuation_warning(50.0, -0.85, market_cap=None, currency='JPY')
    assert w and 'SUSPECT' in w
