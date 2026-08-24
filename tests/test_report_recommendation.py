"""
The Recommendation section must be a report, not a data structure.

THE BUG. A user's LVMH report — 57KB, otherwise clean — carried this in the
middle of its Recommendation & Price Target section:

    ## Investment Rating: SELL

    {"rating": "SELL", "thesis": "LVMH combines a large, profitable portfolio...

7,123 characters of raw model JSON, escaped unicode and all, pasted into a
document sold as professional research. 12 of 33 stored reports had it,
including real users'.

The cause was one undefined name. `_format_final_output` takes a parameter named
`validation_result`, and a block added in c81d3e3 read `validation_report`. That
raised NameError unconditionally, on every report, and the surrounding

    except Exception as e:
        return f"## Investment Rating: {...}\\n\\n{llm_response}"

swallowed it and published the payload. `e` was never logged, so nothing recorded
that the section had failed — for eleven days.

Two lessons are pinned here: the happy path must actually run, and a fallback
must never publish raw model output.

Run:  python -m pytest tests/test_report_recommendation.py -q
"""

import json
import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "src"))

from src.recommendation_engine import RecommendationEngineV3


# The shape the LLM returns, trimmed from the payload that actually shipped.
LLM_RESPONSE = json.dumps({
    "rating": "SELL",
    "thesis": "LVMH combines a large, profitable portfolio with a strong balance sheet [E2].",
    "valuation_perspective": "At 459.35 the stock sits above the 12-month target of 402.32 [E8].",
    "price_targets": {
        "m3": {"price": 440.53, "range_low": 400.88, "range_high": 480.18, "driver": "China sentiment [E3]."},
        "m6": {"price": 421.14, "range_low": 367.54, "range_high": 474.75, "driver": "Demand bottom [E4]."},
        "m12": {"price": 402.32, "range_low": 329.91, "range_high": 474.74, "driver": "Valuation convergence [E2]."},
    },
    "catalysts": [{"statement": "China stabilisation [E3].", "evidence": ["E3"]}],
    "risks": [{"statement": "Policy headwind [E6].", "evidence": ["E6"]}],
    "scenarios": {
        "bull": {"narrative": "Demand stabilises [E3].", "watch": ["China sales"]},
        "base": {"narrative": "Resilient but capped [E2].", "watch": ["Management commentary"]},
        "bear": {"narrative": "Pressure persists [E5].", "watch": ["Policy signals"]},
    },
    "action": {"buyers": "Wait for an inflection [E3].",
               "holders": "Hold, do not add [E5].",
               "watch": ["Next earnings"]},
    "monitoring_plan": ["Next earnings call [E2]"],
})

FIXED_NUMBERS = {
    "rating": "SELL",
    "price_available": True,
    "expected_return_pct_12m": -12.41,
    "targets": {
        "m3": {"price": 440.53, "range_low": 400.88, "range_high": 480.18},
        "m6": {"price": 421.14, "range_low": 367.54, "range_high": 474.75},
        "m12": {"price": 402.32, "range_low": 329.91, "range_high": 474.74},
    },
    "inputs": {
        "raw_val_gap_pct": -37.91, "sector_premium_adjustment": 0.2,
        "adj_val_gap_pct": -30.33, "catalyst_score_pct": 5.0,
        "risk_score_pct": 1.61, "net_catalyst_risk_pct": 3.39,
        "momentum_score_pct": -8.2, "hist_vol_annual_pct": 28.0,
    },
}


@pytest.fixture
def engine():
    eng = RecommendationEngineV3(sector="default")
    eng._ccy = "€"
    return eng


class TestNoRawJsonEverReachesTheReport:
    def test_the_happy_path_actually_runs(self, engine):
        """
        The regression. This exact input produced the raw-JSON fallback in
        production because of an undefined name in the formatter.
        """
        out = engine._format_final_output(LLM_RESPONSE, FIXED_NUMBERS, {})
        assert '{"rating"' not in out
        assert "\\u" not in out

    def test_it_renders_the_deterministic_numbers(self, engine):
        out = engine._format_final_output(LLM_RESPONSE, FIXED_NUMBERS, {})
        assert "### Investment Rating: SELL" in out
        assert "€402.32" in out
        assert "-12.4%" in out

    def test_it_renders_the_narrative(self, engine):
        out = engine._format_final_output(LLM_RESPONSE, FIXED_NUMBERS, {})
        assert "Investment Thesis" in out
        assert "strong balance sheet" in out

    def test_the_fallback_publishes_numbers_not_a_payload(self, engine):
        """
        Even when formatting fails, the raw model response must never reach the
        document. A reader gets the computed figures and an explicit note.
        """
        broken = dict(FIXED_NUMBERS)
        broken.pop("inputs")           # force the formatter to raise
        out = engine._format_final_output(LLM_RESPONSE, broken, {})
        assert '{"rating"' not in out
        assert "thesis" not in out
        assert "### Investment Rating: SELL" in out
        assert "could not be rendered" in out

    def test_the_fallback_is_logged(self, engine):
        """
        The original `except Exception as e` never used `e`. Eleven days of
        broken reports went unnoticed because nothing was written down.
        """
        seen = []
        engine._log = lambda msg, level="info": seen.append((level, msg))
        broken = dict(FIXED_NUMBERS)
        broken.pop("inputs")
        engine._format_final_output(LLM_RESPONSE, broken, {})
        assert any(level == "error" for level, _ in seen)
        assert any("Traceback" in msg for _, msg in seen)


