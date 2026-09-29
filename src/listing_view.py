"""
A valuation stated in the listing the user asked about.

A foreign company is valued on its home listing. Its US line regresses against
the S&P 500, which it barely moves with: AstraZeneca's NYSE shares gave a beta
of 0.50 (the floor) against 0.96 for its London shares on the FTSE 100, and with
the same risk-free rate, premium, cost of debt and tax the model published a
$159.47 fair value on the NYSE line and withheld a $106.61 one on London. So
ensure_state_for_ticker values the home line, and a user who asked about AZN, TM
or SHEL, or named a company that trades on a US exchange, reads the answer per
US share in dollars.

How many home shares one US share represents comes from Yahoo's share counts,
which it states for a US line in US-share equivalents (Toyota: 1.18B ADRs
against 11.8B Tokyo shares). Measured on 2026-09-28 the quotient was 1, 2, 3, 5,
6, 8 or 10 to within 0.03% for AstraZeneca, Shell, HSBC, BP, BHP, Toyota, TSMC,
Novo Nordisk, SAP, Alibaba, Sony, Unilever, Rio Tinto, Shopify, ASML, Ferrari
and HDFC Bank. The price quotient is no substitute: TSMC's ADR trades 16% above
its Taiwan shares, and 5.82 rounds to the wrong ratio. Prices only check that
the two lines are the same claim in the right units.
"""

from __future__ import annotations

import math
import re
from typing import Callable, Dict, Optional

from src.listing_resolver import (
    _SUFFIX_COUNTRY,
    _search_queries,
    better_listing,
    is_analyzable,
    is_depositary,
    is_home_listing,
    is_otc,
    names_might_match,
    same_company,
    venue_suffix,
)

# Yahoo's codes for the US national exchanges: NYSE, Nasdaq (Global Select,
# Global Market, Capital Market), NYSE American, NYSE Arca and Cboe BZX. An OTC
# line is not what "the US listing" of a named company means.
US_EXCHANGES = frozenset({"NYQ", "NYS", "NMS", "NGM", "NCM", "NAS", "ASE", "PCX", "BTS"})

_US_COUNTRY = "United States"
# Countries some mapped exchange is at home in. Luxembourg, Bermuda or Jersey
# have none, so no search can find a home line for an issuer registered there.
_HOME_COUNTRIES = frozenset(_SUFFIX_COUNTRY.values())
# A US price this far from the home price times the ratio is a unit or identity
# error, not a premium. The largest real premium measured was TSMC's, 16%; 25%
# still rejects a neighbouring ratio (5 for 6 is 17% off, 4 for 5 is 20%) only
# together with the share counts, which must also land on it.
_MAX_PREMIUM = 0.25
# Share-count quotients landed within 0.03% of the ratio; 0.5% leaves room for
# a count updated on one line before the other.
_RATIO_TOLERANCE = 0.005
# Depositary ratios in use: whole numbers to 20 (Telkom Indonesia's is 100,
# America Movil's 20), and the inverse for a share worth several receipts
# (POSCO 1/4, Genmab 1/10). Anything else is two counts describing different
# things, not a ratio.
_RATIOS = tuple(sorted({*range(1, 21), 25, 30, 40, 50, 100}
                       | {1 / n for n in (*range(2, 11), 20, 25, 50, 100)}))
# A line the company is actually traded on: at least this share of the US
# line's volume, in US-share units. Stellantis trades 40M shares a day in Milan
# against 21M in New York; Spotify's Frankfurt line trades 430 against 1.7M.
_AT_SCALE = 0.20
# Below this a premium is timing and exchange-rate noise, not worth a sentence.
_STATED_PREMIUM = 0.03
# How many US candidates a name search may spend an .info call on.
_MAX_US_LOOKUPS = 3


def _positive(value) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(float(value)) and float(value) > 0)


def _price(info: dict) -> Optional[float]:
    for key in ("currentPrice", "regularMarketPrice", "previousClose"):
        value = (info or {}).get(key)
        if _positive(value):
            return float(value)
    return None


def _major_unit(currency: Optional[str]) -> Optional[str]:
    return "GBP" if currency == "GBp" else currency


def _fx_rate(from_ccy: Optional[str], to_ccy: str) -> Optional[float]:
    """Spot rate through the scraper's own lookup, so both agree."""
    if not from_ccy:
        return None
    if from_ccy == to_ccy:
        return 1.0
    try:
        from src.financial_scraper import _fx_rate as scraper_rate
    except Exception:
        try:
            from financial_scraper import _fx_rate as scraper_rate
        except Exception:
            return None
    try:
        rate = scraper_rate(from_ccy, to_ccy)
    except Exception:
        return None
    return float(rate) if _positive(rate) else None


