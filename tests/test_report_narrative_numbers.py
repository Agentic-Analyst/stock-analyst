"""LLM commentary may explain validated figures but cannot create new ones."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from report_agent import extract_valuation, sanitize_narrative_numbers  # noqa: E402


def test_validated_money_percent_and_multiple_are_preserved():
    prompt = "Current price $100.00, margin 24.8%, exit multiple 12.0x."
    response = "At $100.00, the 24.8% margin supports the stated 12.0x multiple."
    cleaned, removed = sanitize_narrative_numbers(response, prompt)
    assert cleaned == response
    assert removed == 0


def test_invented_numeric_sentence_is_omitted_but_grounded_prose_remains():
    prompt = "Current price $100.00 and operating margin 24.8%."
    response = (
        "The company remains highly profitable. Its margin should reach 35% next year. "
        "Execution is the key uncertainty."
    )
    cleaned, removed = sanitize_narrative_numbers(response, prompt)
    assert removed == 1
    assert "35%" not in cleaned
    assert "highly profitable" in cleaned
    assert "Execution is the key uncertainty" in cleaned
    assert "validated tables remain authoritative" in cleaned


def test_rounding_does_not_silently_change_a_validated_number():
    cleaned, removed = sanitize_narrative_numbers(
        "The margin is approximately 25%.", "Reported margin: 24.8%."
    )
    assert removed == 1
    assert "25%" not in cleaned


def test_scale_normalization_allows_equivalent_money_formatting():
    cleaned, removed = sanitize_narrative_numbers(
        "Revenue was USD 1.20 billion.", "Revenue: USD 1.2B."
    )
    assert removed == 0
    assert "1.20 billion" in cleaned


def test_extracted_equity_bridge_does_not_mislabel_investments_as_net_debt():
    computed = {
        "Summary": {"cells": {
            "(14, 2)": 40.0,
            "(15, 2)": 85.0,
            "(16, 2)": 107.0,
        }},
        "Valuation (DCF)": {"cells": {
            "(12, 2)": 0.09,
            "(23, 2)": 0.025,
        }},
        "Sensitivity": {"cells": {"(4, 2)": 0.5}},
    }

    valuation = extract_valuation(computed)

    assert valuation["summary"]["investments"] == 107.0
    assert valuation["summary"]["net_debt"] == -62.0
    assert valuation["dcf_inputs"]["wacc"] == 0.09
    assert valuation["dcf_inputs"]["terminal_growth"] == 0.025
    assert valuation["dcf_inputs"]["mid_year_adjustment"] == 0.5
