"""
What a stock's price did, in the terms a "why did it move" answer needs.

"Why did Cerebras crash" was answered from today's quote alone: -4.1% on the
day, "no clear catalyst". The crash the user meant was the slide from $212.41
on September 22 to $166.43 on October 2 (-21.6%, the S&P 500 roughly flat),
with an 8.9% fall on September 30 on 2.6x normal volume. Every figure here is
computed from daily closes so the answer can name the move, its dates and the
sessions that made it before it explains them.

Pure functions over pandas Series/DataFrames; the tool (agents/tools/
move_tools.py) fetches the data. Never raises on short or empty input: a
missing piece comes back as None.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

# Bars per look-back window. A month is what "crashed" usually means when the
# user does not say "today"; the agent can ask for longer. A market that trades
# every day (crypto) counts calendar days: 252 of its bars are 8.3 months, and
# Bitcoin's "52-week high" came out at $86,603 (September) instead of $115,271.
WINDOW_SESSIONS = {"5d": 5, "1mo": 21, "3mo": 63, "6mo": 126, "1y": 252}
WINDOW_DAYS = {"5d": 7, "1mo": 30, "3mo": 91, "6mo": 182, "1y": 365}
_WINDOW_ALIASES = {
    "1w": "5d", "1wk": "5d", "week": "5d", "5d": "5d",
    "1m": "1mo", "1mo": "1mo", "month": "1mo", "30d": "1mo",
    "3m": "3mo", "3mo": "3mo", "quarter": "3mo",
    "6m": "6mo", "6mo": "6mo",
    "1y": "1y", "12mo": "1y", "year": "1y", "52w": "1y", "ytd": "ytd",
}
_BIGGEST_DAYS = 5
_VOLUME_BASE_SESSIONS = 50


def _finite(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _day(index_value: Any) -> str:
    return str(getattr(index_value, "date", lambda: index_value)())


def _pct(new: float, old: float) -> Optional[float]:
    return round((new / old - 1.0) * 100.0, 2) if old else None


def latest_and_previous_close(closes, live_price: Optional[float] = None) -> Tuple[Optional[float], Optional[float]]:
    """``(latest, previous_close)`` from daily closes, after the bell included.

    Yahoo publishes the current session's daily bar before it has a close: in
    the evening its Close is NaN while the volume is already there. Dropping
    that row made yesterday's close the "latest" price and the day before the
    "previous close", so at 00:14 UTC Cerebras was reported "down 1.2% at
    $175.05" (October 7's move) on a day it fell 4.1%. A bar without a close
    means the last valid close IS the previous close and the latest price is
    the live one.
    """
    live = _finite(live_price)
    if closes is None or len(closes) == 0:
        return live, None
    valid = closes.dropna()
    if len(valid) == 0:
        return live, None
    if _finite(closes.iloc[-1]) is None:
        return live, float(valid.iloc[-1])
    previous = float(valid.iloc[-2]) if len(valid) >= 2 else None
    return float(valid.iloc[-1]), previous


def _valid_closes(daily):
    if daily is None or getattr(daily, "empty", True) or "Close" not in daily:
        return None
    closes = daily["Close"].dropna()
    return closes if len(closes) else None


def largest_swing(closes, direction: str = "down") -> Optional[Dict[str, Any]]:
    """The deepest peak-to-trough fall ("down") or trough-to-peak rise ("up")."""
    if closes is None or len(closes) < 2:
        return None
    values = [float(v) for v in closes]
    best = None
    anchor = 0
    for i in range(1, len(values)):
        if direction == "down":
            if values[i] > values[anchor]:
                anchor = i
            move = values[i] / values[anchor] - 1.0
            better = best is None or move < best[2]
        else:
            if values[i] < values[anchor]:
                anchor = i
            move = values[i] / values[anchor] - 1.0
            better = best is None or move > best[2]
        if better and i != anchor:
            best = (anchor, i, move)
    if best is None or best[2] == 0:
        return None
    start, end, move = best
    return {
        "direction": direction,
        "start_date": _day(closes.index[start]),
        "start_close": round(values[start], 2),
        "end_date": _day(closes.index[end]),
        "end_close": round(values[end], 2),
        "change_pct": round(move * 100.0, 2),
        "sessions": end - start,
    }


def normalize_window(window: Optional[str]) -> str:
    """The window the agent asked for, in this module's terms ("3M" is "3mo")."""
    return _WINDOW_ALIASES.get((window or "1mo").strip().lower(), "1mo")


def trades_every_day(closes) -> bool:
    """Weekend bars: a 24/7 market whose windows count calendar days."""
    try:
        return any(stamp.weekday() >= 5 for stamp in closes.index[-30:])
    except AttributeError:
        return False