class TestValidationAnnotations:
    """
    The block whose typo caused all this. It must run — and be reachable — so
    the annotations it exists to add actually appear.
    """

    def test_citation_bypass_is_annotated(self, engine):
        out = engine._format_final_output(
            LLM_RESPONSE, FIXED_NUMBERS, {"citation_enforcement_bypassed": True})
        assert "News evidence was unavailable" in out

    def test_degraded_coverage_is_annotated(self, engine):
        out = engine._format_final_output(
            LLM_RESPONSE, FIXED_NUMBERS,
            {"degraded": True, "coverage_details": {"coverage_pct": 72.5}})
        assert "Validation Warning" in out
        assert "72.5%" in out

    def test_clean_validation_adds_no_warning(self, engine):
        out = engine._format_final_output(LLM_RESPONSE, FIXED_NUMBERS, {})
        assert "Validation Warning" not in out
        assert "News evidence was unavailable" not in out

    def test_the_formatter_never_reads_an_undefined_name(self):
        """
        Guards the original defect: the parameter is `validation_result`, and
        nothing in the function body may reference `validation_report`.
        """
        import inspect
        source = inspect.getsource(RecommendationEngineV3._format_final_output)
        assert "validation_report" not in source

    def test_generate_recommendation_never_reads_the_formatter_name(self):
        """
        The mirror image, and a mistake made while fixing the first one: in
        generate_recommendation the local really IS `validation_report`, and a
        blanket rename broke the max-rewrite-attempts branch — which is the
        branch a real LVMH run takes, since its citation coverage lands at 87.5%
        after three attempts. Both names are correct; each belongs to one
        function only.
        """
        import inspect
        source = inspect.getsource(RecommendationEngineV3.generate_recommendation)
        assert "validation_result" not in source

    def test_every_name_in_both_functions_resolves(self):
        """
        A narrow undefined-name check over the two functions that got this
        wrong, so the next confusion between them fails a test instead of a
        user's report.
        """
        import ast
        import inspect
        import textwrap

        for func in (RecommendationEngineV3._format_final_output,
                     RecommendationEngineV3.generate_recommendation):
            tree = ast.parse(textwrap.dedent(inspect.getsource(func)))
            fn = tree.body[0]
            bound = {a.arg for a in fn.args.args}
            for node in ast.walk(fn):
                if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                    bound.add(node.id)
                elif isinstance(node, (ast.For, ast.comprehension)):
                    tgt = getattr(node, "target", None)
                    if isinstance(tgt, ast.Name):
                        bound.add(tgt.id)
                elif isinstance(node, ast.ExceptHandler) and node.name:
                    bound.add(node.name)
            # Only check the two names this test exists for; a general
            # undefined-name pass would need real scope analysis.
            for suspect in ("validation_report", "validation_result"):
                used = any(isinstance(n, ast.Name) and n.id == suspect
                           and isinstance(n.ctx, ast.Load)
                           for n in ast.walk(fn))
                if used:
                    assert suspect in bound, (
                        f"{fn.name} reads {suspect} without defining it")


class TestUnpricedListing:
    def test_no_target_is_invented_without_a_price(self, engine):
        unpriced = dict(FIXED_NUMBERS, price_available=False, rating="NOT RATED")
        out = engine._format_final_output(LLM_RESPONSE, unpriced, {})
        assert "No market price was available" in out
        assert "12-Month Price Target" not in out

    def test_minimal_fallback_also_withholds_the_target(self, engine):
        unpriced = dict(FIXED_NUMBERS, price_available=False, rating="NOT RATED")
        unpriced.pop("inputs")
        out = engine._format_final_output(LLM_RESPONSE, unpriced, {})
        assert "No market price was available" in out
        assert "402.32" not in out