def fx_to_usd(currency: Optional[str]) -> Optional[float]:
    """US dollars per unit of ``currency``."""
    return _fx_rate(currency, "USD")


def is_us_exchange_line(info: dict, symbol: str) -> bool:
    """A listing on a US national exchange, not OTC."""
    info = info or {}
    return (not venue_suffix(symbol) and not is_otc(info)
            and str(info.get("exchange") or "").upper() in US_EXCHANGES)


def quote_unit_supported(currency: Optional[str]) -> bool:
    """
    Whether the scraper reads this listing's quote in the right unit.

    London's pence (GBp) are divided by 100 there. Tel Aviv quotes in agorot
    (ILA) and Johannesburg in cents (ZAc), and neither is converted, so a
    valuation on those lines would price the company a hundred times too high.
    """
    if currency == "GBp":
        return True
    return (isinstance(currency, str) and len(currency) == 3 and currency.isupper()
            and currency not in {"ILA", "ZAC"})


def receipt_ratio(*pairs) -> Optional[float]:
    """
    Home shares per US share, from (home count, US count) pairs.

    The first pair whose quotient lands within 0.5% of a ratio in use wins; a
    pair that lands on none (another share class, a stale count) is skipped,
    and None means no pair gave a ratio, so nothing can be converted.
    """
    for home_shares, us_shares in pairs:
        try:
            quotient = float(home_shares) / float(us_shares)
        except (TypeError, ValueError, ZeroDivisionError):
            continue
        if not math.isfinite(quotient) or quotient <= 0:
            continue
        clean = min(_RATIOS, key=lambda ratio: abs(quotient / ratio - 1))
        if abs(quotient / clean - 1) <= _RATIO_TOLERANCE:
            return float(clean)
    return None


def trades_at_scale(candidate: dict, us_line: dict) -> bool:
    """
    Whether ``candidate`` trades at least a fifth of the US line's volume.

    Volumes are compared in US-share units (through the share counts), so a
    line of receipts is not mistaken for a thin one. False when either volume
    or count is missing.
    """
    try:
        quotient = float(candidate["sharesOutstanding"]) / float(us_line["sharesOutstanding"])
        volume = float(candidate["averageVolume"]) / quotient
        return quotient > 0 and volume >= _AT_SCALE * float(us_line["averageVolume"])
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return False


def conversion_factor(view: Optional[dict]) -> Optional[float]:
    """Dollars per US share for one unit of a per-home-share figure; None without a view."""
    if not view:
        return None
    return float(view["usd_per_reporting_unit"]) * float(view["home_shares_per_share"])


def figures_differ(view: Optional[dict]) -> bool:
    """
    Whether a per-home-share figure and the same figure per US share differ.

    When they do (Shell: dollars per London share are half the dollars per
    NYSE share), a figure can be quoted against the wrong share, and only the
    per-US-share one may be quoted as the answer's.
    """
    factor = conversion_factor(view)
    return factor is not None and abs(factor - 1) > 0.005


def price_premium(us_price, home_price_usd, ratio) -> Optional[float]:
    """How far the US share trades above (+) or below (−) the shares it represents."""
    if not (_positive(us_price) and _positive(home_price_usd) and _positive(ratio)):
        return None
    premium = float(us_price) / (float(home_price_usd) * float(ratio)) - 1
    return premium if math.isfinite(premium) else None


def home_line_for(ticker: str, info: dict,
                  rate: Callable[[Optional[str], str], Optional[float]] = _fx_rate) -> Optional[dict]:
    """
    The home listing to value a US line of a foreign company on, or None.

    Only a line the answer can be converted back from qualifies: the same
    issuer on its home exchange, quoted in a unit the scraper reads, with a
    clean receipt ratio, a price that agrees with it, and an exchange rate the
    scraper can convert its price with. A company filing with the SEC as a US
    company stays on its US line. Anything less keeps the ticker's existing
    handling. Never raises.
    """
    try:
        info = info or {}
        if not ticker or venue_suffix(ticker) or info.get("currency") != "USD":
            return None
        country = info.get("country")
        if not country or country == _US_COUNTRY or country not in _HOME_COUNTRIES:
            return None
        # A company that reports to the SEC as a US company (Yum China, Waste
        # Connections, Shopify) trades mainly here and is valued here.
        from src.sec_filer import files_as_us_company
        if files_as_us_company(ticker):
            return None
        upgrade = better_listing(ticker, info)
        if not upgrade:
            return None
        symbol, name = upgrade
        import yfinance as yf
        home = yf.Ticker(symbol).info or {}
        if not (is_home_listing(home, symbol) and not is_otc(home)
                and not is_depositary(home, symbol) and is_analyzable(home)
                and quote_unit_supported(home.get("currency"))):
            return None
        ratio = receipt_ratio(
            (home.get("sharesOutstanding"), info.get("sharesOutstanding")),
            (home.get("impliedSharesOutstanding"), info.get("impliedSharesOutstanding")),
        )
        if ratio is None:
            return None
        listing = _major_unit(home.get("currency"))
        home_price = _price(home)
        if home_price is not None and home.get("currency") == "GBp":
            home_price /= 100.0
        to_usd = rate(listing, "USD")
        premium = price_premium(_price(info), home_price * to_usd if home_price and to_usd else None, ratio)
        if premium is None or abs(premium) > _MAX_PREMIUM:
            return None
        financial = home.get("financialCurrency")
        if financial and financial != listing and rate(listing, financial) is None:
            return None
        return {"symbol": symbol, "name": name, "info": home, "ratio": ratio}
    except Exception:
        return None


