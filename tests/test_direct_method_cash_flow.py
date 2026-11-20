"""Operating cash flow reported by the direct method (Australian issuers) must reach the model."""
import math

from src.financial_scraper import FinancialScraper


def test_direct_method_total_becomes_operating_cash_flow():
    # Hansen Technologies (HSN.AX) FY2026 as Yahoo returns it: no "Operating Cash Flow" row.
    statement = {
        "2026-06-30": {"Cash Flowsfromusedin Operating Activities Direct": 110395000.0,
                       "Capital Expenditure": -15093000.0, "Free Cash Flow": 95302000.0},
        "2022-06-30": {"Cash Flowsfromusedin Operating Activities Direct": None},
    }
    FinancialScraper.normalize_operating_cash_flow(statement)
    row = statement["2026-06-30"]
    assert row["Operating Cash Flow"] == 110395000.0
    assert math.isclose(row["Operating Cash Flow"] + row["Capital Expenditure"], row["Free Cash Flow"])
    assert "Operating Cash Flow" not in statement["2022-06-30"]       # a missing value stays missing


def test_an_existing_operating_cash_flow_is_never_overwritten():
    statement = {"2026-09-30": {"Operating Cash Flow": 111482000000.0,
                                "Cash Flow From Continuing Operating Activities": 1.0}}
    FinancialScraper.normalize_operating_cash_flow(statement)
    assert statement["2026-09-30"]["Operating Cash Flow"] == 111482000000.0
