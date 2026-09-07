"""
The risk-free rate is a government bond yield in the cash flows' currency.

Before: live for USD, a dated table entry for EUR, and a US Treasury yield for
every other currency — labelled as a proxy, which is honest, but still a 4.8%
rate on yen cash flows whose own 10Y is 2.9%. Now each currency has a feed
(FRED's public CSVs, the ECB curve, Japan's MOF file, ^TNX), a dated snapshot
behind it, and a label that says which one answered.

Run:  python -m pytest tests/test_sovereign_rates.py -q
"""

import os
import sys
import time

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "src"))

from src.agents.fm import netcache
from src.agents.fm import sovereign_rates as sr

FRED_DAILY = "observation_date,DGS10\n2026-09-01,4.79\n2026-09-02,.\n2026-09-03,4.77\n"
FRED_MONTHLY = "observation_date,IRLTLT01JPM156N\n2026-05-01,2.650\n2026-06-01,2.670\n"
ECB_CSV = (
    "KEY,FREQ,REF_AREA,CURRENCY,PROVIDER_FM,INSTRUMENT_FM,PROVIDER_FM_ID,DATA_TYPE_FM,TIME_PERIOD,OBS_VALUE,OBS_STATUS\n"
    "YC.B.U2.EUR.4F.G_N_A.SV_C_YM.SR_10Y,B,U2,EUR,4F,G_N_A,SV_C_YM,SR_10Y,2026-09-02,3.3918508877,A\n"
    "YC.B.U2.EUR.4F.G_N_A.SV_C_YM.SR_10Y,B,U2,EUR,4F,G_N_A,SV_C_YM,SR_10Y,2026-09-03,3.3646241735,A\n"
)
MOF_CSV = (
    "Interest Rate (September 2026),,,,,,,,,,,,,,,(Unit : %)\r\n"
    "Date,1Y,2Y,3Y,4Y,5Y,6Y,7Y,8Y,9Y,10Y,15Y,20Y,25Y,30Y,40Y\r\n"
    "\"  If you cannot download the latest csv data, please clear the browser's cache and download again.\",,,,,,,,,,,,,,,\r\n"
    "2026/9/3,1.563,1.85,1.994,2.173,2.303,2.426,2.547,2.704,2.832,2.966,3.506,3.806,4.079,4.052,4.063\r\n"
    "2026/9/4,1.546,1.83,1.955,2.128,2.25,2.368,2.493,2.652,2.778,2.91,3.416,3.717,3.987,3.965,3.966\r\n"
    ",,,,,,,,,,,,,,,\r\n"
)


def _serve(monkeypatch, routes, post_routes=None):
    """Route substrings of the URL to fixture text; anything else is a network error."""
    def fake(url, timeout=None):
        for needle, body in routes.items():
            if needle in url:
                if isinstance(body, Exception):
                    raise body
                return body.encode("utf-8")
        raise ConnectionError(url)

    def fake_post(url, body, timeout=None):
        for needle, reply in (post_routes or {}).items():
            if needle in url or needle in body.decode("utf-8", "replace"):
                if isinstance(reply, Exception):
                    raise reply
                return reply.encode("utf-8")
        raise ConnectionError(url)
    monkeypatch.setattr(netcache, "http_get", fake)
    monkeypatch.setattr(netcache, "http_post", fake_post)


TV_REPLY = ('{"totalCount":1,"data":[{"s":"TVC:CN10Y","d":[1.682,1788741000]}]}')


class TestParsers:
    def test_fred_skips_missing_days_and_takes_the_last_number(self):
        assert sr.parse_fred_csv(FRED_DAILY) == (pytest.approx(0.0477), "2026-09-03")

    def test_fred_monthly(self):
        assert sr.parse_fred_csv(FRED_MONTHLY) == (pytest.approx(0.0267), "2026-06-01")

    def test_fred_garbage_is_none(self):
        assert sr.parse_fred_csv("<html>bot check</html>") is None

    def test_ecb(self):
        rate, as_of = sr.parse_ecb_csv(ECB_CSV)
        assert rate == pytest.approx(0.033646, abs=1e-6)
        assert as_of == "2026-09-03"

    def test_mof_reads_the_10y_column_past_the_notice_line(self):
        rate, as_of = sr.parse_mof_csv(MOF_CSV)
        assert rate == pytest.approx(0.0291)
        assert as_of == "2026-09-04"

    def test_a_dead_series_is_not_fresh(self):
        assert not sr._fresh_enough("2020-01")
        assert sr._fresh_enough(time.strftime("%Y-%m-%d"))


