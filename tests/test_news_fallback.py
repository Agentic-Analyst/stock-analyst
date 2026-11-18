"""The quick news tool falls back to Google News when Yahoo returns nothing."""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "src"))

import yf_news  # noqa: E402

RSS = b"""<?xml version="1.0"?><rss><channel>
<item><title>Why Hansen Technologies Bears Were Right Before The Drop - Yahoo Finance</title>
<link>https://news.google.com/a1</link><pubDate>Tue, 20 Oct 2026 07:00:00 GMT</pubDate><source url="https://finance.yahoo.com">Yahoo Finance</source></item>
<item><title>Hansen Technologies Supports Two New UK Mobile Offerings With Vodafone - MarketScreener</title>
<link>https://news.google.com/a2</link><pubDate>Wed, 11 Nov 2026 03:30:16 GMT</pubDate><source url="https://marketscreener.com">MarketScreener</source></item>
</channel></rss>"""


def test_google_items_are_newest_first_in_yahoo_shape():
    items = yf_news.parse_google_news(RSS)
    assert [i["publisher"] for i in items] == ["MarketScreener", "Yahoo Finance"]
    assert items[0]["title"] == "Hansen Technologies Supports Two New UK Mobile Offerings With Vodafone"
    assert items[0]["published"].startswith("2026-11-11T03:30:16") and set(items[0]) == {"title", "publisher", "link", "published"}


def test_yahoo_failure_falls_back_to_google_by_company_name(monkeypatch):
    import yfinance as yf

    class Down:
        def __init__(self, *a, **k):
            pass

        @property
        def news(self):
            raise RuntimeError("*** YAHOO! FINANCE IS CURRENTLY DOWN! ***")

    asked = []
    monkeypatch.setattr(yf, "Ticker", Down)
    monkeypatch.setattr(yf, "Search", Down, raising=False)
    monkeypatch.setattr(yf_news.time, "sleep", lambda s: None)
    monkeypatch.setattr(yf_news, "_company_name", lambda t: "Hansen Technologies Limited")
    monkeypatch.setattr(yf_news, "fetch_google_news", lambda q, count=10: asked.append(q) or yf_news.parse_google_news(RSS))
    items = yf_news.fetch_ticker_news("HSN.AX")
    assert asked == ['"Hansen Technologies Limited"'] and len(items) == 2


def test_search_name_drops_legal_forms_and_listing_codes():
    assert yf_news.search_name("Hansen Technologies Limited") == "Hansen Technologies"
    assert yf_news.search_name("China Vanke Co., Ltd.") == "China Vanke"
    assert yf_news.search_name("Kioxia Holdings Corporation") == "Kioxia"
    assert yf_news.search_name("Costco Wholesale Corporation") == "Costco Wholesale"
    assert yf_news.search_name("Alphabet Inc.") == "Alphabet"
    assert yf_news.search_name("") is None
