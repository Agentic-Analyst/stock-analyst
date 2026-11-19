"""A withheld fair value never reaches the standard answer (release review, 19 Nov 2026).

The note that says the price comparison uses the cash-flow method alone printed
"its fair value of $123.45 also uses a second method" for a company whose single
value was withheld (stale statements, methods far apart, the outlier rule).
"""
from src.summary_evidence import render_external_benchmark_compact


def _value(withheld):
    return {
        "currency": "USD",
        "market_implied_fcf_path_delta": 0.4,
        "model_cash_flow_value": 150.0,
        "model_fair_value": 123.45,
        "model_point_withheld": withheld,
    }


def test_a_published_value_keeps_the_note():
    text = render_external_benchmark_compact(_value(False))
    assert "cash-flow method alone" in text and "123.45" in text


def test_a_withheld_value_is_never_printed():
    text = render_external_benchmark_compact(_value(True))
    assert "123.45" not in text and "150.00" not in text and "150" not in text
    assert "To justify today's price" in text