def us_line_for(name: Optional[str], country: Optional[str], home_shares,
                home_implied=None) -> Optional[dict]:
    """
    The exchange-listed US line of a company valued on a foreign listing.

    Found by name, then held to the same tests as a move: the same issuer
    (name and domicile), a US exchange rather than OTC, dollar quotes, and a
    clean receipt ratio against the home line's share count. Never raises.
    """
    try:
        if not name:
            return None
        import yfinance as yf
        looked_up = set()
        for query in _search_queries(name):
            try:
                quotes = yf.Search(query, max_results=8).quotes or []
            except Exception:
                continue
            for quote in quotes:
                symbol = quote.get("symbol") or ""
                if (not symbol or venue_suffix(symbol) or symbol in looked_up
                        or quote.get("quoteType") != "EQUITY"
                        or str(quote.get("exchange") or "").upper() not in US_EXCHANGES):
                    continue
                if not (names_might_match(name, quote.get("shortname"))
                        or names_might_match(name, quote.get("longname"))):
                    continue
                if len(looked_up) >= _MAX_US_LOOKUPS:
                    return None
                looked_up.add(symbol)
                info = yf.Ticker(symbol).info or {}
                if not is_us_exchange_line(info, symbol) or info.get("currency") != "USD":
                    continue
                if not same_company(name, info.get("longName") or info.get("shortName")):
                    continue
                if country and info.get("country") and info.get("country") != country:
                    continue
                ratio = receipt_ratio(
                    (home_shares, info.get("sharesOutstanding")),
                    (home_implied, info.get("impliedSharesOutstanding")),
                )
                if ratio is not None:
                    return {"symbol": symbol, "info": info, "ratio": ratio}
        return None
    except Exception:
        return None


def _exchange_name(info: dict) -> str:
    name = str(info.get("fullExchangeName") or info.get("exchange") or "US")
    return "Nasdaq" if name.lower().startswith("nasdaq") else name


def build_view(us_symbol: str, us_info: dict, ratio: float, *, home_symbol: str,
               reporting_currency: Optional[str], home_price: Optional[float],
               to_usd: Callable[[Optional[str]], Optional[float]] = fx_to_usd,
               home_market: bool = True) -> Optional[dict]:
    """
    The user's listing and how to state per-share figures in it, or None.

    ``home_price`` is the valued listing's price in the reporting currency,
    as the model used it. ``home_market`` is False for a main listing outside
    the country of domicile (Stellantis, registered in the Netherlands, trades
    in Milan). Never raises.
    """
    try:
        us_price = _price(us_info)
        if (not us_symbol or (us_info or {}).get("currency") != "USD" or us_price is None
                or not _positive(home_price) or not _positive(ratio) or not reporting_currency):
            return None
        rate = to_usd(reporting_currency)
        if not _positive(rate):
            return None
        premium = price_premium(us_price, float(home_price) * rate, ratio)
        if premium is None or abs(premium) > _MAX_PREMIUM:
            return None
        return {
            "ticker": us_symbol,
            "exchange": _exchange_name(us_info),
            "currency": "USD",
            "price": round(us_price, 2),
            "home_ticker": home_symbol,
            "home_market": bool(home_market),
            "home_shares_per_share": float(ratio),
            "reporting_currency": reporting_currency,
            "usd_per_reporting_unit": float(rate),
            "premium": round(premium, 4),
            **({"market_cap": float(us_info["marketCap"])} if _positive(us_info.get("marketCap")) else {}),
        }
    except Exception:
        return None


def per_us_share(view: Optional[dict], value) -> Optional[float]:
    """A per-home-share figure in the reporting currency, per US share in dollars."""
    if not view or not _positive(value):
        return None
    return round(float(value) * view["usd_per_reporting_unit"] * view["home_shares_per_share"], 2)


