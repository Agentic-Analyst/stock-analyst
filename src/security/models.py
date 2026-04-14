"""
Core data models for the security benchmark.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


ALLOWED_CASE_TYPES = {"clean", "poisoned", "stale_sidecar"}
ALLOWED_ATTACK_TIERS = {"none", "tier1", "tier2", "tier3"}
ALLOWED_SPLITS = {"pilot", "main", "validation"}
ALLOWED_TARGET_DIRECTIONS = {"bullish", "bearish", "neutral"}


def _iso_now() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


@dataclass
class SecurityConfig:
    """Benchmark runtime configuration."""

    name: str = "baseline"
    target_model: str = "gpt-4o-mini"
    input_separation: bool = False
    sanitizer: bool = False
    verifier: bool = False
    verifier_model: str = "claude-sonnet-4-20250514"
    verifier_threshold: float = 0.7
    block_on_flag: bool = False
    batch_size: int = 10
    min_confidence: Optional[float] = None
    generate_report: bool = True
    max_workers: int = 2
    resume: bool = False
    cache_llm: bool = True
    cache_dir: Optional[str] = None
    corpus_version: Optional[str] = None
    direction_map_version: Optional[str] = None
    attack_template_version: Optional[str] = None
    metric_version: Optional[str] = None
    code_commit: Optional[str] = None
    run_validity: str = "benchmark_candidate"
    notes: str = ""

    @classmethod
    def from_name(cls, name: str) -> "SecurityConfig":
        """Build a preset config by name."""
        presets = {
            "baseline": cls(name="baseline"),
            "verifier-only": cls(
                name="verifier-only",
                verifier=True,
                block_on_flag=True,
            ),
            "struq-lite": cls(
                name="struq-lite",
                input_separation=True,
                sanitizer=True,
            ),
            "guarded": cls(
                name="guarded",
                input_separation=True,
                sanitizer=True,
                verifier=True,
                block_on_flag=True,
            ),
        }
        if name not in presets:
            raise ValueError(
                f"Unknown security config '{name}'. Available: {sorted(presets)}"
            )
        return presets[name]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ArticleRecord:
    """Frozen article used by the security benchmark."""

    article_id: str
    title: str
    source_url: str
    publish_date: str
    source_type: str
    text: str
    seed_article_id: Optional[str] = None
    rewrite_notes: Optional[str] = None
    poison_span_labels: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ArticleRecord":
        return cls(
            article_id=data["article_id"],
            title=data["title"],
            source_url=data["source_url"],
            publish_date=str(data["publish_date"]),
            source_type=data.get("source_type", "seed"),
            text=data["text"],
            seed_article_id=data.get("seed_article_id"),
            rewrite_notes=data.get("rewrite_notes"),
            poison_span_labels=list(data.get("poison_span_labels", [])),
            metadata=dict(data.get("metadata", {})),
        )

    def to_frontmatter_dict(self) -> Dict[str, Any]:
        payload = {
            "article_id": self.article_id,
            "title": self.title,
            "source_url": self.source_url,
            "publish_date": self.publish_date,
            "source_type": self.source_type,
        }
        if self.seed_article_id:
            payload["seed_article_id"] = self.seed_article_id
        if self.rewrite_notes:
            payload["rewrite_notes"] = self.rewrite_notes
        if self.poison_span_labels:
            payload["poison_span_labels"] = self.poison_span_labels
        return payload

    def to_screener_dict(self, file_name: Optional[str] = None) -> Dict[str, Any]:
        return {
            "file_name": file_name or self.article_id,
            "title": self.title,
            "source_url": self.source_url,
            "publish_date": self.publish_date,
            "text": self.text,
            "word_count": len(self.text.split()),
            "security_source_type": self.source_type,
        }


@dataclass
class SecurityCase:
    """One clean or poisoned benchmark case."""

    case_id: str
    base_case_id: str
    ticker: str
    scenario_id: str
    variant: str
    split: str
    case_type: str
    attack_tier: str
    attack_family: str
    objective: str
    target_direction: str
    article_refs: List[str]
    financial_snapshot_ref: str
    model_snapshot_ref: str
    expected_end_to_end_effect: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if self.split not in ALLOWED_SPLITS:
            raise ValueError(f"Invalid split for {self.case_id}: {self.split}")
        if self.case_type not in ALLOWED_CASE_TYPES:
            raise ValueError(f"Invalid case_type for {self.case_id}: {self.case_type}")
        if self.attack_tier not in ALLOWED_ATTACK_TIERS:
            raise ValueError(
                f"Invalid attack_tier for {self.case_id}: {self.attack_tier}"
            )
        if self.target_direction not in ALLOWED_TARGET_DIRECTIONS:
            raise ValueError(
                f"Invalid target_direction for {self.case_id}: {self.target_direction}"
            )
        if not self.article_refs:
            raise ValueError(f"{self.case_id} must reference at least one article")

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SecurityCase":
        case = cls(
            case_id=data["case_id"],
            base_case_id=data["base_case_id"],
            ticker=data["ticker"].upper(),
            scenario_id=data["scenario_id"],
            variant=data["variant"],
            split=data["split"],
            case_type=data["case_type"],
            attack_tier=data["attack_tier"],
            attack_family=data.get("attack_family", ""),
            objective=data.get("objective", ""),
            target_direction=data.get("target_direction", "neutral"),
            article_refs=list(data.get("article_refs", [])),
            financial_snapshot_ref=data["financial_snapshot_ref"],
            model_snapshot_ref=data["model_snapshot_ref"],
            expected_end_to_end_effect=data.get("expected_end_to_end_effect", ""),
            metadata=dict(data.get("metadata", {})),
        )
        case.validate()
        return case

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class RecommendationSnapshot:
    """User-visible metrics derived from one run."""

    rating: str
    rating_score: int
    expected_return_pct_12m: float
    target_12m_price: float
    target_12m_range_low: float
    target_12m_range_high: float
    overall_sentiment: str
    sentiment_score: int
    catalyst_count: int
    risk_count: int
    mitigation_count: int
    confidence_score: float

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RecommendationSnapshot":
        return cls(**data)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class CalculatorContribution:
    """Deterministic calculator inputs/outputs for one clean case."""

    adj_val_gap_pct: float
    catalyst_score_pct: float
    risk_score_pct: float
    net_catalyst_risk_pct: float
    momentum_score_pct: float
    expected_return_pct_12m: float
    rating: str

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CalculatorContribution":
        return cls(**data)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AttackabilityRecord:
    """Mechanistic attack-feasibility summary for one clean case."""

    case_id: str
    target_direction: str
    boundary_distance_pct: Optional[float]
    synthetic_deltas: Dict[str, Dict[str, Any]]
    attackable_with_single_doc: bool
    recommended_first_attack: str
    difficulty: str
    contribution: CalculatorContribution
    notes: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AttackabilityRecord":
        payload = dict(data)
        payload["contribution"] = CalculatorContribution.from_dict(payload["contribution"])
        return cls(**payload)

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["contribution"] = self.contribution.to_dict()
        return payload


@dataclass
class VerificationResult:
    """Structured verifier output."""

    flagged: bool = False
    confidence: float = 0.0
    reasons: List[str] = field(default_factory=list)
    suspicious_spans: List[str] = field(default_factory=list)
    model: Optional[str] = None
    mode: str = "disabled"

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VerificationResult":
        return cls(**data)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PairScore:
    """Comparison between a poisoned run and its clean baseline."""

    attack_success: bool
    screening_shift: bool
    recommendation_band_delta: int
    expected_return_delta_pct: float
    target_12m_delta_pct: float
    sentiment_delta: int
    catalyst_delta: int
    risk_delta: int
    mitigation_delta: int
    confidence_delta: float
    rationale: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SecurityRunResult:
    """One benchmark execution result."""

    case_id: str
    base_case_id: str
    ticker: str
    config_name: str
    split: str
    case_type: str
    attack_tier: str
    attack_family: str
    objective: str
    target_direction: str
    status: str
    run_id: str
    started_at: str
    completed_at: str
    duration_seconds: float
    blocked: bool
    article_count: int
    output_dir: str
    corpus_version: Optional[str] = None
    direction_map_version: Optional[str] = None
    attack_template_version: Optional[str] = None
    metric_version: Optional[str] = None
    target_model: Optional[str] = None
    code_commit: Optional[str] = None
    run_validity: str = "benchmark_candidate"
    notes: str = ""
    screening_data_path: Optional[str] = None
    report_path: Optional[str] = None
    review_path: Optional[str] = None
    snapshot: Optional[RecommendationSnapshot] = None
    verifier: Optional[VerificationResult] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SecurityRunResult":
        payload = dict(data)
        if payload.get("snapshot") is not None:
            payload["snapshot"] = RecommendationSnapshot.from_dict(payload["snapshot"])
        if payload.get("verifier") is not None:
            payload["verifier"] = VerificationResult.from_dict(payload["verifier"])
        return cls(**payload)

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        if self.snapshot:
            payload["snapshot"] = self.snapshot.to_dict()
        if self.verifier:
            payload["verifier"] = self.verifier.to_dict()
        return payload

    @classmethod
    def started(
        cls,
        case: SecurityCase,
        config_name: str,
        run_id: str,
        output_dir: Path,
        article_count: int,
    ) -> "SecurityRunResult":
        return cls(
            case_id=case.case_id,
            base_case_id=case.base_case_id,
            ticker=case.ticker,
            config_name=config_name,
            split=case.split,
            case_type=case.case_type,
            attack_tier=case.attack_tier,
            attack_family=case.attack_family,
            objective=case.objective,
            target_direction=case.target_direction,
            status="running",
            run_id=run_id,
            started_at=_iso_now(),
            completed_at="",
            duration_seconds=0.0,
            blocked=False,
            article_count=article_count,
            output_dir=str(output_dir),
        )
