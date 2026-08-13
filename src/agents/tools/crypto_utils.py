"""
Crypto detection + symbol normalization for the generalist agent.

The rest of the toolbox is built for equities (fundamentals, DCF, P/E). Crypto
assets have none of that, so we handle them on a separate, price-first path:
resolve a coin name to its Yahoo `XXX-USD` symbol, pull spot / momentum / market
data, and NEVER route them into get_financials / build_model / write_report.

yfinance serves crypto history under the `-USD` suffix, but the BASE is not
always the plain token symbol: Yahoo disambiguates many coins with a numeric
CoinMarketCap id (Bittensor = TAO22974-USD; TAO-USD is a different, thin
asset). Worse, several bare pairs return data for the WRONG coin (ARB-USD is
"ARbit", not Arbitrum). This module owns that mapping so every crypto tool
agrees on the answer, and provides a live Yahoo-search fallback
(`search_crypto_symbol`) for anything outside the curated map.

Safety rule: several tools pass EQUITY tickers through
`normalize_crypto_symbol` first, so bare-symbol recognition must never collide
with a real stock (W=Wayfair, S=SentinelOne, AR=Antero, DASH=DoorDash,
BEAM=Beam Therapeutics, AXS=Axis Capital, SAND=Sandstorm Gold, ...). Full
names are always safe; bare symbols are curated.
"""

from __future__ import annotations

import time
from typing import Dict, Optional


# Curated name/alias -> Yahoo base symbol (the part before "-USD"). Values are
# the EXACT Yahoo bases, numeric CMC suffix included where Yahoo requires it
# (live-verified 2026-08). Anything outside this map still resolves through
# `search_crypto_symbol` (live Yahoo search + data probe) at the tool layer.
_CRYPTO_NAME_TO_SYMBOL = {
    # majors
    "bitcoin": "BTC", "btc": "BTC", "xbt": "BTC",
    "ethereum": "ETH", "eth": "ETH", "ether": "ETH",
    "solana": "SOL", "sol": "SOL",
    "ripple": "XRP", "xrp": "XRP",
    "cardano": "ADA", "ada": "ADA",
    "dogecoin": "DOGE", "doge": "DOGE",
    "polkadot": "DOT", "dot": "DOT",
    "avalanche": "AVAX", "avax": "AVAX",
    "chainlink": "LINK", "link": "LINK",
    "litecoin": "LTC", "ltc": "LTC",
    "tron": "TRX", "trx": "TRX",
    "shiba inu": "SHIB", "shiba": "SHIB", "shib": "SHIB",
    "cosmos": "ATOM", "atom": "ATOM",
    "stellar": "XLM", "xlm": "XLM",
    "monero": "XMR", "xmr": "XMR",
    "bitcoin cash": "BCH", "bch": "BCH",
    "near": "NEAR", "near protocol": "NEAR",
    "hedera": "HBAR", "hbar": "HBAR",
    "internet computer": "ICP", "icp": "ICP",
    "filecoin": "FIL", "fil": "FIL",
    "injective": "INJ", "inj": "INJ",
    "optimism": "OP",
    "bonk": "BONK",
    # Yahoo-suffixed bases: the bare pair is dead or the WRONG coin
    "uniswap": "UNI7083", "uni": "UNI7083",
    "toncoin": "TON11419", "ton": "TON11419",
    "aptos": "APT21794", "apt": "APT21794",
    "arbitrum": "ARB11841", "arb": "ARB11841",
    "sui": "SUI20947",
    "pepe": "PEPE24478",
    "render": "RENDER", "rndr": "RENDER",
    "polygon": "POL28321", "matic": "POL28321", "pol": "POL28321",
    "bittensor": "TAO22974", "tao": "TAO22974",
    "the graph": "GRT6719", "grt": "GRT6719",
    "immutable": "IMX10603", "imx": "IMX10603",
    "stacks": "STX4847", "stx": "STX4847",
    "mantle": "MNT27075", "mnt": "MNT27075",
    "starknet": "STRK22691", "strk": "STRK22691",
    "hyperliquid": "HYPE32196",
    "apecoin": "APE18876", "ape": "APE18876",
    "official trump": "TRUMP35336", "trump coin": "TRUMP35336",
    "spx6900": "SPX28081",
    "popcat": "POPCAT28782",
    "morpho": "MORPHO34104",
    "aerodrome": "AERO29270", "aero": "AERO29270",
    "ethena usde": "USDE29470", "usde": "USDE29470",
    "walrus": "WAL36119",
    # plain -USD alts, live-verified correct without suffix
    "sei": "SEI", "celestia": "TIA", "tia": "TIA",
    "ondo": "ONDO", "pyth": "PYTH", "ethena": "ENA", "ena": "ENA",
    "dogwifhat": "WIF", "wif": "WIF",
    "floki": "FLOKI", "kaspa": "KAS", "kas": "KAS",
    "dydx": "DYDX", "multiversx": "EGLD", "egld": "EGLD",
    "helium": "HNT", "hnt": "HNT",
    "lido": "LDO", "lido dao": "LDO", "ldo": "LDO",
    "curve": "CRV", "crv": "CRV",
    "aave": "AAVE", "algorand": "ALGO", "algo": "ALGO",
    "thorchain": "RUNE", "rune": "RUNE",
    "pendle": "PENDLE",
    "jito": "JTO", "jto": "JTO",
    "worldcoin": "WLD", "wld": "WLD",
    "arweave": "AR", "raydium": "RAY",
    "rocket pool": "RPL", "rpl": "RPL",
    "blur": "BLUR", "eigenlayer": "EIGEN", "eigen": "EIGEN",
    "fetch.ai": "FET", "fetch ai": "FET", "fet": "FET",
    "artificial superintelligence": "FET",
    "maker": "MKR", "mkr": "MKR",
    "tezos": "XTZ", "xtz": "XTZ",
    "ethereum classic": "ETC",
    "zcash": "ZEC", "zec": "ZEC",
    "quant": "QNT", "qnt": "QNT",
    "chiliz": "CHZ", "chz": "CHZ",
    "cronos": "CRO", "cro": "CRO",
    "gnosis": "GNO", "gno": "GNO",
    "kava": "KAVA", "mina": "MINA",
    "theta": "THETA", "vechain": "VET",
    "the sandbox": "SAND", "sandbox": "SAND",
    "decentraland": "MANA", "axie infinity": "AXS",
    "gala": "GALA", "flow": "FLOW",
    "celo": "CELO", "akash": "AKT", "akt": "AKT",
    "conflux": "CFX", "flare": "FLR",
    "kaia": "KAIA", "berachain": "BERA", "bera": "BERA",
    "notcoin": "NOT",
    # stablecoins (rarely "analyzed" but users mention them)
    "tether": "USDT", "usdt": "USDT",
    "usd coin": "USDC", "usdc": "USDC",
    "dai": "DAI",
    # wrapped / staked majors people say by name
    "wrapped bitcoin": "WBTC", "wbtc": "WBTC",
    # exchange tokens
    "bnb": "BNB", "binance coin": "BNB",
    "okb": "OKB", "bitget token": "BGB", "bgb": "BGB",
}