def _target_value(headline: Optional[dict], reporting_currency: Optional[str]) -> Optional[float]:
    """The report's 12-month target, when it is stated in the reporting currency."""
    text = str((headline or {}).get("price_target_12m") or "")
    match = re.search(r"(?:\b([A-Z]{3})\s*)?[$€£¥₹]?\s*([\d,]+(?:\.\d+)?)", text)
    if not match:
        return None
    code = match.group(1)
    if code and reporting_currency and code != reporting_currency:
        return None
    try:
        return float(match.group(2).replace(",", ""))
    except ValueError:
        return None


def view_figures(view: Optional[dict], metrics: Optional[dict], headline: Optional[dict] = None,
                 street: Optional[dict] = None) -> Dict[str, object]:
    """
    The valuation's per-share figures per US share: what the model published
    (fair value, its upside against the US price, the 12-month target) or, when
    the point estimate is withheld, the supported range; and the Street's mean
    target, when ``street`` (an external benchmark) states it in the reporting
    currency. Shell's Street target is $52.04 per London share: printed beside
    the $96.47 NYSE price it reads as a target far below the price.
    """
    if not view:
        return {}
    metrics = metrics or {}
    out: Dict[str, object] = {}
    if isinstance(street, dict) and street.get("currency") == view.get("reporting_currency"):
        target = per_us_share(view, street.get("target_mean"))
        if target:
            out["street_target_mean"] = target
    if metrics.get("point_estimate_withheld"):
        try:
            from src.summary_evidence import supported_valuation_span, supported_valuation_values
            span = supported_valuation_span(supported_valuation_values(metrics))
        except Exception:
            span = {}
        low, high = per_us_share(view, span.get("low")), per_us_share(view, span.get("high"))
        if span.get("shape") == "single_estimate" and low:
            out["range"] = [low, low]
        elif span.get("shape") == "range" and low and high:
            out["range"] = [low, high]
        return out
    fair = per_us_share(view, metrics.get("fair_value"))
    if fair:
        out["fair_value"] = fair
        out["upside"] = round(fair / view["price"] - 1, 4)
    target = per_us_share(view, _target_value(headline, view.get("reporting_currency")))
    if target:
        out["price_target_12m"] = target
    return out


def _rate_text(units_per_usd: float) -> str:
    return f"{units_per_usd:,.2f}" if units_per_usd >= 10 else f"{units_per_usd:,.4f}"


def lead_paragraph(view: Optional[dict], *, company: Optional[str], kind: str,
                   figures: Optional[dict] = None) -> str:
    """
    The opening lines of a templated answer, in the user's listing.

    ``kind`` is "withheld", "published" or "refused" (analysed but not valued).
    """
    if not view:
        return ""
    us, home = view["ticker"], view["home_ticker"]
    ratio = view["home_shares_per_share"]
    who = company or us
    verb = "analysed" if kind == "refused" else "valued"
    if ratio == 1:
        shares = f"one {us} share is one {home} share"
    elif ratio > 1:
        shares = f"one {us} share represents {ratio:g} {home} shares"
    else:
        shares = f"{round(1 / ratio)} {us} shares represent one {home} share"
    premium = view.get("premium")
    if isinstance(premium, (int, float)) and abs(premium) >= _STATED_PREMIUM:
        shares += (f" and trades {abs(premium) * 100:.0f}% "
                   f"{'above' if premium > 0 else 'below'} them")
    where = "home" if view.get("home_market", True) else "main"
    text = (f"{us} ({view['exchange']}, ${view['price']:,.2f}): {who} is {verb} on its {where} "
            f"listing, {home}; {shares}.")
    figures = figures or {}
    currency = view.get("reporting_currency")
    basis = (f"Per {us} share" if currency == "USD" else
             f"Per {us} share, at 1 USD = {_rate_text(1 / view['usd_per_reporting_unit'])} {currency}")
    if kind == "withheld" and figures.get("range"):
        low, high = figures["range"]
        if low == high:
            text += f" {basis}, the supported DCF scenario estimate is ${low:,.2f}."
        else:
            text += f" {basis}, the supported valuation-method range is ${low:,.2f}–${high:,.2f}."
    elif kind == "published" and figures.get("fair_value"):
        text += (f" {basis}, the model fair value is ${figures['fair_value']:,.2f}, "
                 f"{figures['upside'] * 100:+.1f}% against ${view['price']:,.2f}")
        if figures.get("price_target_12m"):
            text += f", and the 12-month price target ${figures['price_target_12m']:,.2f}"
        text += "."
        # TSMC's ADR trades 16% above its Taiwan shares: a value 15% above the
        # Taiwan price is about flat against the ADR. Say which price rates it.
        if isinstance(premium, (int, float)) and abs(premium) >= _STATED_PREMIUM:
            text += f" The rating is set against the {home} price."
    if figures.get("street_target_mean"):
        text += f" The Street's mean target is ${figures['street_target_mean']:,.2f} per {us} share."
    return text
