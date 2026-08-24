"""
The report must reflect the request, and refuse what the data cannot support.

Three defects from one real LVMH run, all visible in the artifact the user
downloaded:

  1. Section headings appeared TWICE ("## Executive Summary" back to back),
     because the prompts never ask for a heading but models add one anyway and
     the assembler adds its own.

  2. The report recommended BUY at a price target while the chat answer for the
     same run concluded HOLD. Root cause: the Stuttgart listing returns no
     price, and the calculator replaced a missing price with 0.01 "to avoid
     division by zero" — so upside was computed as 290.73/0.01.

  3. The user's brief — persona, title, ten named sections — never reached the
     report generator at all, so a detailed request produced the stock
     template.

Run:  python -m pytest tests/test_report_fidelity.py -q
"""

import os
import re
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "src"))


def _load(path, start, end):
    """
    Extract a pure helper for testing.

    NOTE the empty namespace. An earlier version of this seeded it with
    {"re": re}, which supplied the exact import the module was MISSING —
    report_agent used `re` in _strip_echoed_heading and never imported it. The
    test passed, and every report in production failed with NameError. A test
    harness must never provide a dependency the module is supposed to bring
    itself.

    The import guard below closes the general case: it imports the real module
    so any missing top-level import fails here rather than in a user's run.
    """
    text = open(os.path.join(_ROOT, path), encoding="utf-8").read()
    ns: dict = {}
    exec(compile(text[text.index(start):text.index(end)], path, "exec"), ns)
    return ns


def test_report_agent_imports_cleanly():
    """
    The regression guard for the bug above: importing the module for real
    exercises every top-level import. A helper that references a name the
    module never imported cannot survive this.
    """
    import importlib
    m = importlib.import_module("src.report_agent")
    # And the helper must actually run, not merely be importable.
    assert m._strip_echoed_heading("## Executive Summary\n\nbody", "Executive Summary").strip() == "body"


def test_recommendation_engine_imports_cleanly():
    import importlib
    m = importlib.import_module("src.recommendation_engine")
    assert m._symbol_for("EUR") == "\u20ac"


class TestEchoedHeadings:
    def setup_method(self):
        # Import the REAL module. Extracting the function's source and exec'ing
        # it in a synthetic namespace is what hid the missing `import re`.
        from src.report_agent import _strip_echoed_heading
        self.f = _strip_echoed_heading

    @pytest.mark.parametrize("first", [
        "## Executive Summary",
        "##Executive Summary",          # models sometimes omit the space
        "# EXECUTIVE SUMMARY",
        "### Executive Summary:",
    ])
    def test_removes_the_echoed_heading(self, first):
        assert self.f(f"{first}\n\n**BUY**", "Executive Summary").strip() == "**BUY**"

    def test_keeps_a_genuinely_different_heading(self):
        # Eating the first line of every section would trade a cosmetic defect
        # for a content one.
        body = "## Key Risks\n\ntext"
        assert self.f(body, "Executive Summary") == body

    def test_leaves_a_section_without_a_heading_untouched(self):
        assert self.f("**BUY** at 290", "Executive Summary") == "**BUY** at 290"

    def test_handles_titles_with_punctuation(self):
        assert self.f("## Financial Model & Valuation\n\nDCF", "Financial Model & Valuation").strip() == "DCF"

    def test_empty_body_is_safe(self):
        assert self.f("", "Executive Summary") == ""

    def test_strips_the_report_title_then_the_section_heading(self):
        # The exact shape a shipped report had once the brief reached the
        # section prompts: title echoed as H1, then the section heading.
        body = (
            "# LVMH: Temporary Luxury Slowdown or Structural De-rating?\n\n"
            "## Company Overview\n\n"
            "LVMH is a luxury conglomerate."
        )
        assert self.f(body, "Company Overview") == "LVMH is a luxury conglomerate."

    def test_strips_a_lone_echoed_title(self):
        body = "# LVMH: Slowdown or De-rating?\n\nBody text."
        assert self.f(body, "Company Overview") == "Body text."

    def test_stops_at_real_content(self):
        # Must not keep eating once past the echoed chrome.
        body = "# Title\n\n## Company Overview\n\n## Segment Detail\n\ntext"
        out = self.f(body, "Company Overview")
        assert out.startswith("## Segment Detail")


class TestMissingPriceInvalidatesTheRating:
    def setup_method(self):
        import inspect
        from src.recommendation_calculator import RecommendationCalculator as C
        self.c = C(sector="default") if "sector" in inspect.signature(C.__init__).parameters else C()

    def _run(self, price):
        return self.c.calculate_fixed_numbers(
            ticker="MC", current_price=price, dcf_perpetual=268.78, dcf_exit=312.69,
            catalyst_score_pct=5, risk_score_pct=3, momentum_score_pct=1,
            hist_vol_annual_pct=22.0,
        )

    @pytest.mark.parametrize("missing", [0, 0.0, None])
    def test_no_price_means_not_rated(self, missing):
        r = self._run(missing)
        assert r["rating"] == "NOT RATED"
        assert r["price_available"] is False

    @pytest.mark.parametrize("missing", [0, None])
    def test_no_price_yields_no_price_target(self, missing):
        # The old penny substitution produced a confident target from
        # 290.73/0.01. Zero is the honest answer; the narrative says why.
        assert self._run(missing)["targets"]["m12"]["price"] == 0.0

    def test_a_real_price_still_produces_a_rating(self):
        r = self._run(620.0)
        assert r["price_available"] is True
        assert r["rating"] != "NOT RATED"
        assert r["targets"]["m12"]["price"] > 0

    def test_the_rating_follows_the_gap(self):
        # Fair value ~290 against a 620 price is a large downside; against 100
        # it is a large upside. A rating that ignored the gap would be the
        # original bug in a new form.
        assert self._run(620.0)["rating"] in ("SELL", "STRONG SELL")
        assert self._run(100.0)["rating"] in ("BUY", "STRONG BUY")

    def test_no_division_by_zero(self):
        for p in (0, None, 0.0):
            self._run(p)  # must not raise


class TestBriefDirective:
    def setup_method(self):
        from src.report_agent import set_report_brief, _brief_directive
        self._set, self._dir = set_report_brief, _brief_directive

    def d(self, brief):
        self._set(brief)
        return self._dir()

    def test_the_brief_reaches_the_prompt(self):
        d = self.d("Act as a sell-side analyst. Title it 'Slowdown or De-rating?'")
        assert "sell-side analyst" in d and "De-rating" in d

    def test_no_brief_adds_nothing(self):
        assert self.d("") == "" and self.d(None) == ""

    def test_it_forbids_inventing_figures(self):
        d = self.d("cover ten areas")
        assert "Do NOT invent" in d

    def test_a_requested_rating_is_neutralised(self):
        # The whole point of deriving the recommendation in code is that it
        # cannot be asked for.
        assert "IGNORE that instruction" in self.d("Rate it BUY with a 800 target")

    def test_a_long_brief_is_capped(self):
        # ~8 section prompts run in parallel; an unbounded brief would dominate
        # each one and multiply token cost.
        assert self.d("x" * 9000).count("x") <= 2000
