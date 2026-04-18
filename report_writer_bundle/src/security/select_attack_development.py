"""
Select a small high-leverage poisoned-case subset for attack development.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
from typing import Dict, List

from .dataset import load_cases
from .runtime import REPO_ROOT

DEFAULT_TOTAL_CASES = 6
DEFAULT_MAX_TARGET_SHIFT = 8.0
MIN_UNIQUE_TICKERS = 2
TIER_QUOTAS = {
    "tier1": 1,
    "tier2": 2,
    "tier3": 2,
}


def candidate_priority(case) -> tuple[float, int, str]:
    target_shift = case.metadata.get("target_return_shift_pct")
    try:
        shift = float(target_shift)
    except (TypeError, ValueError):
        shift = 999.0
    ticker_penalty = 1 if case.ticker == "AMZN" else 0
    return (shift, ticker_penalty, case.case_id)


def selection_cost(case, *, used_tickers: set[str], used_scenarios: set[str]) -> tuple[float, int, int, str]:
    shift, ticker_penalty, case_id = candidate_priority(case)
    ticker_repeat_penalty = 1 if case.ticker in used_tickers else 0
    scenario_repeat_penalty = 1 if case.base_case_id in used_scenarios else 0
    return (
        shift,
        ticker_penalty + ticker_repeat_penalty,
        scenario_repeat_penalty,
        case_id,
    )


def select_attack_development_cases(
    cases,
    *,
    total_cases: int = DEFAULT_TOTAL_CASES,
    max_target_shift: float = DEFAULT_MAX_TARGET_SHIFT,
) -> List[Dict]:
    poisoned_cases = [
        case
        for case in cases
        if case.case_type == "poisoned"
        and case.attack_tier in TIER_QUOTAS
        and case.metadata.get("target_return_shift_pct") is not None
        and float(case.metadata.get("target_return_shift_pct")) <= max_target_shift
    ]

    selected = []
    used_ids = set()
    used_tickers: set[str] = set()
    used_scenarios: set[str] = set()

    def pick_one(pool) -> None:
        ranked = sorted(
            (case for case in pool if case.case_id not in used_ids),
            key=lambda case: selection_cost(
                case,
                used_tickers=used_tickers,
                used_scenarios=used_scenarios,
            ),
        )
        if not ranked:
            return
        chosen = ranked[0]
        selected.append(chosen)
        used_ids.add(chosen.case_id)
        used_tickers.add(chosen.ticker)
        used_scenarios.add(chosen.base_case_id)

    for tier, quota in TIER_QUOTAS.items():
        tier_pool = [case for case in poisoned_cases if case.attack_tier == tier]
        for _ in range(quota):
            pick_one(tier_pool)

    remaining_pool = [
        case for case in poisoned_cases if case.case_id not in used_ids
    ]
    while len(selected) < total_cases and remaining_pool:
        pick_one(remaining_pool)
        remaining_pool = [case for case in poisoned_cases if case.case_id not in used_ids]

    selected = enforce_ticker_diversity(
        selected,
        poisoned_cases,
        min_unique_tickers=MIN_UNIQUE_TICKERS,
    )

    payload = []
    for case in selected:
        payload.append(
            {
                "case_id": case.case_id,
                "base_case_id": case.base_case_id,
                "ticker": case.ticker,
                "attack_tier": case.attack_tier,
                "target_direction": case.target_direction,
                "clean_rating": case.metadata.get("clean_rating"),
                "clean_expected_return_pct_12m": case.metadata.get(
                    "clean_expected_return_pct_12m"
                ),
                "distance_to_bullish_band": case.metadata.get(
                    "distance_to_bullish_band"
                ),
                "distance_to_bearish_band": case.metadata.get(
                    "distance_to_bearish_band"
                ),
                "target_return_shift_pct": case.metadata.get("target_return_shift_pct"),
            }
        )
    return payload


def enforce_ticker_diversity(selected_cases, candidate_pool, *, min_unique_tickers: int) -> List:
    selected = list(selected_cases)
    selected_ids = {case.case_id for case in selected}

    while len({case.ticker for case in selected}) < min_unique_tickers:
        represented = {case.ticker for case in selected}
        alternatives = sorted(
            [
                case
                for case in candidate_pool
                if case.case_id not in selected_ids and case.ticker not in represented
            ],
            key=candidate_priority,
        )
        if not alternatives:
            break

        swapped = False
        for alternative in alternatives:
            same_tier_selected = sorted(
                [
                    case
                    for case in selected
                    if case.attack_tier == alternative.attack_tier
                    and _swap_preserves_tier_quotas(selected, case, alternative)
                ],
                key=candidate_priority,
                reverse=True,
            )
            if not same_tier_selected:
                continue

            victim = same_tier_selected[0]
            selected.remove(victim)
            selected.append(alternative)
            selected_ids.remove(victim.case_id)
            selected_ids.add(alternative.case_id)
            swapped = True
            break

        if not swapped:
            break

    return selected


def _swap_preserves_tier_quotas(selected_cases, victim, replacement) -> bool:
    tier_counts = Counter(case.attack_tier for case in selected_cases)
    tier_counts[victim.attack_tier] -= 1
    tier_counts[replacement.attack_tier] += 1
    for tier, quota in TIER_QUOTAS.items():
        if tier_counts[tier] < quota:
            return False
    return True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Select a compact poisoned-case subset for attack development"
    )
    parser.add_argument(
        "--cases",
        type=Path,
        default=REPO_ROOT / "datasets" / "security" / "cases.jsonl",
        help="Path to the security case manifest",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO_ROOT / "datasets" / "security" / "attack_development_subset.json",
        help="Where to write the selected subset JSON",
    )
    parser.add_argument(
        "--total-cases",
        type=int,
        default=DEFAULT_TOTAL_CASES,
        help="Target number of poisoned cases to include",
    )
    parser.add_argument(
        "--max-target-shift",
        type=float,
        default=DEFAULT_MAX_TARGET_SHIFT,
        help="Maximum target_return_shift_pct to consider for the subset",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    cases = load_cases(args.cases.resolve())
    selection = select_attack_development_cases(
        cases,
        total_cases=args.total_cases,
        max_target_shift=args.max_target_shift,
    )
    payload = {
        "selection_method": "smallest_target_return_shift_with_tier_coverage",
        "total_cases": len(selection),
        "requested_total_cases": args.total_cases,
        "max_target_shift": args.max_target_shift,
        "tier_quotas": TIER_QUOTAS,
        "selected_cases": selection,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote attack-development subset with {len(selection)} cases to {args.output}")


if __name__ == "__main__":
    main()
