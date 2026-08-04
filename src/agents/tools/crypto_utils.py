"""
Crypto detection + symbol normalization for the generalist agent.

The rest of the toolbox is built for equities (fundamentals, DCF, P/E). Crypto
assets have none of that, so we handle them on a separate, price-first path:
resolve a coin name to its Yahoo `XXX-USD` symbol, pull spot / momentum / market
data, and NEVER route them into get_financials / build_model / write_report.

yfinance already serves crypto history under the `-USD` suffix (BTC-USD, ETH-USD,
…), so no new data vendor is needed. This module is the thin, well-tested layer
that decides "is this crypto?" and "what's the Yahoo symbol?" so every crypto
tool agrees on the answer.
"""

from __future__ import annotations

from typing import Optional


# Curated name/alias -> Yahoo base symbol (the part before "-USD"). Covers the
# coins users actually ask about. Anything outside this map still resolves if
# the user gives a known base symbol (e.g. "DOT", "LINK") via _looks_like_base.
_CRYPTO_NAME_TO_SYMBOL = {
    # majors
    "bitcoin": "BTC", "btc": "BTC", "xbt": "BTC",
    "ethereum": "ETH", "eth": "ETH", "ether": "ETH",
    "solana": "SOL", "sol": "SOL",
    "ripple": "XRP", "xrp": "XRP",
    "cardano": "ADA", "ada": "ADA",
    "dogecoin": "DOGE", "doge": "DOGE",
    "polkadot": "DOT", "dot": "DOT",
    "polygon": "MATIC", "matic": "MATIC",
    "avalanche": "AVAX", "avax": "AVAX",
    "chainlink": "LINK", "link": "LINK",
    "litecoin": "LTC", "ltc": "LTC",
    "tron": "TRX", "trx": "TRX",
    "shiba inu": "SHIB", "shiba": "SHIB", "shib": "SHIB",
    "uniswap": "UNI",
    "cosmos": "ATOM", "atom": "ATOM",
    "stellar": "XLM", "xlm": "XLM",
    "monero": "XMR", "xmr": "XMR",
    "bitcoin cash": "BCH", "bch": "BCH",
    "near": "NEAR", "near protocol": "NEAR",
    "aptos": "APT", "apt": "APT",
    "arbitrum": "ARB", "arb": "ARB",
    "optimism": "OP",
    "toncoin": "TON", "ton": "TON",
    "sui": "SUI",
    "hedera": "HBAR", "hbar": "HBAR",
    "internet computer": "ICP", "icp": "ICP",
    "filecoin": "FIL", "fil": "FIL",
    "render": "RNDR", "rndr": "RNDR",
    "injective": "INJ", "inj": "INJ",
    "pepe": "PEPE",
    "bonk": "BONK",
    # stablecoins (rarely "analyzed" but users mention them)
    "tether": "USDT", "usdt": "USDT",
    "usd coin": "USDC", "usdc": "USDC",
    # wrapped / staked majors people say by name
    "wrapped bitcoin": "WBTC", "wbtc": "WBTC",
    # exchange tokens
    "bnb": "BNB", "binance coin": "BNB",
}

# Common human phrasings that mean "this is about crypto" even without a coin name.
_CRYPTO_CONTEXT_WORDS = {
    "crypto", "cryptocurrency", "cryptocurrencies", "coin", "coins",
    "altcoin", "altcoins", "token", "blockchain", "on-chain", "onchain",
}


def _clean(text: str) -> str:
    return (text or "").strip().lower()


def _looks_like_base_symbol(sym: str) -> Optional[str]:
    """
    If `sym` is a bare crypto base symbol we recognize (e.g. 'BTC', 'SOL'),
    return the canonical base. Only recognizes symbols already in the map so we
    never misfire on equity tickers (AAPL, MSFT). Returns None otherwise.
    """
    up = (sym or "").strip().upper()
    # Reverse lookup: the map's values are the canonical bases.
    known_bases = set(_CRYPTO_NAME_TO_SYMBOL.values())
    return up if up in known_bases else None


def normalize_crypto_symbol(raw: str) -> Optional[str]:
    """
    Turn a coin name/alias/symbol into its Yahoo `XXX-USD` symbol, or None if it
    isn't recognizable as crypto.

    Accepts, in order of preference:
      * an already-formed pair: 'BTC-USD', 'eth-usd'  -> 'BTC-USD'
      * a known name/alias:     'Bitcoin', 'ether'    -> 'BTC-USD'
      * a known base symbol:    'SOL', 'doge'         -> 'SOL-USD', 'DOGE-USD'
    """
    s = _clean(raw)
    if not s:
        return None

    # Already a Yahoo crypto pair (…-USD / …-USDT / …-EUR etc.) → normalize casing.
    if "-" in s:
        base, _, quote = s.partition("-")
        base_u = base.upper()
        quote_u = (quote or "usd").upper()
        # Only treat as crypto if the base is a coin we know, to avoid catching
        # things like class-share tickers. Default the quote to USD.
        if _looks_like_base_symbol(base_u) or base in _CRYPTO_NAME_TO_SYMBOL:
            canon = _CRYPTO_NAME_TO_SYMBOL.get(base, base_u)
            return f"{canon}-{quote_u if quote_u else 'USD'}"
        return None

    # Known name / alias.
    if s in _CRYPTO_NAME_TO_SYMBOL:
        return f"{_CRYPTO_NAME_TO_SYMBOL[s]}-USD"

    # Bare known base symbol.
    base = _looks_like_base_symbol(s)
    if base:
        return f"{base}-USD"

    return None


def is_crypto_symbol(sym: str) -> bool:
    """True if `sym` normalizes to a Yahoo crypto pair."""
    return normalize_crypto_symbol(sym) is not None


def detect_crypto_in_query(query: str) -> Optional[str]:
    """
    Scan a free-text query for a crypto asset. Returns the Yahoo `XXX-USD`
    symbol of the first coin found, or None.

    Strategy: check multi-word names first (so 'bitcoin cash' beats 'bitcoin'),
    then single tokens. Bare ambiguous tokens ('link', 'op', 'ton') are only
    matched when a crypto-context word is also present, so we don't hijack
    ordinary English ('the link is broken', 'op-ed').
    """
    q = _clean(query)
    if not q:
        return None

    has_context = any(w in q for w in _CRYPTO_CONTEXT_WORDS)

    # Multi-word names first, longest first.
    multiword = sorted(
        (k for k in _CRYPTO_NAME_TO_SYMBOL if " " in k),
        key=len, reverse=True,
    )
    for name in multiword:
        if name in q:
            return f"{_CRYPTO_NAME_TO_SYMBOL[name]}-USD"

    # Unambiguous single-word coin names (safe to match anywhere).
    _AMBIGUOUS = {"link", "op", "ton", "near", "sui", "atom", "apt", "arb", "inj", "dot", "bnb"}
    tokens = set(q.replace(",", " ").replace(".", " ").split())
    for tok in tokens:
        if tok in _CRYPTO_NAME_TO_SYMBOL and tok not in _AMBIGUOUS:
            return f"{_CRYPTO_NAME_TO_SYMBOL[tok]}-USD"

    # Ambiguous tokens only when the query is clearly about crypto.
    if has_context:
        for tok in tokens:
            if tok in _CRYPTO_NAME_TO_SYMBOL:
                return f"{_CRYPTO_NAME_TO_SYMBOL[tok]}-USD"

    return None