class TestFeedOrder:
    def test_jpy_prefers_the_ministry_of_finance(self, monkeypatch):
        _serve(monkeypatch, {"mof.go.jp": MOF_CSV, "IRLTLT01JPM156N": FRED_MONTHLY})
        got = sr.sovereign_yield("JPY")
        assert got["source"] == "Japan MOF"
        assert got["rate"] == pytest.approx(0.0291)
        assert "10Y JGB 2.91% (Japan MOF, as of 2026-09-04)" == got["label"]

    def test_jpy_falls_to_fred_when_mof_is_down(self, monkeypatch):
        _serve(monkeypatch, {"mof.go.jp": ConnectionError("down"), "IRLTLT01JPM156N": FRED_MONTHLY})
        got = sr.sovereign_yield("JPY")
        assert got["source"] == "FRED"
        assert got["as_of"] == "2026-06"          # monthly series are labelled by month
        assert "FRED, as of 2026-06" in got["label"]

    def test_eur_prefers_the_ecb(self, monkeypatch):
        _serve(monkeypatch, {"ecb.europa.eu": ECB_CSV})
        got = sr.sovereign_yield("EUR")
        assert got["source"] == "ECB" and got["instrument"] == "euro-area AAA 10Y"

    def test_usd_prefers_yahoo_then_fred(self, monkeypatch):
        monkeypatch.setattr(sr, "_yahoo_tnx", lambda: (0.0481, "2026-09-04"))
        assert sr.sovereign_yield("USD")["source"] == "Yahoo"
        sr._reset_memo()
        monkeypatch.setattr(sr, "_yahoo_tnx", lambda: None)
        _serve(monkeypatch, {"DGS10": FRED_DAILY})
        monkeypatch.setattr(netcache, "cache_dir", lambda: None)   # no cache: force the second resolution
        got = sr.sovereign_yield("USD")
        assert got["source"] == "FRED" and got["as_of"] == "2026-09-03"

    def test_eur_falls_to_the_bund_series_when_the_ecb_is_down(self, monkeypatch):
        _serve(monkeypatch, {"ecb.europa.eu": ConnectionError("down"),
                             "IRLTLT01DEM156N": "observation_date,IRLTLT01DEM156N\n2026-06-01,2.97\n"})
        got = sr.sovereign_yield("EUR")
        assert got["source"] == "FRED" and "German Bund" in got["label"] and "as of 2026-06" in got["label"]

    def test_a_series_that_stopped_updating_is_not_served_as_live(self, monkeypatch):
        _serve(monkeypatch, {"IRLTLT01GBM156N": "observation_date,IRLTLT01GBM156N\n2024-06-01,4.10\n"})
        got = sr.sovereign_yield("GBP")
        assert got["source"] == "snapshot"

    def test_an_absurd_value_is_rejected(self, monkeypatch):
        # A feed that came back in basis points would put a 477% rate in a DCF.
        _serve(monkeypatch, {"DGS10": "observation_date,DGS10\n2026-09-03,4770\n"})
        got = sr.sovereign_yield("USD")
        assert got["source"] == "snapshot"


