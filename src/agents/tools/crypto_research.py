"""Bounded, read-only crypto network and protocol research extensions.

Market price data and blockchain activity are different evidence domains.  This
module keeps them separate, uses only explicitly mapped native/protocol assets,
and fails independently so an upstream outage never removes the core quote.
"""

from __future__ import annotations

import math
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

MEMPOOL_BASE = "https://mempool.space/api"
DEFILLAMA_BASE = "https://api.llama.fi"
REQUEST_TIMEOUT = 6
CACHE_TTL_SECONDS = 5 * 60.0
STALE_CACHE_SECONDS = 60 * 60.0
MAX_CACHE_ENTRIES = 64
MAX_UPSTREAM_BYTES = 5 * 1024 * 1024

# Only native assets whose token is meaningfully associated with the mapped
# chain.  Governance/application tokens must not inherit their host chain's
# ecosystem metrics.
CHAIN_BY_BASE = {
    "ETH": "Ethereum", "SOL": "Solana", "TRX": "Tron",
    "AVAX": "Avalanche", "BNB": "BSC", "ADA": "Cardano",
    "DOT": "Polkadot", "NEAR": "Near", "ICP": "ICP",
    "HBAR": "Hedera", "FIL": "Filecoin", "INJ": "Injective",
    "SUI20947": "Sui", "APT21794": "Aptos", "SEI": "Sei",
    "EGLD": "MultiversX", "ALGO": "Algorand", "XTZ": "Tezos",
    "CRO": "Cronos", "GNO": "Gnosis", "CELO": "Celo",
    "FLOW": "Flow", "BERA": "Berachain", "STX4847": "Stacks",
}

# Explicit application-token mappings.  DefiLlama's token-holder-revenue
# series is requested separately from gross fees; the two are never conflated.
PROTOCOL_BY_BASE = {
    "UNI7083": "uniswap", "AAVE": "aave", "LDO": "lido",
    "CRV": "curve-dex", "MKR": "makerdao", "RPL": "rocket-pool",
    "PENDLE": "pendle", "MORPHO34104": "morpho",
    "AERO29270": "aerodrome", "RAY": "raydium",
}

_cache: Dict[str, Tuple[float, dict]] = {}


def _number(value: Any, *, nonnegative: bool = True) -> Optional[float]:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(result) or (nonnegative and result < 0):
        return None
    return result


def _integer(value: Any) -> Optional[int]:
    number = _number(value)
    if number is None or not number.is_integer():
        return None
    return int(number)


def _captured_at() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _future_result(future: Any) -> Tuple[Any, bool]:
    try:
        return future.result(), False
    except Exception:
        return None, True


def _get_json(url: str, *, params: Optional[dict] = None) -> Any:
    import requests

    response = requests.get(
        url, params=params, timeout=REQUEST_TIMEOUT, allow_redirects=False,
        headers={"Accept": "application/json", "User-Agent": "VynnAI/1.0 research"},
        stream=True,
    )
    try:
        response.raise_for_status()
        length = (getattr(response, "headers", {}) or {}).get("Content-Length")
        if length is not None:
            try:
                if int(length) > MAX_UPSTREAM_BYTES:
                    raise ValueError("upstream response exceeds size limit")
            except (TypeError, ValueError) as error:
                if isinstance(error, ValueError) and str(error).startswith("upstream"):
                    raise
        iterator = getattr(response, "iter_content", None)
        if not callable(iterator):
            # Minimal test adapters and some injected clients expose only
            # ``json``. Production requests responses always take the bounded
            # streaming branch above.
            return response.json()
        body = bytearray()
        for chunk in iterator(chunk_size=64 * 1024):
            if not chunk:
                continue
            body.extend(chunk)
            if len(body) > MAX_UPSTREAM_BYTES:
                raise ValueError("upstream response exceeds size limit")
        import json
        return json.loads(bytes(body).decode("utf-8-sig"))
    finally:
        close = getattr(response, "close", None)
        if callable(close):
            close()


def _cache_get(key: str, maximum_age: float) -> Optional[dict]:
    cached = _cache.get(key)
    if not cached or time.monotonic() - cached[0] > maximum_age:
        return None
    fresh = maximum_age == CACHE_TTL_SECONDS
    return {**cached[1], "cache": "hit" if fresh else "stale", "stale": not fresh}


def _cache_put(key: str, value: dict) -> dict:
    if len(_cache) >= MAX_CACHE_ENTRIES and key not in _cache:
        _cache.pop(min(_cache, key=lambda item: _cache[item][0]), None)
    _cache[key] = (time.monotonic(), value)
    return {**value, "cache": "miss", "stale": False}