class TestChatMatchesTheReport:
    """
    write_report published a fair value and an upside but not the RATING, so the
    answer inferred its own. One run told the user "HOLD / Neutral" while the
    report it had just generated was headed "Investment Rating: SELL".
    """

    def test_reads_back_the_published_rating(self):
        from src.agents.tools.analysis_tools import _report_headline
        out = _report_headline(
            "### Investment Rating: SELL\n\n"
            "**12-Month Price Target**: €402.32\n**Expected Return**: -12.4%\n")
        assert out["rating"] == "SELL"
        assert out["price_target_12m"] == "€402.32"
        assert out["price_target_expected_return_pct"] == -12.4

    def test_reads_a_rendered_report_end_to_end(self, engine):
        """The parser must match what the engine actually emits."""
        from src.agents.tools.analysis_tools import _report_headline
        rendered = engine._format_final_output(LLM_RESPONSE, FIXED_NUMBERS, {})
        out = _report_headline(rendered)
        assert out["rating"] == "SELL"
        assert out["price_target_expected_return_pct"] == -12.41 or \
               out["price_target_expected_return_pct"] == -12.4

    def test_missing_content_yields_nothing(self):
        from src.agents.tools.analysis_tools import _report_headline
        assert _report_headline(None) == {}
        assert _report_headline("") == {}
        assert _report_headline("a report with no rating line") == {}

    def test_the_tool_publishes_the_rating(self):
        import inspect
        from src.agents.tools.analysis_tools import WriteReportTool
        source = inspect.getsource(WriteReportTool.execute)
        assert "_report_headline(state.report.content)" in source

    def test_the_tool_warns_against_mixing_the_two_bases(self):
        """
        The report header read "12-Month Price Target: €402.32" beside "Implied
        Upside/Downside: -15.7%". The -15.7% is the DCF's number; the target's
        own figure is -12.4%.
        """
        import inspect
        from src.agents.tools.analysis_tools import WriteReportTool
        source = inspect.getsource(WriteReportTool.execute)
        assert "never quote one with the other" in source


class TestHeadingHierarchy:
    """
    The engine's output is nested inside "## Recommendation & Price Target", so
    emitting another H2 put two sibling H2s back-to-back and broke the outline
    the table of contents links against.
    """

    def test_rating_is_nested_under_the_section(self, engine):
        out = engine._format_final_output(LLM_RESPONSE, FIXED_NUMBERS, {})
        assert out.lstrip().startswith("### Investment Rating:")

    def test_fallback_nests_it_too(self, engine):
        broken = dict(FIXED_NUMBERS)
        broken.pop("inputs")
        out = engine._format_final_output(LLM_RESPONSE, broken, {})
        assert out.lstrip().startswith("### Investment Rating:")

    def test_parser_still_reads_older_reports(self):
        """Reports written before the change used a second H2."""
        from src.agents.tools.analysis_tools import _report_headline
        assert _report_headline("## Investment Rating: BUY")["rating"] == "BUY"
        assert _report_headline("### Investment Rating: BUY")["rating"] == "BUY"


class TestRatioPrecision:
    """
    The explainer is instructed never to alter a number it is given, so whatever
    precision reaches it reaches the report. A shipped LVMH note read
    "20.927107x earnings ... 3.3263094x book value".
    """

    def test_ratios_are_rounded_before_the_model_sees_them(self):
        import inspect
        source = inspect.getsource(RecommendationEngineV3)
        assert 'def _ratio(value):' in source
        for key in ("pe_ratio", "ev_ebitda", "pb_ratio", "roe", "net_margin"):
            assert f'"{key}": _ratio(' in source, key

    def test_rounding_helper_handles_real_and_missing_values(self):
        """Exercised against the helper the engine actually defines."""
        import ast
        import inspect
        import textwrap

        tree = ast.parse(textwrap.dedent(inspect.getsource(RecommendationEngineV3)))
        fn = next((n for n in ast.walk(tree)
                   if isinstance(n, ast.FunctionDef) and n.name == "_ratio"), None)
        assert fn is not None, "_ratio helper not found in RecommendationEngineV3"

        ns: dict = {}
        exec(compile(ast.Module(body=[fn], type_ignores=[]), "<ratio>", "exec"), ns)
        ratio = ns["_ratio"]

        assert ratio(20.927107) == 20.93
        assert ratio(3.3263094) == 3.33
        assert ratio("N/A") == "N/A"
        assert ratio(None) == "N/A"
        assert ratio(float("nan")) == "N/A"
        assert ratio(True) is True          # a bool is not a ratio
