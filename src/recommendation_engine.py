#!/usr/bin/env python3
"""
recommendation_engine_v3.py - Evidence-Based Recommendation Engine

Architecture:
1. Calculator (deterministic): All numbers computed in code
2. Evidence Pack: Structured evidence with IDs for citations
3. Explainer LLM: Writes comprehensive narrative (NO number invention)
4. Validator: Ensures numbers unchanged & citations present

Design: Numbers = Code, Narrative = LLM, Validation = Code + Critic
"""

import json
import traceback
import os
import re
from typing import Dict, Any, Tuple, Optional
from pathlib import Path

from recommendation_calculator import RecommendationCalculator
from evidence_extractor import EvidenceExtractor
from recommendation_validator import RecommendationValidator
from logger import StockAnalystLogger
from src.summary_evidence import compact_publication_reason


# Local copy rather than an import from report_agent, which imports this module.
_CCY = {
    "USD": "$", "EUR": "\u20ac", "GBP": "\u00a3", "JPY": "\u00a5", "CHF": "CHF ",
    "HKD": "HK$", "SGD": "S$", "AUD": "A$", "CAD": "C$", "CNY": "\u00a5",
    "KRW": "\u20a9", "INR": "\u20b9", "TWD": "NT$", "SEK": "SEK ", "NOK": "NOK ",
    "DKK": "DKK ", "BRL": "R$", "MXN": "MX$", "ZAR": "R",
}


def _symbol_for(code):
    code = (code or "USD").strip()
    return _CCY.get(code, f"{code} ")