def window_bars(window: str, closes) -> int:
    """Bars in a window: sessions for an exchange, days for a 24/7 market."""
    if window == "ytd":
        try:
            year = closes.index[-1].year
            return max(1, sum(1 for stamp in closes.index if stamp.year == year))
        except AttributeError:
            return 21
    table = WINDOW_DAYS if trades_every_day(closes) else WINDOW_SESSIONS
    return table.get(window, table["1mo"])


def biggest_days(daily, sessions: int, count: int = _BIGGEST_DAYS,
                 session_open: bool = False, between: Optional[Tuple[str, str]] = None,
                 sign: int = 0) -> List[Dict[str, Any]]:
    """The largest one-day moves in the last ``sessions``, oldest first.

    Volume is compared with the average of the 50 sessions before each day, so
    a heavy-volume break reads differently from a drift on thin trading. A
    session still trading has only part of its volume: SoftBank 41 minutes into
    Tokyo's session read 0.4x on its way to about 2.6x. Its ratio is marked
    ``volume_so_far`` instead of being compared as if complete.
    """
    closes = _valid_closes(daily)
    if closes is None or len(closes) < 2:
        return []
    volume = daily["Volume"] if "Volume" in daily else None
    changes = closes.pct_change()
    recent = changes.iloc[-sessions:].dropna()
    if between:
        # Only the sessions inside a move (after its start, up to its end),
        # and only those going its way: a +12% rally day explains no fall.
        recent = recent[[between[0] < _day(stamp) <= between[1] for stamp in recent.index]]
    if sign:
        recent = recent[recent * sign > 0]
    ranked = sorted(recent.items(), key=lambda item: abs(item[1]), reverse=True)[:count]
    out = []
    for stamp, change in sorted(ranked, key=lambda item: item[0]):
        row = {"date": _day(stamp), "change_pct": round(float(change) * 100.0, 2),
               "close": round(float(closes.loc[stamp]), 2)}
        if volume is not None:
            position = daily.index.get_loc(stamp)
            base = volume.iloc[max(0, position - _VOLUME_BASE_SESSIONS):position].dropna()
            today = _finite(volume.iloc[position])
            if today and len(base) >= 10 and float(base.mean()) > 0:
                ratio = round(today / float(base.mean()), 1)
                if session_open and position == len(daily.index) - 1:
                    row["volume_so_far_vs_full_day_average"] = ratio
                    row["session_in_progress"] = True
                else:
                    row["volume_vs_average"] = ratio
        out.append(row)
    return out


def performance(closes, latest: Optional[float]) -> Dict[str, Optional[float]]:
    """Percent change to the latest price over the usual horizons."""
    if closes is None or len(closes) == 0 or not latest:
        return {}
    out: Dict[str, Optional[float]] = {}
    table = WINDOW_DAYS if trades_every_day(closes) else WINDOW_SESSIONS
    for label in ("5d", "1mo", "3mo", "6mo", "1y"):
        bars = table[label]
        if len(closes) > bars:
            out[label] = _pct(latest, float(closes.iloc[-bars - 1]))
    try:
        year = closes.index[-1].year
        prior = closes[[stamp.year < year for stamp in closes.index]]
        if len(prior):
            out["ytd"] = _pct(latest, float(prior.iloc[-1]))
    except AttributeError:
        pass
    return out


def range_and_listing(daily, latest: Optional[float], history_days_requested: int) -> Dict[str, Any]:
    """52-week high and low, the drawdown from the high, and a recent listing.

    A first bar well inside the requested history means the stock listed then:
    the move since its first close is often what "crashed" refers to for a
    recent IPO (Cerebras: first close $311.07 on May 14, 2026).
    """
    closes = _valid_closes(daily)
    if closes is None:
        return {}
    year = closes.iloc[-(365 if trades_every_day(closes) else 252):]
    high_at = year.idxmax()
    low_at = year.idxmin()
    out: Dict[str, Any] = {
        "high_52w": round(float(year.max()), 2), "high_52w_date": _day(high_at),
        "low_52w": round(float(year.min()), 2), "low_52w_date": _day(low_at),
    }
    if latest:
        out["from_52w_high_pct"] = _pct(latest, float(year.max()))
    try:
        span_days = (closes.index[-1] - closes.index[0]).days
    except (TypeError, AttributeError):
        span_days = None
    if span_days is not None and span_days < history_days_requested - 30:
        out["listed_since"] = _day(closes.index[0])
        out["first_close"] = round(float(closes.iloc[0]), 2)
        if latest:
            out["since_first_close_pct"] = _pct(latest, float(closes.iloc[0]))
    return out


