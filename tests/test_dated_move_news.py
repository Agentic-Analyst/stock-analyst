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
    {"title": "Too recent", "link": "https://x/3", "date": "3 hours ago"},       # an age outside the days: dropped
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


def test_day_first_dates_with_invisible_marks_are_read():
    # The real search for Hansen (19 Nov 2026): nine articles dated like
    # "19‏/08‏/2026", all dropped as unreadable.
    rows = [
        {"title": "Hansen Technologies Shares Slide 19% as Revenue Falls 1.5%", "link": "https://x/1",
         "source": {"name": "Kalkine"}, "date": "19‏/08‏/2026"},
        {"title": "Hansen Technologies Limited Expects Revenue Growth In Fy28", "link": "https://x/2",
         "source": {"name": "TradingView"}, "date": "18‏/08‏/2026"},
    ]
    found = dated_news("Hansen Technologies Limited", AUG19, api_key="k", search=_search(rows, []),
                       exchange_tz="Australia/Sydney")
    assert [f["published"].astimezone(cn._zone("Australia/Sydney")).date().isoformat() for f in found] == \
        ["2026-08-19", "2026-08-18"]


def test_month_first_dates_still_read():
    rows = [{"title": "Acme results", "link": "https://x/1", "date": "08/19/2026"}]
    found = dated_news("Acme Corp", AUG19, api_key="k", search=_search(rows, []))
    assert found and found[0]["published"].date() == AUG19


def test_an_ambiguous_date_takes_the_reading_inside_the_searched_days():
    rows = [{"title": "Acme results", "link": "https://x/1", "date": "08/09/2026"}]   # 9 Aug or 8 Sep
    aug9 = dated_news("Acme Corp", date(2026, 8, 9), api_key="k", search=_search(rows, []))
    assert aug9 and aug9[0]["published"].date() == date(2026, 8, 9)
    sep8 = dated_news("Acme Industries", date(2026, 9, 8), api_key="k", search=_search(rows, []))
    assert sep8 and sep8[0]["published"].date() == date(2026, 9, 8)


def test_relative_ages_inside_the_searched_days_are_kept_as_approximate(monkeypatch):
    # The real search for Robinhood's 5 Nov 2026 fall (asked 19 Nov): ten
    # results, all "2 weeks ago", all dropped; the answer said none were found.
    rows = [
        {"title": "Robinhood Stock Plunges as Bitcoin Dips After Elections", "link": "https://x/1",
         "source": {"name": "Benzinga"}, "date": "2 weeks ago"},
        {"title": "Robinhood Markets, Inc. (HOOD) Seasonal returns chart", "link": "https://x/2",
         "date": "3 weeks ago"},                                     # 21-27 days: outside 4-6 Nov
    ]
    from src.agents.fm import netcache
    store = {}
    monkeypatch.setattr(netcache, "cache_get", lambda name, age: store.get(name))
    monkeypatch.setattr(netcache, "cache_put", lambda name, obj: store.__setitem__(name, obj))
    import src.company_news as module
    real = module.datetime

    class Clock(real):
        @classmethod
        def now(cls, tz=None):
            return real(2026, 11, 19, 6, tzinfo=timezone.utc)
    monkeypatch.setattr(module, "datetime", Clock)
    found = dated_news("Robinhood Markets", date(2026, 11, 5), api_key="k", search=_search(rows, []))
    assert [f["title"] for f in found] == ["Robinhood Stock Plunges as Bitcoin Dips After Elections"]
    assert found[0]["date_approximate"] and found[0]["published"].date() == date(2026, 11, 5)
    # The cache keeps the search day: read a month later, the age still counts from 19 Nov.
    class Later(real):
        @classmethod
        def now(cls, tz=None):
            return real(2026, 12, 19, 6, tzinfo=timezone.utc)
    monkeypatch.setattr(module, "datetime", Later)
    again = dated_news("Robinhood Markets", date(2026, 11, 5), api_key="k", search=_search(rows, []))
    assert [f["title"] for f in again] == ["Robinhood Stock Plunges as Bitcoin Dips After Elections"]


def _zone(name):
    return cn._zone(name)


def test_an_exact_date_outside_the_days_is_not_overruled_by_a_relative_age():
    # The review's case: both fields sent; the exact one is 28 Oct.
    row = {"iso_date": "2026-10-28T14:00:00Z", "date": "2 weeks ago"}
    fetched = datetime(2026, 11, 19, 3, tzinfo=timezone.utc)
    assert cn._search_result_time(row, date(2026, 11, 4), date(2026, 11, 6), _zone("America/New_York"),
                                  fetched_at=fetched) is None


def test_relative_ages_count_from_the_moment_of_the_search():
    ny = _zone("America/New_York")
    # Searched 18 Nov at 10 pm New York time (19 Nov in UTC): "1 week ago"
    # covers 4-11 Nov local, so a 5 Nov article lands on its own session (it
    # was counted from the UTC date and landed on 6 Nov, the session after).
    late = datetime(2026, 11, 19, 3, tzinfo=timezone.utc)
    assert cn._relative_days("1 week ago", late, ny) == (date(2026, 11, 4), date(2026, 11, 11))
    row = {"date": "5 days ago"}
    # Truly from 12 Nov, searched 18 Nov 9 pm New York: the span reaches 12 Nov.
    first, last = cn._relative_days("5 days ago", datetime(2026, 11, 19, 2, tzinfo=timezone.utc), ny)
    assert first <= date(2026, 11, 12) <= last


def test_an_old_cache_entry_without_a_search_time_uses_no_relative_ages(monkeypatch):
    from src.agents.fm import netcache
    rows = [{"title": "Robinhood Stock Plunges", "link": "https://x/1", "date": "2 weeks ago"},
            {"title": "Robinhood results", "link": "https://x/2", "date": "Nov 5, 2026"}]
    monkeypatch.setattr(netcache, "cache_get", lambda name, age: rows)       # the old list format
    found = dated_news("Robinhood Markets", date(2026, 11, 5), api_key="k", search=_search([], []))
    assert [f["title"] for f in found] == ["Robinhood results"]