class RecommendationEngineV3:
    """
    Evidence-based recommendation engine with deterministic calculations
    and comprehensive LLM narratives.
    """
    
    def __init__(self, sector: str = "default", logger: Optional[StockAnalystLogger] = None):
        self.calculator = RecommendationCalculator(sector=sector)
        self.evidence_extractor = EvidenceExtractor()
        self.validator = RecommendationValidator()
        self.sector = sector
        self.logger = logger
    
    def _load_prompt(self, prompt_name: str) -> str:
        """Load a prompt template from the prompts folder."""
        prompt_path = Path(__file__).parent.parent / "prompts" / f"{prompt_name}.md"
        with open(prompt_path, 'r') as f:
            return f.read()
    
    def _log(self, message: str, level: str = "info"):
        """Log message using logger if available, otherwise print."""
        if self.logger:
            if level == "info":
                self.logger.info(message)
            elif level == "warning":
                self.logger.warning(message)
            elif level == "error":
                self.logger.error(message)
        else:
            print(message)
    
    def generate_recommendation(
        self,
        company_data: Dict[str, Any],
        valuation_data: Dict[str, Any],
        screening_data: Dict[str, Any],
        llm
    ) -> Tuple[str, float]:
        """
        Generate comprehensive, evidence-based recommendation.
        
        Steps:
        1. Calculate all numbers deterministically
        2. Build evidence pack with citations
        3. Send to LLM for narrative explanation
        4. Validate output
        """
        
        # Step 1: Extract required data
        ticker = company_data.get('ticker', 'UNKNOWN')
        current_price = company_data.get('current_price', 0)
        week_52_low = company_data.get('week_52_low') or current_price
        week_52_high = company_data.get('week_52_high') or current_price
        
        # DCF values - handle None explicitly
        dcf_perpetual_raw = valuation_data.get('dcf_perpetual', {}).get('intrinsic_value_per_share')
        dcf_exit_raw = valuation_data.get('dcf_exit', {}).get('intrinsic_value_per_share')
        dcf_perpetual = dcf_perpetual_raw if dcf_perpetual_raw is not None else 0
        dcf_exit = dcf_exit_raw if dcf_exit_raw is not None else 0
        
        # Annualized realized volatility is derived from the saved daily price
        # history. Fall back only for legacy artifacts without that field.
        hist_vol_annual_pct = company_data.get('hist_vol_annual_pct')
        if not isinstance(hist_vol_annual_pct, (int, float)) or hist_vol_annual_pct <= 0:
            hist_vol_annual_pct = 18.0

        summary = valuation_data.get('summary', {}) or {}
        fair_value = summary.get('average_intrinsic')
        analyst_target = company_data.get('target_mean_price')
        analyst_count = (
            company_data.get('num_analysts')
            if company_data.get('analyst_target_qualified_for_contradiction', True)
            else 0
        )
        consensus = company_data.get('analyst_consensus', {}) or {}
        target_meta = consensus.get('price_target', {}) or {}
        recommendation_meta = consensus.get('recommendation', {}) or {}
        valuation_reliability = valuation_data.get('reliability') or {}

        def _analyst_count(value):
            if isinstance(value, bool):
                return 0
            try:
                return max(0, int(value or 0))
            except (TypeError, ValueError):
                return 0
        
        # Calculate catalyst, risk, and momentum scores
        catalysts = screening_data.get('catalysts', [])
        risks = screening_data.get('risks', [])
        sentiment = screening_data.get('analysis_summary', {}).get('overall_sentiment', 'neutral')
        freshness = screening_data.get('freshness') or {}
        # A thin/stale article set may be useful context, but it is not enough
        # evidence to move a deterministic rating.  Old cached Apple stories
        # previously supplied 40% of the expected-return formula indefinitely.
        if freshness and freshness.get('status') != 'fresh':
            catalysts = []
            risks = []
            sentiment = 'neutral'
            self._log(
                "⚠️  News evidence is not fresh/complete enough for rating inputs; "
                "catalyst, risk and sentiment adjustments set to neutral",
                "warning",
            )
        
        catalyst_score = self.calculator.estimate_catalyst_impact(catalysts)
        risk_score = self.calculator.estimate_risk_impact(risks)
        momentum_score = self.calculator.calculate_momentum(
            current_price, week_52_low, week_52_high, sentiment
        )
        
        # Step 2: Calculate fixed numbers (deterministic)
        # The listing currency, so code-generated lines (price targets, the
        # rating header) are denominated correctly. The prompt-level directive
        # added in report_agent only steers what the LLM writes; these lines are
        # built in Python and would otherwise stay hardcoded to "$".
        self._ccy = _symbol_for(company_data.get("currency"))

        fixed_numbers = self.calculator.calculate_fixed_numbers(
            ticker=ticker,
            current_price=current_price,
            dcf_perpetual=dcf_perpetual,
            dcf_exit=dcf_exit,
            catalyst_score_pct=catalyst_score,
            risk_score_pct=risk_score,
            momentum_score_pct=momentum_score,
            hist_vol_annual_pct=hist_vol_annual_pct,
            survival_risk=False,
            fair_value=fair_value,
            analyst_target=analyst_target,
            analyst_count=analyst_count,
            analyst_source=target_meta.get('source'),
            analyst_as_of=target_meta.get('as_of'),
            analyst_captured_at=consensus.get('captured_at'),
            analyst_rating=recommendation_meta.get('label'),
            analyst_rating_count=max(
                _analyst_count(recommendation_meta.get('total')),
                _analyst_count(recommendation_meta.get('analyst_count')),
                _analyst_count(recommendation_meta.get('unique_analyst_count')),
            ) if company_data.get('analyst_rating_qualified', True) else 0,
            valuation_reliability=valuation_reliability,
        )
        
        # Step 3: Build evidence pack
        evidence_pack = self.evidence_extractor.build_evidence_pack(screening_data)
        evidence_pack["news_freshness"] = freshness
        evidence_pack["articles_analyzed"] = articles_analyzed = (
            (screening_data or {}).get('analysis_summary', {}).get('articles_analyzed', 0)
        )

        # Limited coverage can be displayed as preliminary context in the news
        # section, but it is not a representative evidence base for a rating.
        # Passing those few items into the explainer caused it to extrapolate a
        # complete thesis, fabricate event dates, and attach valid-looking
        # citations to claims the cited headline did not support.
        limited_news_coverage = bool(
            freshness and freshness.get('status') != 'fresh'
        )
        if limited_news_coverage:
            evidence_pack['evidence'] = []

        # Only source-backed catalyst/risk items receive citation IDs. A pack
        # with no such items carries no citable news.
        evidence_items = evidence_pack.get('evidence', [])
        has_news_evidence = bool(evidence_items)
        if not has_news_evidence:
            if limited_news_coverage:
                self._log(
                    "News items were excluded from recommendation evidence because "
                    "coverage is limited; they remain visible as preliminary context "
                    "in the news section",
                    "warning",
                )
            else:
                self._log(
                    "⚠️  Evidence pack has no source-backed news items — "
                    "citations disabled, report will be annotated",
                    "warning",
                )
            evidence_pack['evidence'] = []

        # A withheld valuation has no recommendation for an LLM to invent or
        # embellish.  The deterministic publication policy already decided
        # NOT RATED and recorded the analyst/market disagreement that caused
        # it.  Calling a model here used four attempts to manufacture a
        # narrative, then usually fell back to the same safe facts.  Assemble
        # the non-recommendation directly: this is both clearer and removes a
        # failure/cost path from the most sensitive valuation state.
        if not fixed_numbers.get("rating_available", True):
            validation = {
                "deterministic_not_rated": True,
                "citation_support_issues": [],
            }
            evidence_pack["validation"] = {
                "status": "not_rated_deterministic",
                "coverage_pct": 100.0,
            }
            return self._evidence_safe_recommendation(
                fixed_numbers, evidence_pack, validation
            ), 0.0, evidence_pack

        # An empty evidence pack cannot support a free-form recommendation
        # narrative.  The previous path still called the model, disabled
        # citation enforcement, logged 0% coverage as "VALIDATION PASSED", and
        # shipped whatever prose remained.  A live NVDA canary then claimed
        # that $218.29 was above a disclosed $236.54 52-week high.  The full
        # report already contains deterministic financial/valuation/Street
        # sections and a separately bounded preliminary-news section; keep this
        # recommendation to the code-proven rating and target until there is a
        # representative, citable evidence pack.
        if not has_news_evidence:
            validation = {
                "deterministic_limited_news": True,
                "citation_support_issues": [],
            }
            evidence_pack["validation"] = {
                "status": "limited_news_deterministic",
                "coverage_pct": None,
            }
            return self._evidence_safe_recommendation(
                fixed_numbers, evidence_pack, validation
            ), 0.0, evidence_pack

        # Step 4: Build prompt
        prompt = self._build_explainer_prompt(
            fixed_numbers,
            evidence_pack,
            company_data,
            valuation_data,
            citations_enabled=has_news_evidence
        )
        
        # Production logs carry policy state and counts, not a second copy of
        # the entire prompt, evidence corpus, and generated report. Explicit
        # local debugging can opt back in.
        verbose = os.getenv("VYNN_VERBOSE_RECOMMENDATION_LOGS", "").strip().lower() \
            in {"1", "true", "yes", "on"}
        self._log(
            "Recommendation inputs prepared: "
            f"rating={fixed_numbers.get('rating')}, "
            f"point_withheld={not fixed_numbers.get('rating_available')}, "
            f"source_evidence={len(evidence_pack.get('evidence') or [])}."
        )
        if verbose:
            self._log(json.dumps(fixed_numbers, indent=2))
            self._log(json.dumps(evidence_pack, indent=2))
            self._log(prompt)
        
        # Step 5: Call LLM
        messages = [{"role": "user", "content": prompt}]
        response, cost = llm(messages, temperature=0.6)
        
        if verbose:
            self._log("LLM RESPONSE (Initial)\n" + response)
        
        # Step 6: Validate and auto-correct response
        total_cost = cost
        corrected_json, validation_report = self.validator.validate_and_correct(
            response, fixed_numbers, evidence_pack
        )
        
        # If JSON parsing failed completely, cannot proceed
        if corrected_json is None:
            self._log("\n❌ CRITICAL ERROR: JSON parsing failed completely", "error")
            self._log("="*80, "error")
            self._log("VALIDATION REPORT:", "error")
            self._log(json.dumps(validation_report, indent=2), "error")
            self._log("="*80, "error")
            raise ValueError("LLM response is not valid JSON. Cannot proceed.")
        
        if verbose:
            self._log("VALIDATION REPORT\n" + json.dumps(validation_report, indent=2))
        
        # Show detailed coverage breakdown
        coverage_details = validation_report.get("coverage_details", {})
        if coverage_details:
            self._log("📊 CITATION COVERAGE ANALYSIS")
            self._log("="*80)
            self._log(f"Material Sentences: {coverage_details.get('material_sentences', 0)}")
            self._log(f"Cited Sentences: {coverage_details.get('cited_sentences', 0)}")
            self._log(f"Coverage: {coverage_details.get('coverage_pct', 0):.1f}%")
            self._log("")
            
            uncited = coverage_details.get('uncited_sentences', [])
            if uncited and verbose:
                self._log(f"❌ UNCITED SENTENCES ({len(uncited)} total, showing first 10):")
                for i, sent in enumerate(uncited[:10], 1):
                    self._log(f"  {i}. {sent[:120]}...")
                self._log("")
            
            cited = coverage_details.get('cited_sentences', [])
            if cited and verbose:
                self._log(f"✅ CITED SENTENCES (showing {min(3, len(cited))} examples):")
                for i, sent in enumerate(cited[:3], 1):
                    self._log(f"  {i}. {sent[:120]}...")
                self._log("")
            self._log("="*80 + "\n")
        
        # Step 7: Multi-pass rewrite loop until 95%+ coverage or max attempts
        max_rewrite_attempts = 3
        rewrite_attempt = 0
        evidence_safe_fallback = None
        
        while self.validator.needs_rewrite(validation_report) and rewrite_attempt < max_rewrite_attempts:
            rewrite_attempt += 1
            self._log(f"\n⚠️  VALIDATION ISSUES DETECTED - Triggering Rewrite (Attempt {rewrite_attempt}/{max_rewrite_attempts})\n", "warning")
            
            if validation_report.get("corrections_made"):
                self._log("Auto-corrections applied:")
                for correction in validation_report["corrections_made"]:
                    self._log(f"  ✓ {correction}")
                self._log("")
            
            if validation_report.get("errors"):
                self._log("Errors found:")
                for error in validation_report["errors"]:
                    self._log(f"  ✗ {error}")
                self._log("")
            
            if validation_report.get("warnings"):
                self._log("Warnings:")
                for warning in validation_report["warnings"]:
                    self._log(f"  ⚠ {warning}")
                self._log("")
            
            # Build rewrite prompt with corrected JSON
            rewrite_prompt = self._build_rewrite_prompt(
                corrected_json,
                fixed_numbers,
                evidence_pack,
                validation_report,
                attempt=rewrite_attempt
            )
            
            if verbose:
                self._log(
                    f"REWRITE PROMPT (Attempt {rewrite_attempt})\n"
                    + (rewrite_prompt[:1500] + "..."
                       if len(rewrite_prompt) > 1500 else rewrite_prompt)
                )
            
            # Call LLM for text-only rewrite
            # Slightly increase temperature with each attempt for creativity
            rewrite_temp = 0.5 + (rewrite_attempt * 0.05)
            rewrite_messages = [{"role": "user", "content": rewrite_prompt}]
            rewrite_response, rewrite_cost = llm(rewrite_messages, temperature=rewrite_temp)
            total_cost += rewrite_cost
            
            if verbose:
                self._log(
                    f"LLM RESPONSE (Rewrite Attempt {rewrite_attempt})\n"
                    + (rewrite_response[:1000] + "..."
                       if len(rewrite_response) > 1000 else rewrite_response)
                )
            
            # Re-validate the rewrite
            final_json, validation_report = self.validator.validate_and_correct(
                rewrite_response, fixed_numbers, evidence_pack
            )
            
            # Update corrected_json if we got valid output
            if final_json:
                corrected_json = final_json
            
            if verbose:
                self._log(
                    f"VALIDATION REPORT (After Attempt {rewrite_attempt})\n"
                    + json.dumps(validation_report, indent=2)
                )
            
            # Show coverage progress
            coverage_details = validation_report.get("coverage_details", {})
            if coverage_details:
                self._log("📊 CITATION COVERAGE PROGRESS")
                self._log("="*80)
                self._log(f"Attempt {rewrite_attempt}: {coverage_details.get('coverage_pct', 0):.1f}% coverage")
                self._log(f"  Cited: {coverage_details.get('cited_sentences', 0)}/{coverage_details.get('material_sentences', 0)} sentences")
                self._log("="*80 + "\n")
            
            # If validation passed, break early
            if validation_report.get("valid"):
                self._log(f"✅ VALIDATION PASSED on attempt {rewrite_attempt} - Output is production-ready\n")
                break
        else:
            # Loop completed without breaking (either max attempts or no rewrite needed)
            if self.validator.needs_rewrite(validation_report):
                # The numerical conclusion remains useful, but prose that
                # repeatedly fails claim-to-evidence validation must never be
                # shipped after merely deleting its citations. That converts
                # a detected unsupported claim into an uncited unsupported
                # claim. Fall back to code-assembled conclusions plus compact
                # evidence titles that map directly to the appendix.
                coverage_pct = validation_report.get('coverage_details', {}).get('coverage_pct', 0)
                self._log(f"\n⚠️  Maximum rewrite attempts ({max_rewrite_attempts}) reached", "warning")
                self._log(
                    f"Final citation coverage: {coverage_pct:.1f}%; claim support still failed. "
                    "Replacing the LLM narrative with an evidence-safe deterministic fallback.",
                    "warning",
                )
                validation_report["degraded"] = True
                validation_report["degraded_reason"] = "claim_support_failed"
                evidence_safe_fallback = self._evidence_safe_recommendation(
                    fixed_numbers, evidence_pack, validation_report
                )
            else:
                self._log("\n✅ VALIDATION PASSED - No rewrite needed\n")

        if not validation_report.get("valid") and not (
            validation_report.get("degraded")
            or validation_report.get("citation_enforcement_bypassed")
        ):
            # Defensive fail-closed path for any invalid state not handled by
            # the normal rewrite loop.
            validation_report["degraded"] = True
            validation_report["degraded_reason"] = "validation_failed"
            evidence_safe_fallback = self._evidence_safe_recommendation(
                fixed_numbers, evidence_pack, validation_report
            )

        # Step 8: Format final output
        final_output = evidence_safe_fallback or self._format_final_output(
            json.dumps(corrected_json), fixed_numbers, validation_report
        )

        if verbose:
            self._log("FINAL OUTPUT\n" + final_output)

        # Machine-readable status for downstream consumers (safe sibling key:
        # the only reader, integrate_report_sections, uses .get('evidence')).
        if validation_report.get("citation_enforcement_bypassed"):
            status = "bypassed_no_news"
        elif validation_report.get("degraded"):
            status = "degraded"
        else:
            status = "passed"
        evidence_pack['validation'] = {
            "status": status,
            "coverage_pct": validation_report.get('coverage_details', {}).get('coverage_pct'),
        }

        return final_output, total_cost, evidence_pack
    
    def _build_rewrite_prompt(
        self,
        corrected_json: Dict[str, Any],
        fixed_numbers: Dict[str, Any],
        evidence_pack: Dict[str, Any],
        validation_report: Dict[str, Any],
        attempt: int = 1
    ) -> str:
        """Build text-only rewrite prompt with corrected JSON and iteration-specific guidance."""

        evidence_items = [
            {
                "id": ev.get("id"),
                "date": ev.get("date"),
                "source": ev.get("source"),
                "source_article_title": ev.get("source_article_title"),
                "snippet": ev.get("snippet"),
            }
            for ev in evidence_pack.get("evidence", [])
            if isinstance(ev, dict) and ev.get("id")
        ]
        valid_ids = sorted([ev["id"] for ev in evidence_items])
        valid_ids_rendered = (
            ", ".join(valid_ids) if valid_ids
            else "NONE — do not cite any evidence IDs"
        )
        
        # Build issues section
        issues_section = ""
        
        if validation_report.get("corrections_made"):
            issues_section += "**Numeric Corrections Made:**\n"
            for correction in validation_report["corrections_made"]:
                issues_section += f"- {correction}\n"
            issues_section += "\n"
        
        if validation_report.get("errors"):
            issues_section += "**Citation Errors:**\n"
            for error in validation_report["errors"]:
                issues_section += f"- {error}\n"
            issues_section += "\n"
        
        if validation_report.get("warnings"):
            issues_section += "**Warnings:**\n"
            for warning in validation_report["warnings"]:
                issues_section += f"- {warning}\n"
            issues_section += "\n"
        
        coverage = validation_report.get("coverage_details", {})
        if coverage:
            issues_section += f"**Citation Coverage**: {coverage.get('coverage_pct', 0):.1f}% "
            issues_section += f"({coverage.get('cited_sentences', 0)}/{coverage.get('material_sentences', 0)} sentences cited)\n"
            issues_section += "**PRODUCTION REQUIREMENT**: 95%+ coverage (YOU MUST ACHIEVE THIS)\n\n"
            
            # Show uncited sentences if available
            uncited = coverage.get('uncited_sentences', [])
            if uncited:
                issues_section += "**Sentences MISSING Citations** (add [E#] to these):\n"
                for i, sent in enumerate(uncited[:10], 1):
                    issues_section += f"{i}. {sent[:100]}...\n" if len(sent) > 100 else f"{i}. {sent}\n"
                issues_section += "\n"
            
            # Show examples of good citations
            cited = coverage.get('cited_sentences', [])
            if cited:
                issues_section += "**Examples of GOOD Citations** (keep this pattern):\n"
                for i, sent in enumerate(cited[:3], 1):
                    issues_section += f"{i}. {sent[:100]}...\n" if len(sent) > 100 else f"{i}. {sent}\n"
                issues_section += "\n"
        
        # Build iteration-specific guidance
        if attempt == 1:
            iteration_guidance = """
**First Attempt Strategy:**
- Rewrite unsupported claims so they say no more than the publisher headline
  and snippet below actually establish
- Remove a claim when no evidence item directly supports it
- Add [E#] only to source-backed news claims; leave deterministic valuation
  fields uncited
"""
        elif attempt == 2:
            iteration_guidance = """
**Second Attempt - Precision Focus:**
- Use near-extractive wording from SOURCE EVIDENCE for every remaining cited
  claim; do not rely on the prior generated interpretation
- If a complete bull/base/bear narrative cannot be supported, make it a
  conditional scenario and cite only the source fact that motivates it
- Never cite news as support for model prices, valuation ranges, or targets
"""
        else:
            iteration_guidance = """
**Final Attempt - Critical Push:**
- Delete or narrowly qualify every sentence listed as unsupported
- A shorter supported answer is better than a comprehensive unsupported one
- Never attach a merely related citation to make coverage appear complete
"""
        
        # Load template and fill in variables
        template = self._load_prompt("recommendation_rewrite")
        prompt = template.format(
            issues_section=issues_section,
            corrected_json=json.dumps(corrected_json, indent=2),
            valid_evidence_ids=valid_ids_rendered,
            source_evidence_json=json.dumps(evidence_items, indent=2),
            attempt=attempt,
            iteration_guidance=iteration_guidance
        )
        
        return prompt
    
    def _build_explainer_prompt(
        self,
        fixed_numbers: Dict[str, Any],
        evidence_pack: Dict[str, Any],
        company_data: Dict[str, Any],
        valuation_data: Dict[str, Any],
        citations_enabled: bool = True
    ) -> str:
        """Build explainer prompt for LLM."""
        
        # Load prompt template
        prompt_path = Path(__file__).parent.parent / "prompts" / "recommendation_explainer.md"
        with open(prompt_path, 'r') as f:
            template = f.read()
        
        # Prepare additional context
        # company_data comes from extract_company_overview() which has proper structure
        #
        # Ratios are rounded BEFORE the model sees them. The explainer is told not
        # to alter any number it is given, so a raw float arrives in the report
        # verbatim — a shipped LVMH note read "20.927107x earnings ... 3.3263094x
        # book value", which is seven decimal places of spurious precision in a
        # document meant to read as sell-side research.
        def _multiple(value):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                return value if value is not None else "N/A"
            if value != value:                 # NaN
                return "N/A"
            return f"{value:.2f}x"

        def _percent(value):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                return value if value is not None else "N/A"
            if value != value:
                return "N/A"
            return f"{value * 100:.1f}%"

        context = {
            "company_name": company_data.get('company_name', 'N/A'),
            "sector": company_data.get('sector', self.sector),
            "market_cap": company_data.get('market_cap', 'N/A'),
            "pe_ratio": _multiple(company_data.get('pe_trailing', company_data.get('pe_forward', 'N/A'))),
            "ev_ebitda": _multiple(company_data.get('ev_to_ebitda', 'N/A')),
            "pb_ratio": _multiple(company_data.get('price_to_book', 'N/A')),
            "revenue_growth": _percent(company_data.get('revenue_growth', 'N/A')),
            "net_margin": _percent(company_data.get('net_margin', 'N/A')),
            "roe": _percent(company_data.get('roe', 'N/A')),
            "debt_equity": _multiple(company_data.get('debt_to_equity', 'N/A')),
            "week_52_low": company_data.get('week_52_low', 0),
            "week_52_high": company_data.get('week_52_high', 0)
        }
        
        # Format prompt
        prompt = template.format(
            fixed_numbers_json=json.dumps(fixed_numbers, indent=2),
            evidence_pack_json=json.dumps(evidence_pack, indent=2),
            company_context=json.dumps(context, indent=2)
        )

        if not citations_enabled:
            # The template unconditionally mandates [E#] citations; when the
            # evidence pack is empty that demand would force fabrication.
            # This override supersedes it.
            prompt_freshness = evidence_pack.get("news_freshness") or {}
            coverage_status = str(prompt_freshness.get("status") or "unavailable").lower()
            article_count = int(
                prompt_freshness.get("fresh_articles")
                or evidence_pack.get("articles_analyzed") or 0
            )
            coverage_wording = (
                f"News coverage is {coverage_status} ({article_count} source-dated articles); "
                "describe it as insufficient/limited, not unavailable."
                if article_count > 0 else
                "No source-dated news evidence is available for this run."
            )
            prompt += (
                "\n\n---\n"
                "## OVERRIDE — NO NEWS EVIDENCE AVAILABLE\n"
                f"{coverage_wording}\n"
                "The evidence pack for this ticker is EMPTY. Ignore every "
                "citation requirement above: do NOT write any [E#] citation "
                "anywhere in your response. Base the narrative solely on "
                "FIXED_NUMBERS and COMPANY_CONTEXT, and make clear in the "
                "thesis using the exact coverage status stated above at "
                "generation time. Leave catalysts and risks empty; do not name "
                "events, competitors, sector averages, or event dates that are "
                "not explicitly present in those two inputs. Monitoring items "
                "may name metric categories, but no purported scheduled dates.\n"
            )

        if not fixed_numbers.get("rating_available", True) and fixed_numbers.get("price_available"):
            reliability = (fixed_numbers.get("inputs") or {}).get("valuation_reliability") or {}
            withheld_reason = reliability.get("withheld_reason") or (
                "The valuation evidence is not sufficient for a defensible point call."
            )
            prompt += (
                "\n\n---\n"
                "## OVERRIDE — VALUATION POINT ESTIMATE WITHHELD\n"
                f"Reason: {withheld_reason}\n"
                "The deterministic rating is "
                "NOT RATED and every price-target field is null. Do not invent, infer, "
                "or recommend a buy/sell rating, point fair value, upside percentage, "
                "entry point, or price target. Explain the limitation in the valuation evidence, "
                "use only the supported valuation range in valuation_reliability, and "
                "focus actions on what evidence or assumptions would resolve it. "
                "Bull/base/bear scenarios may describe operating conditions, but must "
                "not use the valuation-range endpoints as scenario price targets: those "
                "endpoints are outputs from different methods, not probabilistic cases.\n"
            )

        return prompt
    
    def _extract_json(self, response: str) -> Dict[str, Any]:
        """Extract JSON from LLM response with robust cleaning."""
        # Try to find JSON block
        if '```json' in response:
            start = response.find('```json') + 7
            end = response.find('```', start)
            json_str = response[start:end].strip()
        elif '{' in response:
            start = response.find('{')
            end = response.rfind('}') + 1
            json_str = response[start:end]
        else:
            json_str = response
        
        # Clean up common JSON issues
        # Remove trailing commas before closing braces/brackets (multiple passes for nested structures)
        # Do multiple passes to catch all nested cases
        for _ in range(3):
            json_str = re.sub(r',(\s*[}\]])', r'\1', json_str)  # Remove comma before } or ]
        
        # Remove any comments (sometimes LLMs add them)
        json_str = re.sub(r'//.*?\n', '\n', json_str)  # Remove // comments
        json_str = re.sub(r'/\*.*?\*/', '', json_str, flags=re.DOTALL)  # Remove /* */ comments
        
        return json.loads(json_str)
    
    def _format_final_output(
        self,
        llm_response: str,
        fixed_numbers: Dict[str, Any],
        validation_result: Dict[str, Any]
    ) -> str:
        """Format final markdown output."""
        
        try:
            response_data = self.validator._extract_json(llm_response)
            
            # Build markdown output
            output = []
            
            # Header
            ccy = getattr(self, "_ccy", "$")
            priced = fixed_numbers.get("price_available", True)
            rated = fixed_numbers.get("rating_available", priced)
            output.append(f"### Investment Rating: {fixed_numbers['rating']}")
            if rated:
                output.append(
                    f"**Rating Confidence**: "
                    f"{fixed_numbers.get('rating_confidence', 'moderate').title()}")
                output.append(
                    f"\n**12-Month Price Target**: "
                    f"{ccy}{fixed_numbers['targets']['m12']['price']:.2f}"
                )
                output.append(
                    f"**Implied Return if Intrinsic Value Converges**: "
                    f"{fixed_numbers['expected_return_pct_12m']:+.1f}%"
                )
                output.append(
                    "**Target Basis**: current published intrinsic value, with "
                    "convergence assumed by 12 months; this is not a statistically "
                    "forecast market price."
                )
            elif not priced:
                # Without a market price a target is not a low estimate, it is
                # arithmetic on a denominator we never had. Say that instead of
                # printing a confident "0.00".
                output.append(
                    "\n**No market price was available for this listing**, so no price "
                    "target, upside or rating can be derived. The intrinsic value below "
                    "still stands on its own; compare it against the price on the "
                    "company's primary listing."
                )
            else:
                reliability = (fixed_numbers.get('inputs') or {}).get('valuation_reliability') or {}
                low, high = reliability.get('range_low'), reliability.get('range_high')
                band = reliability.get('band') or 'unavailable'
                output.append(f"**Valuation Confidence**: {band.title()}")
                output.append("**Point Estimate**: Withheld")
                range_text = ""
                if isinstance(low, (int, float)) and isinstance(high, (int, float)):
                    range_text = f" The model outputs span {ccy}{low:,.2f}–{ccy}{high:,.2f}."
                    output.append(
                        f"**Supported Valuation Range**: {ccy}{low:,.2f} – {ccy}{high:,.2f}"
                    )
                output.append(
                    "\n**No point rating or price target is published.** "
                    f"{fixed_numbers.get('rating_withheld_reason') or 'The valuation is not reliable enough for a directional call.'}"
                    f"{range_text}"
                )
            
            # Thesis
            output.append(f"\n### Investment Thesis\n")
            output.append(response_data.get('thesis', ''))
            
            # Valuation Perspective
            output.append(f"\n### Valuation Perspective\n")
            output.append(response_data.get('valuation_perspective', ''))
            
            # There is no defensible generated 3/6-month path.  The former
            # progressive targets were fractions of an arbitrary weighted
            # score, not separately modelled horizons.
            if rated:
                output.append(f"\n### Valuation-Convergence Case\n")
                target = fixed_numbers['targets']['m12']
                range_low, range_high = target.get('range_low'), target.get('range_high')
                range_text = (
                    f"; method range {ccy}{range_low:.2f}–{ccy}{range_high:.2f}"
                    if isinstance(range_low, (int, float))
                    and isinstance(range_high, (int, float)) else ""
                )
                output.append(
                    f"**12-Month convergence case**: {ccy}{target['price']:.2f}"
                    f"{range_text}."
                )
                output.append(
                    "This target is the approved point intrinsic value, not a blend "
                    "of news sentiment, historical volatility, or analyst consensus."
                )
            
            # Catalysts
            output.append(f"\n### Catalysts to Watch\n")
            catalysts = response_data.get('catalysts', [])
            for cat in catalysts:
                stmt = cat.get('statement', cat) if isinstance(cat, dict) else cat
                output.append(f"- {stmt}")
            
            # Risks
            output.append(f"\n### Key Risks\n")
            risks = response_data.get('risks', [])
            for risk in risks:
                stmt = risk.get('statement', risk) if isinstance(risk, dict) else risk
                output.append(f"- {stmt}")
            
            # Scenarios (if available)
            scenarios = response_data.get('scenarios', {})
            if scenarios:
                output.append(f"\n### Scenario Analysis\n")
                
                for scenario_name, scenario_label in [('bull', 'Bull Case'), ('base', 'Base Case'), ('bear', 'Bear Case')]:
                    scenario = scenarios.get(scenario_name, {})
                    if scenario:
                        narrative = scenario.get('narrative', '')
                        watch = scenario.get('watch', [])
                        output.append(f"**{scenario_label}**: {narrative}")
                        if watch:
                            output.append(f"  - Watch: {', '.join(watch)}\n")
            
            # Action
            action = response_data.get('action', {}) if rated else {}
            if action:
                output.append(f"\n### Recommended Action\n")
                if action.get('buyers'):
                    output.append(f"**For Buyers**: {action['buyers']}\n")
                if action.get('holders'):
                    output.append(f"**For Holders**: {action['holders']}\n")
                if action.get('watch'):
                    output.append(f"**Key Metrics to Monitor**: {', '.join(action['watch'])}")
            
            # Monitoring Plan
            monitoring = response_data.get('monitoring_plan', [])
            if monitoring:
                output.append(f"\n### Monitoring Plan\n")
                for item in monitoring:
                    output.append(f"- {item}")
            
            # Add calculation transparency
            output.append(f"\n---\n### Calculation Methodology\n")
            inputs = fixed_numbers['inputs']
            basis = inputs.get('valuation_basis', 'valuation')
            if rated:
                output.append(f"- **Valuation Gap ({basis.replace('_', ' ')})**: {inputs['raw_val_gap_pct']:.1f}%")
            else:
                reliability = inputs.get('valuation_reliability') or {}
                band = reliability.get('band') or 'unavailable'
                ratio = reliability.get('dispersion_ratio')
                detail = f", {ratio:.1f}x dispersion" if isinstance(ratio, (int, float)) else ""
                output.append(f"- **Valuation Reliability**: {band.replace('-', ' ').title()}{detail}")
            if inputs.get('analyst_target_gap_pct') is not None:
                output.append(
                    f"- **Analyst Consensus Cross-check**: "
                    f"{inputs['analyst_target_gap_pct']:+.1f}% "
                    f"({inputs.get('analyst_count', 0)} analysts; "
                    f"{inputs.get('analyst_source') or 'source unavailable'}; "
                    f"provider as of {inputs.get('analyst_as_of') or 'date unavailable'}; "
                    f"captured {inputs.get('analyst_captured_at') or 'time unavailable'}; "
                    f"alignment: {inputs.get('consensus_alignment', 'unavailable')}; "
                    f"not included in intrinsic value)")
            if rated:
                output.append(
                    "- **Target arithmetic**: published intrinsic value divided by "
                    "current price, less one."
                )
                output.append(
                    "- **Qualitative evidence**: catalysts, risks, sentiment, and "
                    "52-week-range position inform the narrative and monitoring plan "
                    "but do not mechanically add percentage points to the target."
                )
                output.append(
                    f"- **Convergence-case implied return**: "
                    f"{fixed_numbers['expected_return_pct_12m']:.1f}%"
                )

            # Conspicuous annotation when the section shipped without full
            # citation validation — readers must not mistake it for a fully
            # evidence-backed recommendation.
            if validation_result.get("citation_enforcement_bypassed"):
                output.append(
                    "\n> **Note**: News evidence was unavailable for this ticker at "
                    "generation time. This recommendation is based on the published "
                    "valuation output only; qualitative evidence did not alter the target and citations "
                    "are omitted."
                )
            elif validation_result.get("degraded"):
                coverage_pct = validation_result.get(
                    'coverage_details', {}
                ).get('coverage_pct', 0) or 0
                output.append(
                    f"\n> **Validation Warning**: This section did not pass final "
                    f"claim-to-evidence validation after rewrite attempts (citation "
                    f"coverage {coverage_pct:.1f}%). Numeric fields are deterministic "
                    f"and unaffected; unvalidated narrative is not authoritative."
                )

            return '\n'.join(output)
            
        except Exception:
            # This used to `return ... {llm_response}`, which pasted the model's
            # raw JSON payload — 7,000 characters of {"rating": "SELL", ...} with
            # \u2019 escapes — into the middle of a professional report, and said
            # nothing about it. A NameError introduced in c81d3e3 meant the branch
            # was taken on EVERY report for eleven days: 12 of 33 stored reports
            # carry the blob, including real users'.
            #
            # A fallback must degrade to something a reader can use, and it must
            # be loud enough that the next failure is found by a log rather than
            # by a customer.
            self._log(
                "Recommendation formatting failed; emitting the deterministic "
                "summary without the narrative.\n" + traceback.format_exc(),
                "error",
            )
            return self._minimal_recommendation(fixed_numbers)

    def _evidence_safe_recommendation(
        self,
        fixed_numbers: Dict[str, Any],
        evidence_pack: Dict[str, Any],
        validation_result: Dict[str, Any],
    ) -> str:
        """Deterministic fallback after narrative claim-support failure."""
        ccy = getattr(self, "_ccy", "$")
        lines = [f"### Investment Rating: {fixed_numbers.get('rating', 'NOT RATED')}"]
        rated = fixed_numbers.get(
            "rating_available", fixed_numbers.get("price_available", True)
        )
        if rated:
            lines.append(
                f"**Rating Confidence**: "
                f"{fixed_numbers.get('rating_confidence', 'moderate').title()}"
            )
            target = (fixed_numbers.get("targets") or {}).get("m12") or {}
            if isinstance(target.get("price"), (int, float)):
                lines.append(f"**12-Month Price Target**: {ccy}{target['price']:.2f}")
            expected = fixed_numbers.get("expected_return_pct_12m")
            if isinstance(expected, (int, float)):
                lines.append(
                    f"**Implied Return if Intrinsic Value Converges**: {expected:+.1f}%"
                )
            lines.append(
                "**Target Basis**: current published intrinsic value, with "
                "convergence assumed by 12 months."
            )
        elif fixed_numbers.get("price_available", True):
            reliability = (fixed_numbers.get("inputs") or {}).get(
                "valuation_reliability") or {}
            band = reliability.get("band") or "unavailable"
            lines.extend([
                f"**Valuation Confidence**: {str(band).title()}",
                "**Valuation Conclusion**: Inconclusive",
                "**Point Estimate**: Withheld",
            ])
            low, high = reliability.get("range_low"), reliability.get("range_high")
            if isinstance(low, (int, float)) and isinstance(high, (int, float)):
                lines.append(
                    f"**Supported Valuation Range**: {ccy}{low:,.2f} – {ccy}{high:,.2f}"
                )
            lines.append(
                "\n**No point rating or price target is published.** "
                + compact_publication_reason(fixed_numbers.get("rating_withheld_reason") or (
                    "The valuation evidence is not reliable enough for a directional call."
                ))
            )
        else:
            lines.append(
                "\n**No market price was available**, so no price target, upside, "
                "or rating can be derived."
            )

        evidence = [
            item for item in (evidence_pack.get("evidence") or [])
            if isinstance(item, dict)
            and item.get("id")
            and item.get("source_article_title")
        ]
        catalysts = sorted(
            (item for item in evidence if str(item.get("type", "")).startswith("catalyst_")),
            key=lambda item: float(item.get("relevance") or 0),
            reverse=True,
        )[:3]
        risks = sorted(
            (item for item in evidence if str(item.get("type", "")).startswith("risk_")),
            key=lambda item: float(item.get("relevance") or 0),
            reverse=True,
        )[:3]

        lines.append("\n### Source-Grounded Signals")
        if catalysts:
            lines.append("\n**Source items classified as potential catalysts**")
            for item in catalysts:
                # `title` is an upstream model's interpretation.  The safe
                # fallback must not publish it as if it were the source's own
                # claim; use the actual publisher headline instead.
                title = str(item["source_article_title"]).strip().rstrip(".")
                lines.append(f"- {title}. [{item['id']}]")
        if risks:
            lines.append("\n**Source items classified as potential risks**")
            for item in risks:
                title = str(item["source_article_title"]).strip().rstrip(".")
                lines.append(f"- {title}. [{item['id']}]")
        if not catalysts and not risks:
            news_freshness = evidence_pack.get("news_freshness") or {}
            article_count = int(
                news_freshness.get("fresh_articles")
                or evidence_pack.get("articles_analyzed")
                or 0
            )
            if article_count and news_freshness.get("status") != "fresh":
                minimum = news_freshness.get("minimum_articles")
                threshold = (
                    f"; at least {minimum} are required"
                    if isinstance(minimum, int) and minimum > 0 else ""
                )
                lines.append(
                    "\nPreliminary source-backed news items were found, but the "
                    f"{article_count}-article sample is below the coverage threshold"
                    f"{threshold}. They are shown in the News section and excluded "
                    "from recommendation evidence."
                )
            else:
                lines.append("\nNo validated source-grounded news signals were available.")

        support_issues = len(validation_result.get("citation_support_issues") or [])
        structure_issues = validation_result.get("structure_issues") or []
        fallback_reason = (
            "the generated recommendation was structurally incomplete"
            if structure_issues else
            f"{support_issues or 'one or more'} claim-to-evidence support check(s) "
            "did not pass"
        )
        if validation_result.get("deterministic_not_rated"):
            evidence_note = (
                " Any source headlines shown here map directly to their evidence "
                "entries in the appendix."
                if catalysts or risks else
                " Limited news context, if present, remains in the News section and "
                "does not affect this conclusion."
            )
            lines.append(
                "\n> **Publication note**: no recommendation narrative was generated "
                "because the valuation policy withheld the point estimate and rating. "
                "The status and range above are deterministic."
                + evidence_note
            )
        elif validation_result.get("deterministic_limited_news"):
            lines.append(
                "\n> **Publication note**: no free-form recommendation narrative "
                "was generated because current news coverage did not meet the "
                "evidence threshold. The rating and convergence target above are "
                "deterministic; preliminary news remains visible in the News "
                "section and does not affect them."
            )
        else:
            lines.append(
                "\n> **Narrative validation fallback**: the generated prose was omitted "
                f"because {fallback_reason} after rewrite attempts. The rating, valuation "
                "status, and range above are deterministic; the source headlines shown "
                "here map directly to their evidence entries in the appendix."
            )
        return "\n".join(lines)

    def _minimal_recommendation(self, fixed_numbers: Dict[str, Any]) -> str:
        """
        The recommendation reduced to the numbers the calculator already proved.

        Used when narrative formatting fails. Everything here is computed in
        Python, so it is safe to publish even when the LLM payload is unusable.
        """
        ccy = getattr(self, "_ccy", "$")
        lines = [f"### Investment Rating: {fixed_numbers.get('rating', 'NOT RATED')}"]
        rated = fixed_numbers.get("rating_available", fixed_numbers.get("price_available", True))
        confidence = fixed_numbers.get('rating_confidence')
        if rated or (fixed_numbers.get('rating') != 'NOT RATED' and confidence):
            lines.append(
                f"**Rating Confidence**: "
                f"{(confidence or 'moderate').title()}"
            )
        if rated:
            target = (fixed_numbers.get("targets") or {}).get("m12") or {}
            if target.get("price") is not None:
                lines.append(f"\n**12-Month Price Target**: {ccy}{target['price']:.2f}")
            expected = fixed_numbers.get("expected_return_pct_12m")
            if expected is not None:
                lines.append(
                    f"**Implied Return if Intrinsic Value Converges**: {expected:+.1f}%"
                )
            lines.append(
                "**Target Basis**: current published intrinsic value, with "
                "convergence assumed by 12 months."
            )
        elif not fixed_numbers.get("price_available", True):
            lines.append(
                "\n**No market price was available for this listing**, so no price "
                "target, upside or rating can be derived."
            )
        else:
            lines.append(
                "\n**No point rating or price target is published.** "
                f"{compact_publication_reason(fixed_numbers.get('rating_withheld_reason') or 'The valuation is not reliable enough for a directional call.')}"
            )
        lines.append(
            "\n> **Note**: the narrative for this section could not be rendered, so "
            "only the model's deterministic conclusion is shown. Published ratings "
            "and targets are calculated in code, not written by the model. The "
            "target is the published intrinsic value under a 12-month convergence "
            "assumption; qualitative signals do not alter it."
        )
        return "\n".join(lines)