class TestTradingView:
    """The only reachable feed for the yuan, the Hong Kong dollar and six other markets."""

    def test_parses_the_scanner_reply(self):
        rate, as_of = sr.parse_tradingview(TV_REPLY.encode(), "TVC:CN10Y")
        assert rate == pytest.approx(0.01682)
        assert as_of == "2026-09-07"                     # epoch 1788741000 = 2026-09-07 00:30 UTC

    def test_the_wrong_symbol_or_garbage_is_none(self):
        assert sr.parse_tradingview(TV_REPLY.encode(), "TVC:HK10Y") is None
        assert sr.parse_tradingview(b"<html>", "TVC:CN10Y") is None
        assert sr.parse_tradingview(b'{"data":[{"s":"TVC:CN10Y","d":[null,1]}]}', "TVC:CN10Y") is None
        assert sr.parse_tradingview(b'{"data":[{"s":"TVC:CN10Y","d":{"close":1.6}}]}', "TVC:CN10Y") is None
        assert sr.parse_tradingview(b'{"data":[{"s":"TVC:CN10Y","d":[1.6,1e20]}]}', "TVC:CN10Y") is None

    def test_a_row_without_a_bar_time_is_not_dated_today(self):
        """A symbol the screen stopped updating must not outrank the monthly series behind it."""
        assert sr.parse_tradingview(b'{"data":[{"s":"TVC:CN10Y","d":[1.682,null]}]}', "TVC:CN10Y") is None
        assert sr.parse_tradingview(b'{"data":[{"s":"TVC:CN10Y","d":[1.682,0]}]}', "TVC:CN10Y") is None

    def test_a_turkish_yield_above_thirty_percent_is_a_real_number(self, monkeypatch):
        _serve(monkeypatch, {}, {"TVC:TR10Y": TV_REPLY.replace("TVC:CN10Y", "TVC:TR10Y").replace("1.682", "31.5")})
        got = sr.sovereign_yield("TRY")
        assert got["source"] == "TradingView TR10Y" and got["rate"] == pytest.approx(0.315)

    def test_a_dollar_peg_says_so_instead_of_no_source(self):
        got = sr.sovereign_yield("SAR")
        assert got["proxy"] is True and got["pegged"] is True
        assert "Saudi riyal is pegged to the US dollar" in got["label"]

    def test_the_yuan_comes_from_tradingview(self, monkeypatch):
        _serve(monkeypatch, {}, {"TVC:CN10Y": TV_REPLY})
        got = sr.sovereign_yield("CNY")
        assert got["source"] == "TradingView CN10Y"
        assert got["rate"] == pytest.approx(0.01682)
        assert got["label"] == "10Y China government bond 1.68% (TradingView CN10Y, as of 2026-09-07)"

    def test_a_daily_screen_beats_a_two_month_old_monthly_series(self, monkeypatch):
        _serve(monkeypatch, {"INDIRLTLT01STM": "observation_date,INDIRLTLT01STM\n2026-06-01,6.89\n"},
               {"TVC:IN10Y": TV_REPLY.replace("TVC:CN10Y", "TVC:IN10Y").replace("1.682", "6.957")})
        got = sr.sovereign_yield("INR")
        assert got["source"] == "TradingView IN10Y" and got["rate"] == pytest.approx(0.06957)

    def test_but_sits_behind_the_official_daily_feeds(self, monkeypatch):
        _serve(monkeypatch, {"ecb.europa.eu": ECB_CSV},
               {"TVC:DE10Y": TV_REPLY.replace("TVC:CN10Y", "TVC:DE10Y").replace("1.682", "3.5")})
        assert sr.sovereign_yield("EUR")["source"] == "ECB"
        sr._reset_memo()
        monkeypatch.setattr(netcache, "cache_dir", lambda: None)
        _serve(monkeypatch, {"ecb.europa.eu": ConnectionError("down"), "IRLTLT01DEM156N": "observation_date,x\n2026-06-01,2.97\n"},
               {"TVC:DE10Y": TV_REPLY.replace("TVC:CN10Y", "TVC:DE10Y").replace("1.682", "3.5")})
        got = sr.sovereign_yield("EUR")
        assert got["source"] == "TradingView DE10Y" and got["rate"] == pytest.approx(0.035)

    def test_and_falls_to_fred_when_the_screen_is_down(self, monkeypatch):
        _serve(monkeypatch, {"IRLTLT01GBM156N": "observation_date,x\n2026-06-01,4.80\n"})
        got = sr.sovereign_yield("GBP")
        assert got["source"] == "FRED"

    def test_an_absurd_screen_value_is_rejected(self, monkeypatch):
        _serve(monkeypatch, {}, {"TVC:CN10Y": TV_REPLY.replace("1.682", "168.2")})
        assert sr.sovereign_yield("CNY")["source"] == "snapshot"