# Bare bases that must NEVER be recognized as crypto from a ticker-shaped
# input, because they collide with real equity tickers (W=Wayfair,
# S=SentinelOne, AR=Antero, DASH=DoorDash, BEAM=Beam Therapeutics, AXS=Axis
# Capital, SAND=Sandstorm Gold, NEO=NeoGenomics, LEO=BNY fund, OM=Outset
# Medical, FLR=Fluor, WAL=Western Alliance, EOS=Eaton Vance fund) or read as
# ordinary English in ticker position (ETC, NOT, VET). Their coins stay
# reachable via the full-name aliases above (or live search). Only bases
# WITHOUT an alias key belong here — alias keys resolve before this guard.
_EQUITY_COLLISION_BASES = {
    "W", "S", "AR", "RAY", "DASH", "BEAM", "AXS", "SAND", "MANA", "EOS",
    "NEO", "LEO", "OM", "FLR", "WAL", "CFX", "VET", "ETC", "NOT",
}

# Common human phrasings that mean "this is about crypto" even without a coin name.
_CRYPTO_CONTEXT_WORDS = {
    "crypto", "cryptocurrency", "cryptocurrencies", "coin", "coins",
    "altcoin", "altcoins", "token", "blockchain", "on-chain", "onchain",
}


def _clean(text: str) -> str:
    return (text or "").strip().lower()


def _known_bases() -> set:
    return set(_CRYPTO_NAME_TO_SYMBOL.values())


def _looks_like_base_symbol(sym: str) -> Optional[str]:
    """
    If `sym` is a crypto base we recognize — either an alias key ('TAO') or an
    exact Yahoo base value ('TAO22974') — return the canonical Yahoo base.
    Equity-colliding bases are refused so ticker traffic never gets hijacked.
    Returns None otherwise.
    """
    up = (sym or "").strip().upper()
    if not up or up in _EQUITY_COLLISION_BASES:
        return None
    mapped = _CRYPTO_NAME_TO_SYMBOL.get(up.lower())
    if mapped:
        return mapped
    return up if up in _known_bases() else None


