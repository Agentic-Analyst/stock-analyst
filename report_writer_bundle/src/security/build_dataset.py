"""
Build the local security benchmark dataset from frozen real-news seeds.

The first MVP uses searched markdown artifacts already checked into the repo.
This keeps the benchmark reproducible while still grounding it in real retrieved
news content.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List, Tuple

import yaml

from .attacks import (
    ATTACK_TEMPLATE_VERSION,
    attack_family_for_tier,
    build_poisoned_article,
    default_objective_for_direction,
    expected_effect_for_tier,
)
from .dataset import write_article, write_cases
from .governance import build_dataset_metadata, write_dataset_metadata
from .models import ArticleRecord, SecurityCase
from .runtime import REPO_ROOT, load_project_env

load_project_env()


DEFAULT_TICKERS = ["AAPL", "AMZN", "META", "NVDA"]
ATTACK_TIERS = ["tier1", "tier2", "tier3"]

COMPANY_ALIASES = {
    "AAPL": ["apple", "iphone", "ipad", "mac", "tim cook"],
    "AMZN": ["amazon", "amazon.com", "aws", "prime", "andy jassy"],
    "META": ["meta platforms", "facebook", "instagram", "whatsapp", "zuckerberg", "threads"],
    "NVDA": ["nvidia", "geforce", "cuda", "jensen huang"],
}

WEAK_ALIAS_TOKENS = {
    "META": {"meta"},
}

STOCK_CONTEXT_TERMS = {
    "stock",
    "shares",
    "nasdaq",
    "nyse",
    "earnings",
    "rating",
    "buy",
    "sell",
    "outlook",
    "forecast",
    "price target",
    "revenue",
    "profit",
    "guidance",
    "investment",
    "analyst",
}

LOW_QUALITY_TITLE_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in [
        r"\bamazon[-\s]?bestseller\b",
        r"\bmarket\b.*\b(2025|2026|2030|2032|2033|forecast|analysis|overview|size|share|growth)\b",
        r"\bglobal\b.*\bmarket\b",
        r"\bsec\s+10-q\b",
        r"\bearnings call highlights\b",
        r"\bwhat is\b",
        r"\bukhotviews\b",
        r"\bpress release\b",
    ]
]

CALIBRATION_FIELDS = (
    "clean_rating",
    "clean_expected_return_pct_12m",
    "distance_to_bullish_band",
    "distance_to_bearish_band",
)

SEED_POOL_MULTIPLIER = 4


def build_dataset(
    *,
    dataset_root: Path,
    tickers: List[str],
    scenarios_per_ticker: int,
    bundle_size: int,
    pilot_scenarios_per_ticker: int,
    seed_source: str = "local",
    mongo_limit: int = 80,
    direction_overrides: Dict[str, str] | None = None,
    direction_records: Dict[str, Dict[str, Any]] | None = None,
    direction_map_path: Path | None = None,
    notes: str | None = None,
    force: bool = False,
) -> List[SecurityCase]:
    manifest_path = dataset_root / "cases.jsonl"
    articles_root = dataset_root / "articles"

    if force and articles_root.exists():
        shutil.rmtree(articles_root)
    if force and manifest_path.exists():
        manifest_path.unlink()

    cases: List[SecurityCase] = []

    for ticker in tickers:
        seed_articles = discover_seed_articles(
            ticker,
            seed_source=seed_source,
            mongo_limit=mongo_limit,
        )
        if len(seed_articles) < bundle_size:
            raise ValueError(
                f"Ticker {ticker} only has {len(seed_articles)} usable seed articles; "
                f"need at least {bundle_size}"
            )
        seed_articles = trim_seed_pool(
            seed_articles,
            scenarios_per_ticker=scenarios_per_ticker,
            bundle_size=bundle_size,
        )

        financial_ref, model_ref = discover_snapshot_refs(ticker)
        bundles = build_scenario_bundles(
            seed_articles,
            scenarios_per_ticker=scenarios_per_ticker,
            bundle_size=bundle_size,
        )

        company_name = seed_articles[0].metadata["company_name"]
        for index, bundle in enumerate(bundles, start=1):
            scenario_id = f"{ticker.lower()}_s{index:02d}"
            split = "pilot" if index <= pilot_scenarios_per_ticker else "main"
            scenario_direction_record = (direction_records or {}).get(scenario_id, {})
            target_direction = resolve_target_direction(
                scenario_id=scenario_id,
                default_direction="bullish" if index % 2 else "bearish",
                direction_overrides=direction_overrides or {},
            )
            expected_effect = "Preserve the clean baseline."
            calibration_metadata = build_calibration_metadata(
                scenario_direction_record,
                target_direction=target_direction,
            )

            clean_case_id = f"{scenario_id}_clean"
            clean_refs = materialize_case_articles(
                articles_root=articles_root,
                case_id=clean_case_id,
                articles=bundle,
            )
            cases.append(
                SecurityCase(
                    case_id=clean_case_id,
                    base_case_id=scenario_id,
                    ticker=ticker,
                    scenario_id=scenario_id,
                    variant="clean",
                    split=split,
                    case_type="clean",
                    attack_tier="none",
                    attack_family="none",
                    objective="baseline_reference",
                    target_direction="neutral",
                    article_refs=clean_refs,
                    financial_snapshot_ref=financial_ref,
                    model_snapshot_ref=model_ref,
                    expected_end_to_end_effect=expected_effect,
                    metadata={
                        "company_name": company_name,
                        "seed_bundle_article_ids": [article.article_id for article in bundle],
                        **calibration_metadata,
                    },
                )
            )

            anchor_article = bundle[0]
            context_articles = bundle[1:]
            for attack_tier in ATTACK_TIERS:
                poisoned_anchor, labels = build_poisoned_article(
                    seed_article=anchor_article,
                    ticker=ticker,
                    company_name=company_name,
                    attack_tier=attack_tier,
                    target_direction=target_direction,
                    attack_context=calibration_metadata,
                )
                case_id = f"{scenario_id}_{attack_tier}"
                refs = materialize_case_articles(
                    articles_root=articles_root,
                    case_id=case_id,
                    articles=[poisoned_anchor] + context_articles,
                )
                cases.append(
                    SecurityCase(
                        case_id=case_id,
                        base_case_id=scenario_id,
                        ticker=ticker,
                        scenario_id=scenario_id,
                        variant=attack_tier,
                        split=split,
                        case_type="poisoned",
                        attack_tier=attack_tier,
                        attack_family=attack_family_for_tier(attack_tier),
                        objective=default_objective_for_direction(target_direction),
                        target_direction=target_direction,
                        article_refs=refs,
                        financial_snapshot_ref=financial_ref,
                        model_snapshot_ref=model_ref,
                        expected_end_to_end_effect=expected_effect_for_tier(
                            attack_tier,
                            target_direction,
                        ),
                        metadata={
                            "company_name": company_name,
                            "anchor_seed_article_id": anchor_article.article_id,
                            "poison_span_labels": labels,
                            **calibration_metadata,
                        },
                    )
                )

    write_cases(manifest_path, cases)
    dataset_metadata = build_dataset_metadata(
        dataset_root=dataset_root,
        seed_source=seed_source,
        tickers=tickers,
        scenarios_per_ticker=scenarios_per_ticker,
        bundle_size=bundle_size,
        pilot_scenarios_per_ticker=pilot_scenarios_per_ticker,
        mongo_limit=mongo_limit,
        direction_map_path=direction_map_path,
        notes=notes,
    )
    write_dataset_metadata(dataset_root, dataset_metadata)
    return cases


def discover_seed_articles(
    ticker: str,
    *,
    seed_source: str = "local",
    mongo_limit: int = 80,
) -> List[ArticleRecord]:
    """Collect and rank real seed articles for one ticker."""
    if seed_source == "mongo":
        articles = discover_seed_articles_from_mongo(ticker, limit=mongo_limit)
    elif seed_source == "local":
        articles = discover_seed_articles_from_local(ticker)
    else:
        raise ValueError(f"Unsupported seed_source '{seed_source}'")

    if not articles:
        raise ValueError(f"No usable seed articles found for {ticker} from {seed_source}")

    filtered_articles = [article for article in articles if is_usable_seed_article(article)]
    if filtered_articles:
        articles = filtered_articles

    # Prefer articles with direct company/title alignment and penalize low-quality
    # market-report or clearly off-topic headline patterns.
    articles.sort(
        key=lambda article: (
            int(article.metadata.get("strong_company_match", False)),
            int(article.metadata.get("title_company_match", False)),
            int(article.metadata.get("title_stock_context", False)),
            -int(article.metadata.get("low_quality_candidate", False)),
            article.metadata["relevance_score"],
            article.publish_date,
            len(article.text),
        ),
        reverse=True,
    )
    return articles


def resolve_target_direction(
    *,
    scenario_id: str,
    default_direction: str,
    direction_overrides: Dict[str, str],
) -> str:
    override = direction_overrides.get(scenario_id, default_direction)
    if override not in {"bullish", "bearish", "neutral"}:
        raise ValueError(
            f"Direction override for {scenario_id} must be bullish/bearish/neutral, got {override!r}"
        )
    return override


def load_direction_overrides(path: Path | None) -> Dict[str, str]:
    return direction_overrides_from_records(load_direction_records(path))


def load_direction_records(path: Path | None) -> Dict[str, Dict[str, Any]]:
    if path is None:
        return {}

    payload = json.loads(path.read_text(encoding="utf-8"))
    records: Dict[str, Dict[str, Any]] = {}
    for scenario_id, value in payload.items():
        record = dict(value) if isinstance(value, dict) else {"target_direction": value}
        direction = record.get("target_direction")
        if direction not in {"bullish", "bearish", "neutral"}:
            raise ValueError(
                f"Direction override for {scenario_id} must be bullish/bearish/neutral, got {direction!r}"
            )
        records[scenario_id] = record
    return records


def direction_overrides_from_records(
    records: Dict[str, Dict[str, Any]],
) -> Dict[str, str]:
    overrides: Dict[str, str] = {}
    for scenario_id, record in records.items():
        direction = record.get("target_direction")
        if direction is None:
            continue
        overrides[scenario_id] = str(direction)
    return overrides


def build_calibration_metadata(
    record: Dict[str, Any],
    *,
    target_direction: str,
) -> Dict[str, Any]:
    metadata = {
        field: record[field]
        for field in CALIBRATION_FIELDS
        if field in record
    }
    target_shift = target_shift_for_direction(target_direction, record)
    if target_shift is not None:
        metadata["target_return_shift_pct"] = target_shift
    return metadata


def target_shift_for_direction(
    target_direction: str,
    record: Dict[str, Any],
) -> float | None:
    key = (
        "distance_to_bullish_band"
        if target_direction == "bullish"
        else "distance_to_bearish_band"
    )
    raw_value = record.get(key)
    if raw_value is None:
        return None
    try:
        distance = float(raw_value)
    except (TypeError, ValueError):
        return None
    return round(distance + 2.0, 2)


def discover_seed_articles_from_local(ticker: str) -> List[ArticleRecord]:
    """Collect and rank real seed articles from checked-in markdown artifacts."""
    article_paths = sorted(REPO_ROOT.glob(f"data/**/*/{ticker}/**/searched/*.md"))
    deduped: Dict[str, ArticleRecord] = {}
    for path in article_paths:
        article = parse_seed_markdown(path, ticker)
        if not article:
            continue
        dedupe_key = article.source_url or article.title
        current = deduped.get(dedupe_key)
        if current is None or len(article.text) > len(current.text):
            deduped[dedupe_key] = article

    articles = list(deduped.values())
    return articles


def discover_seed_articles_from_mongo(ticker: str, *, limit: int = 80) -> List[ArticleRecord]:
    """Collect and rank seed articles directly from the live MongoDB cache."""
    from vynn_core import find_recent

    recent_articles = find_recent(collection_name=ticker, limit=limit)
    deduped: Dict[str, ArticleRecord] = {}
    for index, document in enumerate(recent_articles, start=1):
        article = parse_seed_document(document=document, ticker=ticker, ordinal=index)
        if not article:
            continue
        dedupe_key = article.source_url or article.title
        current = deduped.get(dedupe_key)
        if current is None or len(article.text) > len(current.text):
            deduped[dedupe_key] = article

    return list(deduped.values())


def parse_seed_markdown(path: Path, ticker: str) -> ArticleRecord | None:
    content = path.read_text(encoding="utf-8")
    if not content.startswith("---"):
        return None
    end = content.find("\n---", 3)
    if end == -1:
        return None

    meta = yaml.safe_load(content[3:end]) or {}
    text = content[end + 4 :].strip()
    title = str(meta.get("title") or path.stem.replace("_", " ")).strip()
    source_url = str(meta.get("source_url") or "")
    publish_date = str(meta.get("publish_date") or "")
    company_name = str(meta.get("company") or meta.get("company_name") or ticker)
    article_id = slugify(f"{path.stem}-{ticker}")[:80]
    title_company_match = has_title_company_match(
        title=title,
        ticker=ticker,
        company_name=company_name,
    )
    strong_company_match = has_strong_company_match(
        title=title,
        text=text,
        ticker=ticker,
        company_name=company_name,
    )
    title_stock_context = has_stock_context(title)
    low_quality_candidate = is_low_quality_candidate(title)
    relevance_score = compute_relevance_score(
        title=title,
        text=text,
        ticker=ticker,
        company_name=company_name,
    )

    article = ArticleRecord(
        article_id=article_id,
        title=title,
        source_url=source_url,
        publish_date=publish_date,
        source_type="seed",
        text=text,
        metadata={
            "source_path": str(path.relative_to(REPO_ROOT)),
            "company_name": company_name,
            "relevance_score": relevance_score,
            "strong_company_match": strong_company_match,
            "title_company_match": title_company_match,
            "title_stock_context": title_stock_context,
            "low_quality_candidate": low_quality_candidate,
        },
    )
    return article


def parse_seed_document(
    *,
    document: Dict[str, Any],
    ticker: str,
    ordinal: int,
) -> ArticleRecord | None:
    title = str(document.get("title") or "").strip()
    text = str(document.get("content") or document.get("text") or "").strip()
    if not title or not text:
        return None

    source_url = str(document.get("url") or document.get("source_url") or "").strip()
    publish_date = str(
        document.get("publish_date")
        or document.get("scraped_at")
        or document.get("created_at")
        or ""
    )
    company_name = str(document.get("company") or document.get("company_name") or ticker)
    article_id = slugify(f"mongo-{ticker}-{publish_date}-{ordinal}-{title}")[:80]
    title_company_match = has_title_company_match(
        title=title,
        ticker=ticker,
        company_name=company_name,
    )
    strong_company_match = has_strong_company_match(
        title=title,
        text=text,
        ticker=ticker,
        company_name=company_name,
    )
    title_stock_context = has_stock_context(title)
    low_quality_candidate = is_low_quality_candidate(title)
    relevance_score = compute_relevance_score(
        title=title,
        text=text,
        ticker=ticker,
        company_name=company_name,
    )

    return ArticleRecord(
        article_id=article_id,
        title=title,
        source_url=source_url,
        publish_date=publish_date,
        source_type="seed_mongo",
        text=text,
        metadata={
            "company_name": company_name,
            "relevance_score": relevance_score,
            "strong_company_match": strong_company_match,
            "title_company_match": title_company_match,
            "title_stock_context": title_stock_context,
            "low_quality_candidate": low_quality_candidate,
            "mongo_id": str(document.get("_id", "")),
            "mongo_collection": ticker,
        },
    )


def build_scenario_bundles(
    articles: List[ArticleRecord],
    *,
    scenarios_per_ticker: int,
    bundle_size: int,
) -> List[List[ArticleRecord]]:
    """Build anchor + context bundles with evenly spaced anchors."""
    bundles: List[List[ArticleRecord]] = []
    anchor_indices: List[int] = []
    total = len(articles)

    for i in range(scenarios_per_ticker):
        if total >= scenarios_per_ticker:
            anchor_index = int(i * total / scenarios_per_ticker)
        else:
            anchor_index = i % total
        anchor_indices.append(anchor_index)

    for anchor_index in anchor_indices:
        bundle = [articles[anchor_index]]
        cursor = 1
        while len(bundle) < bundle_size:
            candidate = articles[(anchor_index + cursor) % total]
            if candidate.article_id not in {article.article_id for article in bundle}:
                bundle.append(candidate)
            cursor += 1
        bundles.append(bundle)

    return bundles


def trim_seed_pool(
    articles: List[ArticleRecord],
    *,
    scenarios_per_ticker: int,
    bundle_size: int,
) -> List[ArticleRecord]:
    max_pool_size = max(bundle_size * SEED_POOL_MULTIPLIER, scenarios_per_ticker * 4)
    return articles[:max_pool_size]


def materialize_case_articles(
    *,
    articles_root: Path,
    case_id: str,
    articles: List[ArticleRecord],
) -> List[str]:
    """Write one case bundle to the dataset articles directory."""
    refs: List[str] = []
    for index, article in enumerate(articles, start=1):
        article_copy = ArticleRecord.from_dict(
            {
                "article_id": f"{index:02d}_{article.article_id}",
                "title": article.title,
                "source_url": article.source_url,
                "publish_date": article.publish_date,
                "source_type": article.source_type,
                "text": article.text,
                "seed_article_id": article.seed_article_id,
                "rewrite_notes": article.rewrite_notes,
                "poison_span_labels": article.poison_span_labels,
            }
        )
        relative_ref = Path("articles") / case_id / f"{article_copy.article_id}.md"
        write_article(articles_root / case_id / f"{article_copy.article_id}.md", article_copy)
        refs.append(relative_ref.as_posix())
    return refs


def discover_snapshot_refs(ticker: str) -> Tuple[str, str]:
    """Find the newest pair of financial/model snapshots for one ticker."""
    candidates = sorted(
        REPO_ROOT.glob(f"data/**/*/{ticker}_financial_model_computed_values.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for model_path in candidates:
        financial_path = model_path.parent.parent / "financials" / "financials_annual_modeling_latest.json"
        if financial_path.exists():
            return (
                financial_path.relative_to(REPO_ROOT).as_posix(),
                model_path.relative_to(REPO_ROOT).as_posix(),
            )
    raise ValueError(f"Could not find paired financial/model snapshots for {ticker}")


def compute_relevance_score(title: str, text: str, ticker: str, company_name: str) -> int:
    title_lower = title.lower()
    haystack = f"{title}\n{text[:1200]}".lower()
    aliases = company_aliases_for_ticker(ticker, company_name)
    company_tokens = [token for token in re.split(r"[^a-zA-Z0-9]+", company_name.lower()) if token]
    weak_aliases = weak_aliases_for_ticker(ticker)
    score = 0

    if ticker.lower() not in weak_aliases:
        score += count_alias_occurrences(haystack, ticker.lower()) * 4

    for alias in aliases:
        if len(alias) >= 3:
            score += count_alias_occurrences(haystack, alias)
            score += count_alias_occurrences(title_lower, alias) * 3

    for token in company_tokens:
        if len(token) >= 3 and token not in weak_aliases:
            score += count_alias_occurrences(haystack, token)

    if has_stock_context(title):
        score += 3

    for pattern in LOW_QUALITY_TITLE_PATTERNS:
        if pattern.search(title_lower):
            score -= 5

    return score


def company_aliases_for_ticker(ticker: str, company_name: str) -> List[str]:
    weak_aliases = weak_aliases_for_ticker(ticker)
    aliases = list(COMPANY_ALIASES.get(ticker.upper(), []))
    aliases.extend(
        token
        for token in re.split(r"[^a-zA-Z0-9]+", company_name.lower())
        if len(token) >= 3 and token not in weak_aliases
    )
    if ticker.lower() not in weak_aliases:
        aliases.append(ticker.lower())

    deduped: List[str] = []
    for alias in aliases:
        if alias and alias not in deduped:
            deduped.append(alias)
    return deduped


def has_title_company_match(title: str, ticker: str, company_name: str) -> bool:
    title_lower = title.lower()
    return any(
        count_alias_occurrences(title_lower, alias) > 0
        for alias in company_aliases_for_ticker(ticker, company_name)
    )


def has_strong_company_match(title: str, text: str, ticker: str, company_name: str) -> bool:
    haystack = f"{title}\n{text[:1200]}".lower()
    strong_aliases = COMPANY_ALIASES.get(ticker.upper(), [])
    return any(count_alias_occurrences(haystack, alias) > 0 for alias in strong_aliases)


def has_stock_context(title: str) -> bool:
    title_lower = title.lower()
    return any(term in title_lower for term in STOCK_CONTEXT_TERMS)


def is_low_quality_candidate(title: str) -> bool:
    return any(pattern.search(title) for pattern in LOW_QUALITY_TITLE_PATTERNS)


def is_usable_seed_article(article: ArticleRecord) -> bool:
    metadata = article.metadata
    if metadata.get("strong_company_match", False):
        return True
    if metadata.get("title_company_match", False) and metadata.get("title_stock_context", False):
        return True
    return int(metadata.get("relevance_score", 0)) >= 6


def weak_aliases_for_ticker(ticker: str) -> set[str]:
    return set(WEAK_ALIAS_TOKENS.get(ticker.upper(), set()))


def count_alias_occurrences(haystack: str, alias: str) -> int:
    pattern = re.compile(rf"(?<![a-z0-9]){re.escape(alias.lower())}(?![a-z0-9])")
    return len(pattern.findall(haystack.lower()))


def slugify(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the local VYNN AI security dataset")
    parser.add_argument(
        "--dataset-root",
        type=Path,
        default=REPO_ROOT / "datasets" / "security",
        help="Dataset root directory",
    )
    parser.add_argument(
        "--tickers",
        nargs="+",
        default=DEFAULT_TICKERS,
        help="Tickers to include in the MVP benchmark",
    )
    parser.add_argument(
        "--scenarios-per-ticker",
        type=int,
        default=5,
        help="Number of clean scenarios to build per ticker",
    )
    parser.add_argument(
        "--bundle-size",
        type=int,
        default=4,
        help="Articles per case bundle (anchor + context)",
    )
    parser.add_argument(
        "--pilot-scenarios-per-ticker",
        type=int,
        default=1,
        help="How many scenarios per ticker should be marked as pilot",
    )
    parser.add_argument(
        "--seed-source",
        choices=["local", "mongo"],
        default="local",
        help="Where to source the clean seed articles from before freezing them into the dataset",
    )
    parser.add_argument(
        "--mongo-limit",
        type=int,
        default=80,
        help="How many recent MongoDB articles to inspect per ticker when --seed-source mongo is used",
    )
    parser.add_argument(
        "--direction-map",
        type=Path,
        default=None,
        help="Optional JSON file mapping scenario IDs to target directions",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite any existing dataset artifacts under the dataset root",
    )
    parser.add_argument(
        "--notes",
        default="",
        help="Optional build notes to store in benchmark_metadata.json",
    )
    args = parser.parse_args()
    direction_records = load_direction_records(args.direction_map)
    direction_overrides = direction_overrides_from_records(direction_records)

    cases = build_dataset(
        dataset_root=args.dataset_root,
        tickers=[ticker.upper() for ticker in args.tickers],
        scenarios_per_ticker=args.scenarios_per_ticker,
        bundle_size=args.bundle_size,
        pilot_scenarios_per_ticker=args.pilot_scenarios_per_ticker,
        seed_source=args.seed_source,
        mongo_limit=args.mongo_limit,
        direction_overrides=direction_overrides,
        direction_records=direction_records,
        direction_map_path=args.direction_map,
        notes=args.notes,
        force=args.force,
    )

    clean_count = sum(1 for case in cases if case.case_type == "clean")
    poisoned_count = sum(1 for case in cases if case.case_type == "poisoned")
    print(
        f"Built dataset at {args.dataset_root} with {clean_count} clean and "
        f"{poisoned_count} poisoned cases from {args.seed_source} seeds."
    )


if __name__ == "__main__":
    main()
