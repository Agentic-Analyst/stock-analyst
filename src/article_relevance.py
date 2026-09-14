"""Deterministic company-identity checks for the news pipeline.

An LLM relevance score is useful for ranking investment significance, but it
must not be the first or only control on whether an article is about the
subject at all.  Search queries routinely return industry stories and stories
about peers; those must not be saved under the subject ticker or counted as
coverage unless the subject is actually mentioned.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Tuple
from urllib.parse import unquote, urlparse


_LEGAL_SUFFIXES = {
    "ag", "asa", "co", "company", "corp", "corporation", "group", "holdings",
    "inc", "incorporated", "limited", "llc", "lp", "ltd", "nv", "plc", "sa",
    "se", "spa",
}
_GENERIC_NAME_WORDS = {
    "american", "global", "international", "national", "new", "the", "united",
}
_COMMON_TICKER_WORDS = {
    "A", "AI", "ALL", "ARE", "AT", "BE", "BY", "C", "CAN", "CEO", "FOR",
    "GO", "HAS", "I", "IN", "IT", "ON", "OR", "SO", "T", "TO", "TV", "US",
}
_CONSUMER_SERVICE_TITLE_PATTERNS = (
    re.compile(r"\bwhere\s+to\s+(?:buy|pre[- ]?order)\b", re.IGNORECASE),
    re.compile(r"\bhow\s+to\s+(?:buy|pre[- ]?order)\b", re.IGNORECASE),
    re.compile(r"\blive\s+pre[- ]?order\s+updates?\b", re.IGNORECASE),
    re.compile(r"\bwhich\b.{0,60}\bretailers?\b.{0,40}\b(?:have|has|with)\s+stock\b", re.IGNORECASE),
    re.compile(r"\bavailability\s+(?:tracker|updates?)\b", re.IGNORECASE),
    re.compile(r"\bbest\b.{0,50}\bdeals?\b", re.IGNORECASE),
)
_FINANCIAL_MATERIALITY_RE = re.compile(
    r"\b(?:analyst|earnings|forecast|guidance|margin|market\s+share|profit|"
    r"revenue|sales|shipment|supply\s+chain|units?\s+sold)\b",
    re.IGNORECASE,
)


def _normalized_words(value: Any) -> List[str]:
    return re.findall(r"[a-z0-9]+", str(value or "").casefold())


def company_aliases(company_name: str | None) -> List[str]:
    """Build conservative textual aliases from a legal company name."""
    words = _normalized_words(company_name)
    while words and words[-1] in _LEGAL_SUFFIXES:
        words.pop()
    if not words:
        return []

    aliases = {" ".join(words)}
    # Some brands join an initialism to a word in their legal name but are
    # routinely written with a space in headlines (for example, JPMorgan / JP
    # Morgan).  Retain that observable spelling without maintaining a
    # ticker-specific alias table.
    raw_name = str(company_name or "")
    first_raw_word = re.findall(r"[A-Za-z0-9]+", raw_name)
    if first_raw_word:
        split_brand = re.sub(r"^([A-Z]{2,})([A-Z][a-z]+)$", r"\1 \2", first_raw_word[0])
        if split_brand != first_raw_word[0]:
            aliases.add(" ".join(_normalized_words(split_brand)))
    # "JPMorgan Chase & Co." is often shortened to JPMorgan.  Only use a
    # single-word alias when it is distinctive enough; "United" and similar
    # legal-name fragments would create excessive false positives.
    if len(words[0]) >= 5 and words[0] not in _GENERIC_NAME_WORDS:
        aliases.add(words[0])
    return sorted(aliases, key=lambda value: (-len(value), value.count(" "), value))


_ATTRIBUTION_VERBS = (
    "according to", "argues", "cuts", "downgrades", "estimates", "expects",
    "forecasts", "maintains", "predicts", "raises", "rates", "reiterates",
    "reportedly says", "says", "sees", "sets", "upgrades", "warns",
)
_EXTERNAL_TARGET_RE = re.compile(
    r"\b(?:bitcoin|bond|bonds|commodity|commodities|crypto|dollar|gold|index|"
    r"oil|palladium|platinum|rates?|shares?|silver|stock|stocks|treasury|"
    r"yield|yields)\b",
    re.IGNORECASE,
)


def article_uses_subject_only_as_commentator(
    article: Dict[str, Any], ticker: str, company_name: str | None = None,
) -> bool:
    """Identify headlines where the subject is the analyst, not the investment.

    A search for a bank or broker frequently returns its research calls on a
    different company, commodity, or market.  Mentioning the subject prominently
    establishes identity but not *subject role*.  Those articles must not become
    evidence about the bank's own earnings, valuation, catalysts, or risks.

    The rule is intentionally narrow: it requires an external target before the
    company alias and a research-attribution verb around the alias.  A headline
    beginning with the subject ("JPMorgan raises its dividend") remains eligible.
    """
    title = str(article.get("title") or "")
    title_words = " ".join(_normalized_words(title))
    if not title_words:
        return False

    aliases = company_aliases(company_name)
    positions: List[Tuple[int, int]] = []
    for alias in aliases:
        normalized = " ".join(_normalized_words(alias))
        if not normalized:
            continue
        match = re.search(
            rf"(?<![a-z0-9]){re.escape(normalized)}(?![a-z0-9])", title_words
        )
        if match:
            positions.append((match.start(), match.end()))
    if not positions:
        return False

    start, end = min(positions)
    prefix = title_words[:start].strip()
    suffix = title_words[end:].strip()
    if not prefix or not _EXTERNAL_TARGET_RE.search(prefix):
        return False

    attribution = "|".join(re.escape(value) for value in _ATTRIBUTION_VERBS)
    attributed_after = re.match(
        rf"^(?:analysts?\s+|strategists?\s+|economists?\s+)?(?:{attribution})\b",
        suffix,
    )
    attributed_before = re.search(
        rf"\b(?:according\s+to|as)\s*$", prefix,
    ) and re.search(rf"\b(?:{attribution})\b", suffix)
    return bool(attributed_after or attributed_before)


def article_is_about_subject(
    article: Dict[str, Any], ticker: str, company_name: str | None = None,
) -> bool:
    """Require both a subject identity mention and an investee/company role."""
    return article_mentions_subject(article, ticker, company_name) and not (
        article_uses_subject_only_as_commentator(article, ticker, company_name)
    )


def _article_surface(article: Dict[str, Any]) -> Tuple[str, str, str]:
    title = str(article.get("title") or "")
    snippet = str(article.get("serpapi_snippet") or article.get("snippet") or "")
    content = str(article.get("content") or article.get("text") or "")[:6000]
    url = str(article.get("source_url") or article.get("url") or "")
    try:
        parsed = urlparse(url)
        url_text = unquote(f"{parsed.netloc} {parsed.path} {parsed.query}")
    except ValueError:
        url_text = url
    return "\n".join((title, snippet)), content, url_text


def article_mentions_subject(
    article: Dict[str, Any], ticker: str, company_name: str | None = None,
) -> bool:
    """Return whether observable article text identifies the subject.

    Metadata fields such as ``ticker`` and ``company`` are deliberately not
    used: the scraper assigns those fields from the search subject, so an
    unrelated result already carries the desired labels.
    """
    header, content, url_text = _article_surface(article)
    header_folded = " ".join(_normalized_words(f"{header}\n{url_text}"))
    content_folded = " ".join(_normalized_words(content))
    lead_folded = " ".join(_normalized_words(content[:2000]))

    for alias in company_aliases(company_name):
        alias_words = " ".join(_normalized_words(alias))
        if alias_words:
            pattern = rf"(?<![a-z0-9]){re.escape(alias_words)}(?![a-z0-9])"
            if re.search(pattern, header_folded):
                return True
            # A passing reference buried in an article about a peer is not
            # sufficient prominence. A subject should occur in the lead, or
            # recur throughout the body when the scraper retained boilerplate
            # before the actual article.
            if len(re.findall(pattern, lead_folded)) >= 2 or len(re.findall(pattern, content_folded)) >= 4:
                return True

    symbol = str(ticker or "").strip().upper()
    if not symbol:
        return False
    escaped = re.escape(symbol)
    # Explicit exchange-qualified and cashtag forms are safe even for short
    # symbols such as C or T.
    if re.search(
        rf"(?:\$|NASDAQ\s*:\s*|NYSE\s*:\s*|LSE\s*:\s*){escaped}(?![A-Z0-9])",
        header,
    ):
        return True
    if symbol not in _COMMON_TICKER_WORDS and len(symbol) >= 3:
        if re.search(
            rf"(?<![A-Z0-9]){escaped}(?![A-Z0-9])",
            f"{header}\n{content[:2000]}",
        ):
            return True
        url_folded = " ".join(_normalized_words(url_text))
        if re.search(
            rf"(?<![a-z0-9]){re.escape(symbol.casefold())}(?![a-z0-9])",
            url_folded,
        ):
            return True
    return False


def filter_subject_articles(
    articles: Iterable[Dict[str, Any]], ticker: str, company_name: str | None = None,
) -> Tuple[List[Dict[str, Any]], int]:
    rows = list(articles or [])
    kept = [row for row in rows if article_is_about_subject(row, ticker, company_name)]
    return kept, len(rows) - len(kept)


def investment_relevance_score_cap(article: Dict[str, Any]) -> float | None:
    """Cap clearly consumer-service content unless it contains business evidence.

    Buying guides and inventory trackers mention a company's products but are
    not, by themselves, investment research.  This deliberately narrow guard
    does not suppress coverage that discusses sales, shipments, guidance,
    margins, or other financially material evidence.
    """
    title = str(article.get("title") or "")
    snippet = str(article.get("serpapi_snippet") or article.get("snippet") or "")
    if not any(pattern.search(title) for pattern in _CONSUMER_SERVICE_TITLE_PATTERNS):
        return None
    if _FINANCIAL_MATERIALITY_RE.search(f"{title}\n{snippet}"):
        return None
    return 3.0
