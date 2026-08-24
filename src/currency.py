"""
Currency symbols — the one place that maps an ISO code to what a reader sees.

This table lived inside report_agent, which imports the LLM clients. When
findings.py needed the same mapping to stop publishing "$388.27" beside a EUR
valuation, importing it from there would have made a hot log-path module pull in
the whole model stack, and any failure in that import chain would have silently
reverted every listing to dollars. It has no dependencies, so both callers can
rely on it.
"""

from __future__ import annotations

from typing import Optional

_CURRENCY_SYMBOLS = {
    "USD": "$", "EUR": "€", "GBP": "£", "GBp": "p", "JPY": "¥",
    "CHF": "CHF ", "CNY": "¥", "HKD": "HK$", "SGD": "S$", "AUD": "A$",
    "CAD": "C$", "KRW": "₩", "INR": "₹", "TWD": "NT$", "SEK": "SEK ",
    "NOK": "NOK ", "DKK": "DKK ", "BRL": "R$", "MXN": "MX$", "ZAR": "R",
}


def currency_symbol(code: Optional[str]) -> str:
    """Symbol for an ISO currency code, falling back to the code itself."""
    code = (code or "USD").strip()
    return _CURRENCY_SYMBOLS.get(code, f"{code} ")
