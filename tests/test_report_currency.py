"""
Reports must be denominated in the listing's own currency.

THE BUG. A user asked for an LVMH initiation report — a EUR listing, with a
brief that explicitly said "use EUR" — and received a 53KB report containing
500 "$" and not one "€". Every monetary figure in it was mislabelled: price
target, market cap, revenue, every table cell.

The cause was not missing data. The scraper had captured
`company_data.basic_info.currency = "EUR"` all along; the report writer simply
never read it, so the LLM defaulted to dollars for every listing on earth.

These tests pin the resolver and the directive. They deliberately avoid the LLM
and the network: currency correctness is pure lookup and string assembly, and
if verifying it ever needs a model call, the coupling is the bug.

Run:  python -m pytest tests/test_report_currency.py -q
"""

import os
import re
import sys

import pytest

_SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src", "report_agent.py")
_text = open(_SRC, encoding="utf-8").read()

# Import the two pure pieces without dragging in the LLM client stack.
_ns: dict = {}
_start = _text.index("_CURRENCY_SYMBOLS")
_end = _text.index("def format_number")
exec(compile(_text[_start:_end], _SRC, "exec"), _ns)
currency_symbol = _ns["currency_symbol"]


class TestCurrencySymbol:
    @pytest.mark.parametrize(
        "code,expected",
        [("USD", "$"), ("EUR", "€"), ("GBP", "£"), ("JPY", "¥"),
         ("HKD", "HK$"), ("SGD", "S$"), ("AUD", "A$"), ("CAD", "C$"),
         ("KRW", "₩"), ("INR", "₹")],
    )
    def test_known_venues(self, code, expected):
        assert currency_symbol(code) == expected

    def test_unknown_code_falls_back_to_the_code_itself(self):
        # "XYZ 1.2bn" is unambiguous. A wrong "$1.2bn" is not.
        assert currency_symbol("XYZ").strip() == "XYZ"

    def test_missing_currency_defaults_to_usd(self):
        # Only safe because it matches what the prompts already assume.
        assert currency_symbol(None) == "$"
        assert currency_symbol("") == "$"

    def test_every_symbol_is_non_empty(self):
        # An empty symbol would silently strip currency from every figure.
        for code in _ns["_CURRENCY_SYMBOLS"]:
            assert currency_symbol(code).strip() != ""


class TestCurrencyDirective:
    """The directive is what actually reaches the writer."""

    def _directive(self, code):
        ns = {}
        src = _text[_text.index("_REPORT_CURRENCY:"):_text.index("def load_prompt")]
        src = "import contextvars\nfrom typing import Optional\n" + src
        ns["currency_symbol"] = currency_symbol
        exec(compile(src, _SRC, "exec"), ns)
        ns["set_report_currency"](code)
        return ns["_currency_directive"]()

    def test_eur_directive_names_the_currency_and_forbids_dollars(self):
        d = self._directive("EUR")
        assert "EUR" in d
        assert "€" in d
        assert "do NOT" in d or "Do NOT" in d

    def test_usd_adds_nothing(self):
        # The prompts already assume dollars; a redundant directive is noise.
        assert self._directive("USD") == ""
        assert self._directive("usd") == ""

    def test_absent_currency_adds_nothing(self):
        assert self._directive(None) == ""
        assert self._directive("") == ""

    @pytest.mark.parametrize("code", ["EUR", "GBP", "JPY", "HKD", "CHF", "SEK"])
    def test_every_foreign_listing_gets_a_directive(self, code):
        d = self._directive(code)
        assert code in d and len(d) > 50

    def test_it_forbids_conversion_not_just_the_symbol(self):
        # Swapping "$" for "EUR" while converting the VALUES would be a subtler
        # and worse failure than the original bug.
        d = self._directive("EUR")
        assert "convert" in d.lower()