class TestFallbacks:
    def test_offline_gives_the_dated_snapshot_and_says_so(self):
        got = sr.sovereign_yield("GBP")
        assert got["source"] == "snapshot"
        assert got["rate"] == sr._SNAPSHOT["GBP"][0]
        assert "snapshot as of 2026-06" in got["label"] and "live feed unavailable" in got["label"]

    def test_every_snapshot_market_now_has_a_feed_behind_it(self):
        got = sr.sovereign_yield("CNY")
        assert got["source"] == "snapshot" and "live feed unavailable" in got["label"]
        for ccy in sr._SNAPSHOT:
            assert ccy in sr._TV_SYMBOLS or ccy in sr._FRED_SERIES, ccy

    def test_a_currency_nobody_covers_gets_a_labelled_us_proxy(self):
        got = sr.sovereign_yield("XXX")
        assert got["proxy"] is True and got["source"] == "proxy"
        assert "proxy" in got["label"] and "XXX" in got["label"]
        assert got["rate"] == sr._SNAPSHOT["USD"][0]

    def test_pence_quoted_listings_are_sterling(self):
        assert sr.normalise_currency("GBp") == "GBP"
        assert sr.sovereign_yield("GBp")["currency"] == "GBP"

    def test_yahoo_s_other_minor_units_map_to_their_bond(self):
        # JSE quotes in cents (ZAc), TASE in agorot (ILA); the bond is the rand's / shekel's.
        assert sr.normalise_currency("ZAc") == "ZAR"
        assert sr.normalise_currency("ILA") == "ILS"
        assert sr.sovereign_yield("ZAc")["source"] == "snapshot"      # not a US proxy

    def test_the_proxy_says_where_the_us_number_itself_came_from(self):
        got = sr.sovereign_yield("XXX")
        assert "snapshot as of" in got["label"]       # offline: the US leg is a snapshot, and it says so
        assert got["proxy_source"] == "snapshot"

    def test_a_snapshot_past_its_shelf_life_is_marked_stale(self, monkeypatch):
        monkeypatch.setattr(sr, "_today", lambda: "2028-06-01")
        got = sr.sovereign_yield("CNY")
        assert got["stale"] is True and got["label"].startswith("10Y China government bond 1.68% (STALE snapshot")

    def test_never_raises(self, monkeypatch):
        monkeypatch.setattr(netcache, "http_get", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
        for ccy in ("USD", "EUR", "JPY", "INR", "CNY", "XXX", None, ""):
            assert isinstance(sr.sovereign_yield(ccy)["rate"], float)


class TestCache:
    def test_a_resolved_rate_is_reused_for_the_next_run(self, monkeypatch):
        _serve(monkeypatch, {"ecb.europa.eu": ECB_CSV})
        first = sr.sovereign_yield("EUR")
        assert first["source"] == "ECB"
        _serve(monkeypatch, {})                       # network gone
        second = sr.sovereign_yield("EUR")
        assert second == first

    def _age(self, name, seconds):
        path = os.path.join(netcache.cache_dir(), name + ".json")
        old = time.time() - seconds
        os.utime(path, (old, old))

    def test_an_expired_disk_copy_is_refetched_when_the_feed_is_up(self, monkeypatch):
        _serve(monkeypatch, {"ecb.europa.eu": ECB_CSV})
        sr.sovereign_yield("EUR")
        sr._reset_memo()
        self._age("sovereign_EUR", 2 * sr._CACHE_TTL)
        _serve(monkeypatch, {"ecb.europa.eu": ECB_CSV.replace("3.3646241735", "3.50")})
        assert sr.sovereign_yield("EUR")["rate"] == pytest.approx(0.035)

    def test_an_expired_disk_copy_beats_the_embedded_snapshot_when_the_feed_is_down(self, monkeypatch):
        """Yesterday's FRED read is newer than anything embedded in the code."""
        _serve(monkeypatch, {"ecb.europa.eu": ECB_CSV})
        sr.sovereign_yield("EUR")
        sr._reset_memo()
        self._age("sovereign_EUR", 2 * sr._CACHE_TTL)
        _serve(monkeypatch, {})
        got = sr.sovereign_yield("EUR")
        assert got["source"] == "ECB, cached"
        assert got["rate"] == pytest.approx(0.033646, abs=1e-6)
        assert "cached — live feed unavailable" in got["label"] and "as of 2026-09-03" in got["label"]

    def test_a_dead_disk_copy_falls_to_the_snapshot(self, monkeypatch):
        _serve(monkeypatch, {"ecb.europa.eu": ECB_CSV})
        sr.sovereign_yield("EUR")
        sr._reset_memo()
        self._age("sovereign_EUR", (sr._MAX_AGE_DAYS + 5) * 86400)
        _serve(monkeypatch, {})
        assert sr.sovereign_yield("EUR")["source"] == "snapshot"

    @pytest.mark.parametrize("payload", [
        {"rate": 0.05},                                                    # no label: would KeyError
        {"rate": 99.0, "label": "x", "source": "FRED", "instrument": "y", "as_of": "2026-09-01"},   # 9,900%
        {"rate": True, "label": "x", "source": "FRED", "instrument": "y", "as_of": "2026-09-01"},
        {"rate": "0.05", "label": "x", "source": "FRED", "instrument": "y", "as_of": "2026-09-01"},
        [0.05],
    ])
    def test_a_malformed_cache_file_is_a_miss_not_a_crash(self, payload):
        """The cache is a shared volume any worker image, or a hand, can write."""
        import json
        with open(os.path.join(netcache.cache_dir(), "sovereign_USD.json"), "w") as fh:
            json.dump(payload, fh)
        got = sr.sovereign_yield("USD")
        assert got["source"] == "snapshot" and got["rate"] == sr._SNAPSHOT["USD"][0]

    def test_no_cache_directory_is_a_slower_run_not_a_failure(self, monkeypatch):
        monkeypatch.setattr(netcache, "cache_dir", lambda: None)
        _serve(monkeypatch, {"ecb.europa.eu": ECB_CSV})
        assert sr.sovereign_yield("EUR")["source"] == "ECB"

    def test_the_default_location_is_the_analysis_volume(self, monkeypatch, tmp_path):
        monkeypatch.delenv("VYNN_CACHE_DIR")
        monkeypatch.setattr(os.path, "isdir", lambda p: p == "/data" or os.path.exists(p))
        # /data does not exist on a laptop: no cache rather than a crash.
        monkeypatch.setattr(os, "makedirs", lambda *a, **k: (_ for _ in ()).throw(OSError("read-only")))
        assert netcache.cache_dir() is None


class TestYahooTenYear:
    """^TNX is the first USD source in production; its scaling heuristic runs here."""

    def _fake(self, monkeypatch, closes, dates):
        import sys
        import types
        import pandas as pd

        class Ticker:
            def __init__(self, symbol):
                assert symbol == "^TNX"

            def history(self, period="5d"):
                return pd.DataFrame({"Close": closes}, index=pd.to_datetime(dates))

        mod = types.ModuleType("yfinance")
        mod.Ticker = Ticker
        monkeypatch.setitem(sys.modules, "yfinance", mod)

    def test_yield_times_ten_the_usual_quote(self, monkeypatch):
        self._fake(monkeypatch, [47.5, 47.7], ["2026-09-03", "2026-09-04"])
        assert sr._yahoo_tnx() == (pytest.approx(0.0477), "2026-09-04")

    def test_plain_percent_is_also_understood(self, monkeypatch):
        self._fake(monkeypatch, [4.77], ["2026-09-04"])
        assert sr._yahoo_tnx() == (pytest.approx(0.0477), "2026-09-04")

    def test_basis_points_are_refused(self, monkeypatch):
        self._fake(monkeypatch, [477.0], ["2026-09-04"])
        assert sr._yahoo_tnx() is None

    def test_empty_history_is_none(self, monkeypatch):
        self._fake(monkeypatch, [], [])
        assert sr._yahoo_tnx() is None

    def test_a_dead_feed_is_none_not_an_exception(self):
        assert sr._yahoo_tnx() is None        # conftest's yfinance raises on every call
