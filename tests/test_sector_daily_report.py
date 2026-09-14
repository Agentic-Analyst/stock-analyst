"""Sector fallback inputs must be reviewed data, not generated guesses."""

from src.agents.news.daily.sector_daily_report import SectorDailyReportGenerator


def _generator(sector):
    generator = object.__new__(SectorDailyReportGenerator)
    generator.sector = sector
    generator.sector_collection = sector.upper().replace(" ", "_")
    generator._log = lambda *_args, **_kwargs: None
    return generator


def test_technology_representatives_do_not_mix_other_gics_sectors():
    generator = _generator("Technology")
    symbols = {row["ticker"] for row in generator._get_sector_companies()}

    assert {"AAPL", "MSFT", "NVDA", "AVGO", "ORCL", "CRM"} <= symbols
    assert symbols.isdisjoint({"GOOGL", "META", "AMZN", "TSLA"})


def test_unknown_sector_fails_closed_without_calling_an_llm():
    generator = _generator("Imaginary Sector")

    assert generator._get_sector_companies() == []


def test_mapping_callers_cannot_mutate_future_results():
    generator = _generator("Energy")
    first = generator._get_sector_companies()
    first[0]["ticker"] = "WRONG"

    assert generator._get_sector_companies()[0]["ticker"] == "XOM"
