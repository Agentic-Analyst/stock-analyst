"""Server paths (with the user's email) must never reach an answer."""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "src"))

from agents.generalist_agent import scrub_internal_paths  # noqa: E402


def test_production_leak_is_removed():
    leaked = ("The report is here:\n`/data/someone@example.de/1211.HK/2026-08-27T08:14:02.002Z/reports/"
              "1211.HK_Professional_Analysis_Report.md`\nIf you want more, ask.")
    out = scrub_internal_paths(leaked)
    assert "/data/" not in out and "@" not in out and "the attached file" in out and out.endswith("ask.")


def test_relative_path_with_email_and_normal_text_untouched():
    assert "@" not in scrub_internal_paths("saved to data/a.b@c.com/NVDA/run/models/NVDA.xlsx today")
    plain = "Revenue rose 12% to $4.1B; the data/AI segment led, per the 10-K (see page 3/4)."
    assert scrub_internal_paths(plain) == plain


def test_a_web_address_with_data_in_it_is_kept():
    # Release review, 19 Nov 2026: SEC results-release links became
    # "https://www.sec.gov/Archives/edgarthe attached file".
    from src.agents.generalist_agent import scrub_internal_paths
    url = "https://www.sec.gov/Archives/edgar/data/320193/000032019326000010/ex99.htm"
    assert scrub_internal_paths(f"The release: {url}") == f"The release: {url}"
    assert "/data/" not in scrub_internal_paths("Saved at /data/a@b.com/AAPL/r/AAPL.md")
