"""A results 8-K's own press release, for "why did it move" (18 Nov 2026).

Answers could say that results were filed (Item 2.02), not what they said.
The opening of Exhibit 99.1 is the headline, the date line and the highlights.
"""
import json
import time

from src import sec_activity

RELEASE = """<html><head><style>p{}</style><script>var x=1;</script></head><body>
<p>ACME Corp Reports Third Quarter 2026 Results</p>
<p>Revenue of $4.2 billion, down 8% year over year; lowers full-year guidance.</p>
<table><tr><td>Revenue</td><td>4,200</td></tr></table></body></html>"""


def _fake_http(index_files, calls, sizes=None):
    def http_get(url, timeout=8.0, max_bytes=None):
        calls.append(url)
        if sizes is not None:
            sizes.append(max_bytes)
        if url.endswith("index.json"):
            return json.dumps({"directory": {"item": [{"name": n} for n in index_files]}}).encode()
        if "ex99" in url.lower():
            return RELEASE.encode()
        raise AssertionError(f"unexpected {url}")
    return http_get


def test_the_release_opening_is_read_from_exhibit_99_1(monkeypatch):
    from src.agents.fm import netcache
    calls = []
    monkeypatch.setattr(netcache, "http_get", _fake_http(["acme-8k.htm", "acme-ex99_1.htm"], calls))
    release = sec_activity.results_release(123, {"accessionNumber": "0000123-26-000045"}, time.monotonic() + 5)
    assert release["document"] == "acme-ex99_1.htm"
    assert release["excerpt"].startswith("ACME Corp Reports Third Quarter 2026 Results")
    assert "lowers full-year guidance" in release["excerpt"] and "var x" not in release["excerpt"]
    # Read once: the second call comes from the cache.
    sec_activity.results_release(123, {"accessionNumber": "0000123-26-000045"}, time.monotonic() + 5)
    assert len(calls) == 2


def test_no_exhibit_no_release(monkeypatch):
    from src.agents.fm import netcache
    monkeypatch.setattr(netcache, "http_get", _fake_http(["acme-8k.htm"], []))
    assert sec_activity.results_release(123, {"accessionNumber": "1"}, time.monotonic() + 5) is None


def test_out_of_time_reads_nothing(monkeypatch):
    from src.agents.fm import netcache
    calls = []
    monkeypatch.setattr(netcache, "http_get", _fake_http(["ex99-1.htm"], calls))
    assert sec_activity.results_release(123, {"accessionNumber": "2"}, time.monotonic() - 1) is None
    assert calls == []


def test_only_results_filings_get_a_release_and_at_most_two(monkeypatch):
    from datetime import date
    rows = [
        {"form": "8-K", "items": "2.02,9.01", "filingDate": "2026-10-30", "accessionNumber": "a1"},
        {"form": "8-K", "items": "5.02", "filingDate": "2026-10-20", "accessionNumber": "a2"},
        {"form": "8-K", "items": "2.02,9.01", "filingDate": "2026-07-30", "accessionNumber": "a3"},
        {"form": "8-K", "items": "2.02,9.01", "filingDate": "2026-04-30", "accessionNumber": "a4"},
    ]
    recent = {k: [r.get(k) for r in rows] for k in ("form", "items", "filingDate", "accessionNumber")}
    monkeypatch.setattr("src.sec_filer._ciks", lambda: {"ACME": 123})
    from src.agents.fm import netcache
    monkeypatch.setattr(netcache, "cache_get", lambda name, age: (
        {"filings": {"recent": recent}} if name.startswith("sec_submissions") else None))
    asked = []
    monkeypatch.setattr(sec_activity, "results_release",
                        lambda cik, row, deadline: asked.append(row["accessionNumber"]) or {"excerpt": "x"})
    out = sec_activity.filing_activity("ACME", date(2026, 1, 1), date(2026, 11, 18))
    with_release = [e for e in out["other_filings"] if "results_release" in e]
    assert asked == ["a1", "a3"] and len(with_release) == 2



def test_a_filing_without_a_release_is_remembered(monkeypatch):
    from src.agents.fm import netcache
    calls = []
    monkeypatch.setattr(netcache, "http_get", _fake_http(["acme-8k.htm", "pressrelease.htm"], calls))
    row = {"accessionNumber": "0000123-26-000099"}
    assert sec_activity.results_release(123, row, time.monotonic() + 5) is None
    assert sec_activity.results_release(123, row, time.monotonic() + 5) is None
    assert len(calls) == 1                       # the index, once


def test_a_release_is_read_no_further_than_needed(monkeypatch):
    from src.agents.fm import netcache
    sizes = []
    monkeypatch.setattr(netcache, "http_get", _fake_http(["ex99-1.htm"], [], sizes))
    sec_activity.results_release(123, {"accessionNumber": "3"}, time.monotonic() + 5)
    assert sizes[-1] == 512 * 1024


def test_unclosed_style_tags_convert_quickly():
    # The review's probe: 2,000 unclosed <style tags took 20 seconds.
    page = "<p>ACME Reports Results</p>" + "<style>x" * 2000 + "<p>never shown</p>"
    started = time.monotonic()
    text = sec_activity.plain_text(page)
    assert time.monotonic() - started < 1.0
    assert text.startswith("ACME Reports Results") and "never shown" not in text


def test_characters_that_change_length_when_lowercased_do_not_shift_the_cuts():
    # The re-check's probe: "İ" lowercases to two characters.
    page = "<p>İİİİ Results</p><style>.a{}</style><p>Guidance cut.</p>"
    text = sec_activity.plain_text(page)
    assert ".a{}" not in text and "Guidance cut." in text


def test_the_filing_header_lines_are_not_part_of_the_release():
    text = "EX-99.1\n2\nq32026robinhoodexhibit991.htm\nEX-99.1\nDocument\nRobinhood Reports Third Quarter 2026 Results"
    assert sec_activity._without_filing_header(text) == "Robinhood Reports Third Quarter 2026 Results"
