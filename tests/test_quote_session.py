"""A live price is not called a close (18 Nov 2026 Sonnet check).

At 1:52 pm ET Costco's answer said it "closed at $1,112.99", and Robinhood's
"closed at $69.48 on Nov 18": the price tool gave a latest price and a
previous close, and nothing said the session was still open.
"""
from datetime import datetime, timezone

import pandas as pd

from src.agents.tools.data_tools import CRYPTO_PRICE, LAST_CLOSE, LIVE_PRICE, quote_session


def _bars(*days, tz="America/New_York"):
    return pd.DatetimeIndex([pd.Timestamp(d) for d in days]).tz_localize(tz)


def _at(text):
    return datetime.fromisoformat(text).astimezone(timezone.utc)


def test_today_s_bar_before_the_close_is_live():
    index = _bars("2026-11-17", "2026-11-18")
    assert quote_session(index, "COST", _at("2026-11-18T13:52:00-05:00")) == LIVE_PRICE


def test_after_the_close_or_before_today_s_bar_it_is_a_close():
    assert quote_session(_bars("2026-11-17", "2026-11-18"), "COST",
                         _at("2026-11-18T16:05:00-05:00")) == LAST_CLOSE
    # Pre-market: the newest bar is yesterday's.
    assert quote_session(_bars("2026-11-16", "2026-11-17"), "COST",
                         _at("2026-11-18T08:00:00-05:00")) == LAST_CLOSE
    # Saturday.
    assert quote_session(_bars("2026-11-19", "2026-11-20"), "COST",
                         _at("2026-11-21T12:00:00-05:00")) == LAST_CLOSE


def test_each_exchange_uses_its_own_clock():
    # 1:52 pm in New York is 3:52 am next day in Tokyo: Kioxia's bar is a close.
    tokyo = _bars("2026-11-17", "2026-11-18", tz="Asia/Tokyo")
    assert quote_session(tokyo, "285A.T", _at("2026-11-18T13:52:00-05:00")) == LAST_CLOSE
    assert quote_session(tokyo, "285A.T", _at("2026-11-18T10:00:00+09:00")) == LIVE_PRICE


def test_crypto_and_unknown_cases():
    assert quote_session(_bars("2026-11-18"), "BTC-USD") == CRYPTO_PRICE
    assert quote_session(pd.DatetimeIndex([pd.Timestamp("2026-11-18")]), "COST") is None
    assert quote_session(_bars("2026-11-18", tz="America/Sao_Paulo"), "PETR4.SA") is None
    assert quote_session([], "COST") is None
