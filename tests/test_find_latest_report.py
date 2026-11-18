"""read_report must find the last report even when the current turn has already created an empty run folder."""
import importlib


def test_finds_the_report_in_an_earlier_run_under_reports(tmp_path, monkeypatch):
    path_utils = importlib.import_module("path_utils")
    monkeypatch.setattr(path_utils, "DATA_ROOT", tmp_path)
    ticker_dir = tmp_path / "user@example.com" / "META"
    old = ticker_dir / "2026-09-22T04:07:11.000Z"
    (old / "reports").mkdir(parents=True)
    (old / "reports" / "META_Professional_Analysis_Report.md").write_text("# META report")
    (ticker_dir / "2026-09-22T04:10:30.000Z" / "financials").mkdir(parents=True)   # this turn's empty run
    run, report = path_utils.find_latest_report("User@Example.com", "meta")
    assert run == old and report.read_text() == "# META report"


def test_no_report_anywhere_returns_none(tmp_path, monkeypatch):
    path_utils = importlib.import_module("path_utils")
    monkeypatch.setattr(path_utils, "DATA_ROOT", tmp_path)
    (tmp_path / "user@example.com" / "NVDA" / "2026-09-18T01:11:00.000Z" / "models").mkdir(parents=True)
    assert path_utils.find_latest_report("user@example.com", "NVDA") is None
    assert path_utils.find_latest_report("user@example.com", "AAPL") is None