def _bitcoin_context() -> dict:
    with ThreadPoolExecutor(max_workers=3) as pool:
        mempool_future = pool.submit(_get_json, f"{MEMPOOL_BASE}/mempool")
        fees_future = pool.submit(_get_json, f"{MEMPOOL_BASE}/v1/fees/recommended")
        height_future = pool.submit(_get_json, f"{MEMPOOL_BASE}/blocks/tip/height")
        mempool, mempool_failed = _future_result(mempool_future)
        fees, fees_failed = _future_result(fees_future)
        height, height_failed = _future_result(height_future)
    mempool = mempool if isinstance(mempool, dict) else {}
    fees = fees if isinstance(fees, dict) else {}
    block_height = _integer(height)
    mempool_count = _integer(mempool.get("count"))
    fee_values = {
        "high_priority": _number(fees.get("fastestFee")),
        "medium_priority": _number(fees.get("halfHourFee")),
        "low_priority": _number(fees.get("hourFee")),
        "economy": _number(fees.get("economyFee")),
        "minimum": _number(fees.get("minimumFee")),
    }
    partial_failures = []
    if mempool_failed or mempool_count is None:
        partial_failures.append("bitcoin_mempool_source_unavailable")
    if fees_failed or not any(value is not None for value in fee_values.values()):
        partial_failures.append("bitcoin_fee_source_unavailable")
    if height_failed or block_height is None:
        partial_failures.append("bitcoin_height_source_unavailable")
    if len(partial_failures) == 3:
        raise ValueError("Bitcoin network sources unavailable")
    result = {
        "network": "Bitcoin",
        "source": "mempool.space",
        "source_url": "https://mempool.space/docs/api/rest",
        "captured_at": _captured_at(),
        "block_height": block_height,
        "mempool_unconfirmed_transactions": mempool_count,
        "mempool_virtual_size_bytes": _integer(mempool.get("vsize")),
        "mempool_total_fees_sats": _integer(mempool.get("total_fee")),
        "recommended_fees_sat_per_vbyte": fee_values,
        "partial_failures": partial_failures,
        "scope": "bitcoin_network_activity_and_transaction_fee_conditions",
    }
    return result


def _dated_chain_tvl(raw: Any) -> Tuple[Optional[float], Optional[str], Optional[float]]:
    rows = []
    for row in raw if isinstance(raw, list) else []:
        if not isinstance(row, dict):
            continue
        stamp = _integer(row.get("date"))
        tvl = _number(row.get("tvl"))
        if stamp is not None and tvl is not None:
            rows.append((stamp, tvl))
    rows.sort()
    if not rows:
        return None, None, None
    stamp, latest = rows[-1]
    comparison = next((value for when, value in reversed(rows[:-1])
                       if when <= stamp - 7 * 86400), None)
    change = latest / comparison - 1.0 if comparison and comparison > 0 else None
    as_of = datetime.fromtimestamp(stamp, timezone.utc).date().isoformat()
    return latest, as_of, change


def _chain_context(chain: str) -> dict:
    with ThreadPoolExecutor(max_workers=2) as pool:
        tvl_future = pool.submit(
            _get_json, f"{DEFILLAMA_BASE}/v2/historicalChainTvl/{chain}")
        fees_future = pool.submit(
            _get_json, f"{DEFILLAMA_BASE}/overview/fees/{chain}", params={
                "excludeTotalDataChart": "true",
                "excludeTotalDataChartBreakdown": "true",
            })
        raw_tvl, tvl_failed = _future_result(tvl_future)
        raw_fees, fees_failed = _future_result(fees_future)
    tvl, tvl_as_of, change_7d = _dated_chain_tvl(raw_tvl)
    fees = raw_fees if isinstance(raw_fees, dict) else {}
    fee_values = {
        "last_24h": _number(fees.get("total24h")),
        "prior_24h": _number(fees.get("total48hto24h")),
        "last_7d": _number(fees.get("total7d")),
        "last_30d": _number(fees.get("total30d")),
    }
    partial_failures = []
    if tvl_failed or tvl is None:
        partial_failures.append("chain_tvl_source_unavailable")
    if fees_failed or not any(value is not None for value in fee_values.values()):
        partial_failures.append("chain_fee_source_unavailable")
    if len(partial_failures) == 2:
        raise ValueError("chain activity missing")
    return {
        "network": chain,
        "source": "defillama",
        "source_url": "https://defillama.com/docs/api",
        "captured_at": _captured_at(),
        "defi_tvl_usd": tvl,
        "defi_tvl_as_of": tvl_as_of,
        "defi_tvl_change_7d": change_7d,
        "tracked_application_fees_usd": fee_values,
        "partial_failures": partial_failures,
        "scope": "defi_ecosystem_tvl_and_tracked_application_fees",
        "warning": (
            "Chain ecosystem activity is not issuer revenue, token-holder cash flow, "
            "or an intrinsic valuation. DefiLlama coverage may be incomplete."
        ),
    }


