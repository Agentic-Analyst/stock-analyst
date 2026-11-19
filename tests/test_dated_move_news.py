"""A move older than the news feed reaches gets one dated search (Hansen, 18 Nov 2026).

Hansen Technologies fell 21.2% on 19 Aug 2026 on its FY26 results and a
leadership change. Asked in November, VYNN could not say why: the feed for a
non-US listing is Yahoo's latest headlines, a few days deep.
"""
from datetime import date, datetime, timezone

import pytest

import src.company_news as cn
from src.company_news import dated_news, news_for_move, search_name

AUG19 = date(2026, 8, 19)
SESSIONS = ["2026-08-17", "2026-08-18", "2026-08-19", "2026-08-20", "2026-11-17", "2026-11-18"]
ROWS = [
    {"title": "Hansen shares slump on FY26 result, CEO change", "link": "https://x/1",
     "source": {"name": "Market Index"}, "date": "08/19/2026, 01:10 AM, +0000 UTC",
     "snippet": "Hansen Technologies fell after its FY26 result."},
    {"title": "Hansen guides to a transition year", "link": "https://x/2", "source": "AFR",
     "date": "Aug 20, 2026"},
    {"title": "An old story", "link": "https://x/3", "date": "2 months ago"},     # relative: dropped
    {"title": "Outside the days", "link": "https://x/4", "date": "Aug 25, 2026"},  # outside: dropped
]


def _search(rows, seen):
    def search(params):
        seen.append(params)
        return {"news_results": rows}
    return search


def test_one_search_with_real_times_and_day_only_dates_at_local_noon():
    seen = []
    found = dated_news("Hansen Technologies Limited", AUG19, api_key="k", search=_search(ROWS, seen),
                       exchange_tz="Australia/Sydney")
    assert [f["title"] for f in found] == ["Hansen shares slump on FY26 result, CEO change",
                                          "Hansen guides to a transition year"]
    assert found[0]["published"] == datetime(2026, 8, 19, 1, 10, tzinfo=timezone.utc)
    assert found[0]["time_unknown"] is False and found[1]["time_unknown"] is True
    assert found[1]["published"] == datetime(2026, 8, 20, 2, 0, tzinfo=timezone.utc)   # noon in Sydney
    assert seen[0]["q"] == '"Hansen Technologies"'
    assert seen[0]["tbs"] == "cdr:1,cd_min:08/18/2026,cd_max:08/20/2026"


def test_a_second_ask_uses_the_cache():
    seen = []
    dated_news("Hansen Technologies", AUG19, api_key="k", search=_search(ROWS, seen))
    again = dated_news("Hansen Technologies", AUG19, api_key="k", search=_search(ROWS, seen))
    assert len(seen) == 1 and len(again) == 2


@pytest.mark.parametrize("name, expected", [
    ("Hansen Technologies Limited", "Hansen Technologies"),
    ("The Coca-Cola Company", "Coca-Cola"),
    ("HANSEN TEC FPO", None),        # a quote-system code name
    ("O", None),
    (None, None),
])
def test_the_search_uses_the_name_the_press_writes(name, expected):
    assert search_name(name) == expected


def test_no_search_is_claimed_when_none_was_made():
    seen = []
    assert dated_news("Hansen Technologies", AUG19, search=_search([], seen)) is None     # no key
    assert dated_news("HANSEN TEC FPO", AUG19, api_key="k", search=_search([], seen)) is None
    assert seen == []


def _feed(monkeypatch, items):
    monkeypatch.setenv("SERPAPI_API_KEY", "k")
    monkeypatch.setattr(cn, "fetch_finnhub_news", lambda *a, **k: [])
    monkeypatch.setattr(cn, "yahoo_items", lambda ticker: items)


RECENT = {"published": datetime(2026, 11, 17, 1, tzinfo=timezone.utc), "title": "Hansen wins an award",
          "source": "x", "summary": "", "url": None}