def normalize_crypto_symbol(raw: str) -> Optional[str]:
    """
    Turn a coin name/alias/symbol into its Yahoo `XXX-USD` symbol, or None if it
    isn't recognizable as crypto.

    Accepts, in order of preference:
      * an already-formed pair: 'BTC-USD', 'tao-usd' -> 'BTC-USD', 'TAO22974-USD'
      * a known name/alias:     'Bitcoin', 'bittensor' -> 'BTC-USD', 'TAO22974-USD'
      * a known base symbol:    'SOL', 'TAO22974'      -> 'SOL-USD', 'TAO22974-USD'
    """
    s = _clean(raw)
    if not s:
        return None

    # Already a Yahoo crypto pair (…-USD / …-USDT / …-EUR etc.) → normalize
    # casing AND remap wrong bare bases to the real Yahoo base. An explicit
    # pair is an unambiguous crypto statement, so the equity-collision guard
    # does NOT apply here — otherwise this module would reject its own
    # canonical output ("VET-USD" from detect_crypto_in_query would fail
    # normalize_crypto_symbol). The guard only protects BARE ticker input.
    if "-" in s:
        base, _, quote = s.partition("-")
        base_u = base.upper()
        quote_u = (quote or "usd").upper()
        canon = _CRYPTO_NAME_TO_SYMBOL.get(base) or (
            base_u if base_u in _known_bases() else None
        )
        if canon:
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


# ---------------------------------------------------------------------------
# Live fallback: Yahoo symbol search for coins outside the curated map.
# Network call — callers inside async tools must run it via asyncio.to_thread.
# ---------------------------------------------------------------------------

_SEARCH_CACHE: Dict[str, tuple] = {}   # query -> (expires_at | None, symbol | None)
_SEARCH_MISS_TTL = 600.0               # re-try misses after 10 min


def search_crypto_symbol(query: str) -> Optional[str]:
    """
    Resolve an unknown coin name/symbol to a Yahoo `XXX-USD` pair via live
    Yahoo search, verifying the winner actually returns price data before
    trusting it. Hits are cached for the process lifetime; misses for 10 min.
    """
    q = _clean(query)
    if not q:
        return None

    cached = _SEARCH_CACHE.get(q)
    if cached:
        expires_at, symbol = cached
        if expires_at is None or time.time() < expires_at:
            return symbol

    symbol = None
    try:
        import yfinance as yf
        from .yf_resilience import fetch_history

        quotes = (yf.Search(q, max_results=8).quotes or [])
        candidates = [
            qt for qt in quotes
            if qt.get("quoteType") == "CRYPTOCURRENCY"
            and str(qt.get("symbol", "")).endswith("-USD")
        ]

        def rank(qt) -> int:
            short = str(qt.get("shortname", "")).lower()
            if short == f"{q} usd":
                return 0
            if short.startswith(q):
                return 1
            return 2

        for qt in sorted(candidates, key=rank):
            sym = qt["symbol"]
            try:
                df = fetch_history(sym, "5d", attempts=2)
                if df is not None and not df.empty:
                    symbol = sym
                    break
            except Exception:
                continue
    except Exception:
        symbol = None

    _SEARCH_CACHE[q] = (
        None if symbol else time.time() + _SEARCH_MISS_TTL,
        symbol,
    )
    return symbol


def detect_crypto_in_query(query: str) -> Optional[str]:
    """
    Scan a free-text query for a crypto asset. Returns the Yahoo `XXX-USD`
    symbol of the first coin found, or None.

    Strategy: check multi-word names first (so 'bitcoin cash' beats 'bitcoin'),
    then single tokens. Bare ambiguous tokens ('link', 'op', 'ton', 'gala') are
    only matched when a crypto-context word is also present, so we don't hijack
    ordinary English ('the link is broken', 'op-ed', 'gala dinner').
    """
    q = _clean(query)
    if not q:
        return None

    has_context = any(w in q for w in _CRYPTO_CONTEXT_WORDS)

    # Multi-word names that are also ordinary finance English need crypto
    # context ("show me the graph of AAPL" must not resolve to GRT).
    _AMBIGUOUS_MULTIWORD = {"the graph", "the sandbox"}

    # Multi-word names first, longest first.
    multiword = sorted(
        (k for k in _CRYPTO_NAME_TO_SYMBOL if " " in k),
        key=len, reverse=True,
    )
    for name in multiword:
        if name in q and (has_context or name not in _AMBIGUOUS_MULTIWORD):
            return f"{_CRYPTO_NAME_TO_SYMBOL[name]}-USD"

    # Ambiguous single tokens: English words, 1-letter symbols, equity tickers.
    # Matched only when the query is clearly about crypto.
    _AMBIGUOUS = {
        "link", "op", "ton", "near", "sui", "atom", "apt", "arb", "inj",
        "dot", "bnb", "ape", "trump", "blur", "grass", "render", "ray",
        "mantle", "quant", "flow", "gala", "theta", "kava", "mina", "celo",
        "flare", "walrus", "sandbox", "maker", "pendle", "eigen", "ena",
        "ondo", "sei", "not", "dai", "uni", "pol", "mnt", "wal", "aero", "algo",
    }
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