def index_change(index_closes, start_date: str, end_date: str) -> Optional[float]:
    """An index's close-to-close change over the same dates (market or not?)."""
    if index_closes is None or len(index_closes) == 0:
        return None
    closes = index_closes.dropna()
    days = [_day(stamp) for stamp in closes.index]
    try:
        start = max(i for i, d in enumerate(days) if d <= start_date)
        end = max(i for i, d in enumerate(days) if d <= end_date)
    except ValueError:
        return None
    return _pct(float(closes.iloc[end]), float(closes.iloc[start]))


def _from_extreme(scan, latest: float, which: str) -> Optional[Dict[str, Any]]:
    if scan is None or len(scan) < 2:
        return None
    stamp = scan.idxmax() if which == "high" else scan.idxmin()
    level = float(scan.loc[stamp])
    return {"date": _day(stamp), "close": round(level, 2), "change_pct": _pct(latest, level)}


def day_change(frame) -> Optional[float]:
    """The last session's change from a frame whose last close is live."""
    if frame is None or len(frame) < 2:
        return None
    return _pct(float(frame["Close"].iloc[-1]), float(frame["Close"].iloc[-2]))


def with_live_close(daily, live_price: Optional[float]):
    """Daily bars whose last, still-open session carries the live price.

    See ``latest_and_previous_close``: the evening bar has volume but no
    close. Filling it once means today's move counts everywhere (the day's
    change, the biggest days, the horizons) instead of silently vanishing.
    """
    if daily is None or getattr(daily, "empty", True) or "Close" not in daily:
        return None
    frame = daily.copy()
    live = _finite(live_price)
    if _finite(frame["Close"].iloc[-1]) is None and live is not None:
        frame.iloc[-1, frame.columns.get_loc("Close")] = live
    frame = frame[frame["Close"].notna()]
    return frame if len(frame) else None


def describe_move(daily, live_price: Optional[float], window: str = "1mo",
                  direction: str = "auto", history_days_requested: int = 730,
                  index_closes=None, index_name: str = "S&P 500",
                  session_open: bool = False) -> Optional[Dict[str, Any]]:
    """Everything above for one ticker, or None without usable daily closes."""
    frame = with_live_close(daily, live_price)
    if frame is None:
        return None
    closes = frame["Close"]
    latest = float(closes.iloc[-1])
    previous = float(closes.iloc[-2]) if len(closes) >= 2 else None
    window = normalize_window(window)
    sessions = window_bars(window, closes)
    scan = closes.iloc[-(sessions + 1):]
    down = largest_swing(scan, "down")
    up = largest_swing(scan, "up")
    if direction == "down":
        episode = down
    elif direction == "up":
        episode = up
    else:
        candidates = [e for e in (down, up) if e]
        episode = max(candidates, key=lambda e: abs(e["change_pct"])) if candidates else None
    today_missing = _finite(daily["Close"].iloc[-1]) is None and _finite(live_price) is None
    out: Dict[str, Any] = {
        "latest_price": round(latest, 2),
        "previous_close": round(previous, 2) if previous is not None else None,
        "day_change_pct": _pct(latest, previous) if previous else None,
        "as_of_session": _day(frame.index[-1]),
        "window": window,
        "performance": performance(closes, latest),
        **range_and_listing(frame, latest, history_days_requested),
        "episode": episode,
        # Where the price stands against the window's extremes: "why is X
        # down" is about the fall from the high to now, which is not always
        # the window's largest swing (MU's was a September dip it had since
        # recovered).
        "from_window_high": _from_extreme(scan, latest, "high"),
        "from_window_low": _from_extreme(scan, latest, "low"),
        "biggest_days": biggest_days(frame, sessions, session_open=session_open),
    }
    if today_missing:
        # Today's bar has no close and no live price came back: the figures
        # above end at the previous session, so do not call it today's move.
        out["latest_session_missing"] = _day(daily.index[-1])
        out["note"] = ("Today's price is not available yet; latest_price and day_change_pct "
                       f"are for the session of {out['as_of_session']}.")
    if session_open:
        out["session_in_progress"] = True
    if episode:
        out["episode"] = {**episode, "since_end_pct": _pct(latest, episode["end_close"]),
                          # The sessions that made the move: what its drivers
                          # have to explain (Intel's slide was Sep 25, Sep 28,
                          # Oct 5, Oct 6 and Oct 8, not September's rallies).
                          "sessions_that_made_it": biggest_days(
                              frame, sessions, session_open=session_open,
                              between=(episode["start_date"], episode["end_date"]),
                              sign=-1 if episode["direction"] == "down" else 1)}
        market = index_change(index_closes, episode["start_date"], episode["end_date"])
        if market is not None:
            out["episode"]["market_index"] = index_name
            out["episode"]["market_same_dates_pct"] = market
    return out