def _protocol_context(slug: str) -> dict:
    common = {
        "excludeTotalDataChart": "true",
        "excludeTotalDataChartBreakdown": "true",
    }
    with ThreadPoolExecutor(max_workers=2) as pool:
        fees_future = pool.submit(
            _get_json, f"{DEFILLAMA_BASE}/summary/fees/{slug}", params=common)
        holders_future = pool.submit(
            _get_json, f"{DEFILLAMA_BASE}/summary/fees/{slug}",
            params={**common, "dataType": "dailyHoldersRevenue"})
        raw_fees, fees_failed = _future_result(fees_future)
        raw_holders, holders_failed = _future_result(holders_future)
    fees = raw_fees if isinstance(raw_fees, dict) else {}
    holders = raw_holders if isinstance(raw_holders, dict) else {}
    def periods(source: dict) -> dict:
        return {
            "last_24h": _number(source.get("total24h")),
            "last_7d": _number(source.get("total7d")),
            "last_30d": _number(source.get("total30d")),
        }

    gross_fees, holder_revenue = periods(fees), periods(holders)
    partial_failures = []
    if fees_failed or not any(value is not None for value in gross_fees.values()):
        partial_failures.append("protocol_fee_source_unavailable")
    if holders_failed or not any(value is not None for value in holder_revenue.values()):
        partial_failures.append("protocol_holder_revenue_source_unavailable")
    if len(partial_failures) == 2:
        raise ValueError("protocol economics missing")
    return {
        "protocol": str(fees.get("displayName") or fees.get("name") or slug)[:120],
        "protocol_slug": slug,
        "source": "defillama",
        "source_url": "https://defillama.com/data-definitions",
        "captured_at": _captured_at(),
        "gross_fees_usd": gross_fees,
        "token_holder_revenue_usd": holder_revenue,
        "partial_failures": partial_failures,
        "scope": "mapped_protocol_fees_and_defillama_token_holder_revenue",
        "warning": (
            "Protocol activity is not automatically attributable to the token. "
            "Only DefiLlama's separate token-holder-revenue series represents "
            "tracked value returned to holders, and coverage may be incomplete."
        ),
    }


def get_crypto_research(symbol: str) -> dict:
    """Return mapped research context; unsupported or failed sources stay explicit."""
    base = str(symbol or "").upper().split("-", 1)[0]
    cached = _cache_get(base, CACHE_TTL_SECONDS)
    if cached is not None:
        return cached

    network = protocol = None
    failures = []
    if base == "BTC":
        try:
            network = _bitcoin_context()
            failures.extend(network.get("partial_failures") or [])
        except Exception:
            failures.append("bitcoin_network_source_unavailable")
    elif base in CHAIN_BY_BASE:
        try:
            network = _chain_context(CHAIN_BY_BASE[base])
            failures.extend(network.get("partial_failures") or [])
        except Exception:
            failures.append("chain_ecosystem_source_unavailable")
    if base in PROTOCOL_BY_BASE:
        try:
            protocol = _protocol_context(PROTOCOL_BY_BASE[base])
            failures.extend(protocol.get("partial_failures") or [])
        except Exception:
            failures.append("protocol_economics_source_unavailable")

    supported = base == "BTC" or base in CHAIN_BY_BASE or base in PROTOCOL_BY_BASE
    network_activity = bool(
        network and network.get("source") == "mempool.space" and
        (network.get("block_height") is not None or
         network.get("mempool_unconfirmed_transactions") is not None)
    )
    holder_revenue = (
        (protocol or {}).get("token_holder_revenue_usd") or {}
    )
    payload = {
        "network_context": network,
        "protocol_context": protocol,
        "mapped_asset": supported,
        "failures": failures,
        "capabilities": {
            # DefiLlama chain TVL/application fees are ecosystem context, not
            # generic on-chain usage metrics such as transactions, addresses,
            # gas, staking, or supply flows.
            "network_activity": network_activity,
            "defi_ecosystem_activity": bool(network and network.get("source") == "defillama"),
            "protocol_economics": protocol is not None,
            "token_holder_revenue": any(
                _number(value) is not None for value in holder_revenue.values()
            ),
        },
    }
    has_context = network is not None or protocol is not None
    payload["status"] = (
        "unsupported" if not supported else
        "partial" if has_context and failures else
        "complete" if has_context else
        "unavailable"
    )
    if failures:
        stale = _cache_get(base, STALE_CACHE_SECONDS)
        if stale is not None:
            return stale
    return _cache_put(base, payload)
