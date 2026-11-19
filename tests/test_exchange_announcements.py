"""ASX announcements reach explain_price_move under the session they could have moved."""
import os
import sys
from datetime import date

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from src.exchange_announcements import announcements_for_move, asx_code, parse_page  # noqa: E402

# Rows as the exchange's page serves them (HSN, 2026), trimmed.
PAGE = """<table>
<tr> <td> 19/08/2026<br> <span class="dates-time">8:32 am</span> </td>
<td class="pricesens" style="vertical-align: middle"> <img src="/asx/v2/markets/image/icon-price-sensitive.svg" class="pricesens" alt="asterix" title="price sensitive"> </td>
<td> <a href="/asx/v2/statistics/displayAnnouncement.do?display=pdf&amp;idsId=03126721"> FY26 Release Announcement<br> <img src="/x.png"> <span class="page">6 pages </span> </a> </td> </tr>
<tr> <td> 19/08/2026<br> <span class="dates-time">8:34 am</span> </td>
<td class="pricesens"> <img title="price sensitive"> </td>
<td> <a href="/asx/v2/statistics/displayAnnouncement.do?display=pdf&amp;idsId=03126730"> Leadership Changes<br> </a> </td> </tr>
<tr> <td> 22/09/2026<br> <span class="dates-time">3:21 pm</span> </td>
<td class="pricesens" style="vertical-align: middle"> </td>
<td> <a href="/asx/v2/statistics/displayAnnouncement.do?display=pdf&amp;idsId=03142237"> Change of Director's Interest Notice<br> </a> </td> </tr>
<tr> <td> 21/08/2026<br> <span class="dates-time">4:45 pm</span> </td>
<td class="pricesens"> <img title="price sensitive"> </td>
<td> <a href="/asx/v2/statistics/displayAnnouncement.do?display=pdf&amp;idsId=03127000"> Market update after the close<br> </a> </td> </tr>
</table>"""


def test_only_asx_listings_are_looked_up():
    assert asx_code("HSN.AX") == "HSN" and asx_code("hsn.ax") == "HSN"
    assert asx_code("AAPL") is None and asx_code("7203.T") is None
    assert announcements_for_move("AAPL", date(2026, 8, 1), date(2026, 9, 30), [], fetch=lambda u: PAGE) is None


def test_rows_are_parsed_with_time_flag_and_link():
    rows = parse_page(PAGE)
    assert rows[0] == {"date": "2026-08-19", "time_sydney": "08:32", "headline": "FY26 Release Announcement",
                       "price_sensitive": True,
                       "url": "https://www.asx.com.au/asx/v2/statistics/displayAnnouncement.do?display=pdf&idsId=03126721"}
    assert rows[2]["price_sensitive"] is False and rows[2]["time_sydney"] == "15:21"


def test_announcements_are_filed_under_the_session_they_could_move(monkeypatch):
    monkeypatch.setenv("VYNN_ASX_ANNOUNCEMENTS", "1")
    sessions = ["2026-08-18", "2026-08-19", "2026-08-20", "2026-08-21", "2026-08-24", "2026-09-22"]
    out = announcements_for_move("HSN.AX", date(2026, 8, 15), date(2026, 9, 30), sessions, fetch=lambda u: PAGE)
    by = out["price_sensitive_by_session"]
    assert [i["headline"] for i in by["2026-08-19"]] == ["FY26 Release Announcement", "Leadership Changes"]
    assert [i["headline"] for i in by["2026-08-24"]] == ["Market update after the close"]   # after 4 pm -> next session
    assert all("Director" not in i["headline"] for items in by.values() for i in items)    # not price-sensitive


def test_an_unreachable_exchange_just_omits_the_field(monkeypatch):
    monkeypatch.setenv("VYNN_ASX_ANNOUNCEMENTS", "1")
    def boom(url):
        raise OSError("timeout")
    assert announcements_for_move("HSN.AX", date(2026, 8, 1), date(2026, 9, 30), [], fetch=boom) is None



def test_off_by_default_nothing_is_fetched(monkeypatch):
    # ASX announcements are free for private and personal use only; VYNN is
    # commercial, so the lookup waits for the ASX's written authority.
    monkeypatch.delenv("VYNN_ASX_ANNOUNCEMENTS", raising=False)
    fetched = []
    out = announcements_for_move("HSN.AX", date(2026, 8, 15), date(2026, 9, 30), ["2026-08-19"],
                                 fetch=lambda u: fetched.append(u) or PAGE)
    assert out is None and fetched == []