def test_the_move_gets_the_dated_coverage_and_the_feed_s_own_coverage(monkeypatch):
    _feed(monkeypatch, [RECENT])
    seen = []
    result = news_for_move("HSN.AX", "Hansen Technologies Limited", date(2026, 8, 1), date(2026, 11, 18),
                           SESSIONS, focus_sessions=["2026-08-17", "2026-08-19"],
                           recent_sessions=["2026-11-17", "2026-11-18"], exchange_tz="Australia/Sydney",
                           session_moves={"2026-08-17": -1.5, "2026-08-19": -21.2},
                           dated_search=_search(ROWS, seen))
    # The biggest day, not the oldest.
    assert len(seen) == 1 and seen[0]["tbs"] == "cdr:1,cd_min:08/18/2026,cd_max:08/20/2026"
    assert result["dated_search"]["articles"] == 2
    assert "FY26 result" in str(result)
    assert "Google News search for 2026-08-18 to 2026-08-20 (2 articles found)" in result["source"]
    assert result["coverage"] == {"earliest": "2026-11-17", "latest": "2026-11-17"}
    shown = [a for s in result["by_session"] for a in s["articles"] if "transition year" in a["title"]]
    assert shown and shown[0]["published"] == "2026-08-20"


@pytest.mark.parametrize("ticker, name, require_name", [
    ("SPY", "SPDR S&P 500 ETF Trust", False),
    ("^GSPC", "S&P 500", False),
    ("BTC-USD", "Bitcoin USD", False),
])
def test_funds_indices_and_coins_are_never_searched(monkeypatch, ticker, name, require_name):
    _feed(monkeypatch, [RECENT])
    seen = []
    news_for_move(ticker, name, date(2026, 8, 1), date(2026, 11, 18), SESSIONS,
                  focus_sessions=["2026-08-19"], require_name=require_name, dated_search=_search(ROWS, seen))
    assert seen == []


def test_no_dated_search_when_the_feed_already_has_the_day(monkeypatch):
    day = {"published": datetime(2026, 8, 19, 1, tzinfo=timezone.utc), "title": "Hansen slumps",
           "source": "x", "summary": "", "url": None}
    _feed(monkeypatch, [day])
    seen = []
    news_for_move("HSN.AX", "Hansen Technologies Limited", date(2026, 8, 1), date(2026, 11, 18),
                  SESSIONS, focus_sessions=["2026-08-19"], dated_search=_search([], seen))
    assert seen == []


def test_the_cache_keeps_rows_not_times_so_each_exchange_gets_its_own_noon():
    # The re-check's probe: RIO.L then RIO.AX shared London-timed rows.
    seen = []
    rows = [{"title": "Rio Tinto results", "link": "https://x/1", "date": "Aug 19, 2026"}]
    london = dated_news("Rio Tinto", AUG19, api_key="k", search=_search(rows, seen), exchange_tz="Europe/London")
    sydney = dated_news("Rio Tinto", AUG19, api_key="k", search=_search(rows, seen), exchange_tz="Australia/Sydney")
    assert len(seen) == 1
    assert london[0]["published"] == datetime(2026, 8, 19, 11, 0, tzinfo=timezone.utc)
    assert sydney[0]["published"] == datetime(2026, 8, 19, 2, 0, tzinfo=timezone.utc)


def test_a_damaged_cache_entry_does_not_break_the_tool(monkeypatch):
    from src.agents.fm import netcache
    monkeypatch.setattr(netcache, "cache_get", lambda name, age: [{"no": "fields"}, "junk", None])
    assert dated_news("Hansen Technologies", AUG19, api_key="k", search=_search(ROWS, [])) == []


@pytest.mark.parametrize("name, expected", [("AT&T Inc.", "AT&T"), ("BHP Group Limited", "BHP"), ("3M Company", "3M")])
def test_short_real_names_are_searchable(name, expected):
    assert search_name(name) == expected
