"""
THE BUG: two finding branches read keys their tools do not emit, so they never
fired once in production.

  get_crypto    findings.py read result["price"];    the tool returns "price_usd"
  analyze_news  findings.py read "catalysts"/"risks"; the tool returns
                "top_catalysts"/"top_risks"

Every crypto run silently lost its price chip and every news run lost its
"Signals found" chip. Nothing errored — the dict lookups just returned None and
the branch fell through, which is why this survived unnoticed.

The payloads below are copied from what the tools actually construct
(crypto_tools.py, analysis_tools.py:645-655), not invented.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agents.findings import extract_findings


def kinds(findings):
    return [(f.get("kind"), f.get("label")) for f in findings]


# ---------------------------------------------------------------- crypto

CRYPTO = {
    "status": "ok", "asset_class": "crypto", "symbol": "BTC-USD",
    "price_usd": 64250.12, "change_24h_pct": 2.31, "as_of": "2026-09-09",
}


def test_a_crypto_run_emits_its_price():
    out = extract_findings("get_crypto", CRYPTO)
    assert any(f["kind"] == "price" for f in out), kinds(out)


def test_the_crypto_price_carries_the_value_and_the_move():
    f = next(f for f in extract_findings("get_crypto", CRYPTO) if f["kind"] == "price")
    assert "64,250.12" in f["value"]
    assert f.get("sub") == "+2.3%"
    assert f["label"] == "BTC-USD"


def test_a_crypto_payload_with_no_price_emits_nothing():
    assert extract_findings("get_crypto", {"status": "ok", "symbol": "X-USD"}) == []


def test_the_legacy_price_key_still_works():
    """Kept as a fallback so a future tool reshape does not silently break it again."""
    out = extract_findings("get_crypto", {"status": "ok", "symbol": "ETH-USD", "price": 3000.0})
    assert any(f["kind"] == "price" for f in out)


# ------------------------------------------------------------ analyze_news

NEWS = {
    "status": "ok", "ticker": "NVDA", "overall_sentiment": "bearish",
    "articles_analyzed": 30,
    "top_catalysts": [{"description": "a"}, {"description": "b"}],
    "top_risks": [{"description": "c"}],
    "note": "",
}


def test_a_news_run_emits_its_signal_counts():
    out = extract_findings("analyze_news", NEWS)
    assert any(f.get("label") == "Signals found" for f in out), kinds(out)


def test_the_counts_are_the_real_ones():
    f = next(f for f in extract_findings("analyze_news", NEWS) if f["label"] == "Signals found")
    assert "2 catalysts" in f["value"] and "1 risk" in f["value"]


def test_a_single_signal_is_not_pluralised():
    out = extract_findings("analyze_news", {
        "status": "ok", "articles_analyzed": 5,
        "top_catalysts": [{"d": 1}], "top_risks": [{"d": 2}]})
    f = next(f for f in out if f["label"] == "Signals found")
    assert "1 catalyst ·" in f["value"] and "1 risk" in f["value"]
    assert "catalysts" not in f["value"] and "risks" not in f["value"]


def test_no_signals_emits_no_chip():
    out = extract_findings("analyze_news", {
        "status": "ok", "articles_analyzed": 5, "top_catalysts": [], "top_risks": []})
    assert not any(f.get("label") == "Signals found" for f in out)
    assert any(f.get("label") == "Articles screened" for f in out)


def test_an_errored_result_emits_nothing():
    assert extract_findings("analyze_news", {"status": "error", "error": "boom"}) == []
