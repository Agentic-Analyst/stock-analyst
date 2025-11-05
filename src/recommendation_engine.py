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
import os
from typing import Dict, Any, Tuple, Optional
from pathlib import Path

from recommendation_calculator import RecommendationCalculator
from evidence_extractor import EvidenceExtractor
from recommendation_validator import RecommendationValidator
from logger import StockAnalystLogger


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
        week_52_low = company_data.get('week_52_low', current_price)
        week_52_high = company_data.get('week_52_high', current_price)
        
        # DCF values
        dcf_perpetual = valuation_data.get('dcf_perpetual', {}).get('intrinsic_value_per_share', 0)
        dcf_exit = valuation_data.get('dcf_exit', {}).get('intrinsic_value_per_share', 0)
        
        # Estimate volatility from company data or use default
        # TODO: Calculate actual historical volatility from price data
        hist_vol_annual_pct = 18.0  # Default for tech stocks
        
        # Calculate catalyst, risk, and momentum scores
        catalysts = screening_data.get('catalysts', [])
        risks = screening_data.get('risks', [])
        sentiment = screening_data.get('analysis_summary', {}).get('overall_sentiment', 'neutral')
        
        catalyst_score = self.calculator.estimate_catalyst_impact(catalysts)
        risk_score = self.calculator.estimate_risk_impact(risks)
        momentum_score = self.calculator.calculate_momentum(
            current_price, week_52_low, week_52_high, sentiment
        )
        
        # Step 2: Calculate fixed numbers (deterministic)
        fixed_numbers = self.calculator.calculate_fixed_numbers(
            ticker=ticker,
            current_price=current_price,
            dcf_perpetual=dcf_perpetual,
            dcf_exit=dcf_exit,
            catalyst_score_pct=catalyst_score,
            risk_score_pct=risk_score,
            momentum_score_pct=momentum_score,
            hist_vol_annual_pct=hist_vol_annual_pct,
            survival_risk=False
        )
        
        # Step 3: Build evidence pack
        evidence_pack = self.evidence_extractor.build_evidence_pack(screening_data)
        
        # Step 4: Build prompt
        prompt = self._build_explainer_prompt(
            fixed_numbers,
            evidence_pack,
            company_data,
            valuation_data
        )
        
        # Debug output
        self._log("\n" + "="*80)
        self._log("FIXED NUMBERS (Deterministic - LLM CANNOT change these)")
        self._log("="*80)
        self._log(json.dumps(fixed_numbers, indent=2))
        self._log("\n" + "="*80)
        self._log("EVIDENCE PACK (for citations)")
        self._log("="*80)
        self._log(json.dumps(evidence_pack, indent=2)[:2000] + "...")
        self._log("\n" + "="*80)
        self._log("EXPLAINER PROMPT")
        self._log("="*80)
        self._log(prompt)
        self._log("="*80 + "\n")
        
        # Step 5: Call LLM
        messages = [{"role": "user", "content": prompt}]
        response, cost = llm(messages, temperature=0.6)
        
        self._log("\n" + "="*80)
        self._log("LLM RESPONSE (Initial)")
        self._log("="*80)
        self._log(response)
        self._log("="*80 + "\n")
        
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
        
        self._log("\n" + "="*80)
        self._log("VALIDATION REPORT")
        self._log("="*80)
        self._log(json.dumps(validation_report, indent=2))
        self._log("="*80 + "\n")
        
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
            if uncited:
                self._log(f"❌ UNCITED SENTENCES ({len(uncited)} total, showing first 10):")
                for i, sent in enumerate(uncited[:10], 1):
                    self._log(f"  {i}. {sent[:120]}...")
                self._log("")
            
            cited = coverage_details.get('cited_sentences', [])
            if cited:
                self._log(f"✅ CITED SENTENCES (showing {min(3, len(cited))} examples):")
                for i, sent in enumerate(cited[:3], 1):
                    self._log(f"  {i}. {sent[:120]}...")
                self._log("")
            self._log("="*80 + "\n")
        
        # Step 7: Multi-pass rewrite loop until 95%+ coverage or max attempts
        max_rewrite_attempts = 3
        rewrite_attempt = 0
        
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
            
            self._log("\n" + "="*80)
            self._log(f"REWRITE PROMPT (Attempt {rewrite_attempt})")
            self._log("="*80)
            self._log(rewrite_prompt[:1500] + "..." if len(rewrite_prompt) > 1500 else rewrite_prompt)
            self._log("="*80 + "\n")
            
            # Call LLM for text-only rewrite
            # Slightly increase temperature with each attempt for creativity
            rewrite_temp = 0.5 + (rewrite_attempt * 0.05)
            rewrite_messages = [{"role": "user", "content": rewrite_prompt}]
            rewrite_response, rewrite_cost = llm(rewrite_messages, temperature=rewrite_temp)
            total_cost += rewrite_cost
            
            self._log("\n" + "="*80)
            self._log(f"LLM RESPONSE (Rewrite Attempt {rewrite_attempt})")
            self._log("="*80)
            self._log(rewrite_response[:1000] + "..." if len(rewrite_response) > 1000 else rewrite_response)
            self._log("="*80 + "\n")
            
            # Re-validate the rewrite
            final_json, validation_report = self.validator.validate_and_correct(
                rewrite_response, fixed_numbers, evidence_pack
            )
            
            # Update corrected_json if we got valid output
            if final_json:
                corrected_json = final_json
            
            self._log("\n" + "="*80)
            self._log(f"VALIDATION REPORT (After Attempt {rewrite_attempt})")
            self._log("="*80)
            self._log(json.dumps(validation_report, indent=2))
            self._log("="*80 + "\n")
            
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
                coverage_pct = validation_report.get('coverage_details', {}).get('coverage_pct', 0)
                self._log(f"\n⚠️  Maximum rewrite attempts ({max_rewrite_attempts}) reached", "warning")
                self._log(f"Final coverage: {coverage_pct:.1f}%", "warning")
                raise RuntimeError(
                    f"Recommendation validation failed after {max_rewrite_attempts} rewrite attempts; final coverage {coverage_pct:.1f}%"
                )
            else:
                self._log("\n✅ VALIDATION PASSED - No rewrite needed\n")

        if not validation_report.get("valid"):
            coverage_pct = validation_report.get('coverage_details', {}).get('coverage_pct', 0)
            raise RuntimeError(
                f"Recommendation validation failed; coverage {coverage_pct:.1f}% is below the required threshold"
            )

        # Step 8: Format final output
        final_output = self._format_final_output(
            json.dumps(corrected_json),
            fixed_numbers,
            validation_report
        )
        
        self._log("\n" + "="*80)
        self._log("FINAL OUTPUT")
        self._log("="*80)
        self._log(final_output)
        self._log("="*80 + "\n")

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
        
        valid_ids = sorted([ev['id'] for ev in evidence_pack.get('evidence', [])])
        
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
- Focus on the UNCITED sentences listed above
- Add [E#] citations to ALL material claims
- Check price target drivers especially (commonly missed)
- Verify catalysts and risks have citations
"""
        elif attempt == 2:
            iteration_guidance = """
**Second Attempt - Precision Focus:**
- You're getting closer! Target the remaining uncited sentences
- Double-check numeric comparisons (e.g., "priced at $X") need citations
- Ensure EVERY scenario narrative has [E#] citations
- Review price target drivers one more time
"""
        else:
            iteration_guidance = """
**Final Attempt - Critical Push:**
- This is your last chance to reach 95%+
- Review EVERY sentence for factual claims
- Add citations to comparisons, valuations, targets
- Be aggressive - when in doubt, cite relevant evidence
"""
        
        # Load template and fill in variables
        template = self._load_prompt("recommendation_rewrite")
        prompt = template.format(
            issues_section=issues_section,
            corrected_json=json.dumps(corrected_json, indent=2),
            valid_evidence_ids=', '.join(valid_ids),
            attempt=attempt,
            iteration_guidance=iteration_guidance
        )
        
        return prompt
    
    def _build_explainer_prompt(
        self,
        fixed_numbers: Dict[str, Any],
        evidence_pack: Dict[str, Any],
        company_data: Dict[str, Any],
        valuation_data: Dict[str, Any]
    ) -> str:
        """Build explainer prompt for LLM."""
        
        # Load prompt template
        prompt_path = Path(__file__).parent.parent / "prompts" / "recommendation_explainer.md"
        with open(prompt_path, 'r') as f:
            template = f.read()
        
        # Prepare additional context
        # company_data comes from extract_company_overview() which has proper structure
        context = {
            "company_name": company_data.get('company_name', 'N/A'),
            "sector": company_data.get('sector', self.sector),
            "market_cap": company_data.get('market_cap', 'N/A'),
            "pe_ratio": company_data.get('pe_trailing', company_data.get('pe_forward', 'N/A')),
            "ev_ebitda": company_data.get('ev_to_ebitda', 'N/A'),
            "pb_ratio": company_data.get('price_to_book', 'N/A'),
            "revenue_growth": company_data.get('revenue_growth', 'N/A'),
            "net_margin": company_data.get('net_margin', 'N/A'),
            "roe": company_data.get('roe', 'N/A'),
            "debt_equity": company_data.get('debt_to_equity', 'N/A'),
            "week_52_low": company_data.get('week_52_low', 0),
            "week_52_high": company_data.get('week_52_high', 0)
        }
        
        # Format prompt
        prompt = template.format(
            fixed_numbers_json=json.dumps(fixed_numbers, indent=2),
            evidence_pack_json=json.dumps(evidence_pack, indent=2),
            company_context=json.dumps(context, indent=2)
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
        import re
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
            output.append(f"## Investment Rating: {fixed_numbers['rating']}")
            output.append(f"\n**12-Month Price Target**: ${fixed_numbers['targets']['m12']['price']:.2f}")
            output.append(f"**Expected Return**: {fixed_numbers['expected_return_pct_12m']:+.1f}%")
            
            # Thesis
            output.append(f"\n### Investment Thesis\n")
            output.append(response_data.get('thesis', ''))
            
            # Valuation Perspective
            output.append(f"\n### Valuation Perspective\n")
            output.append(response_data.get('valuation_perspective', ''))
            
            # Price Targets
            output.append(f"\n### Price Targets\n")
            for period, label in [('m3', '3-Month'), ('m6', '6-Month'), ('m12', '12-Month')]:
                target = fixed_numbers['targets'][period]
                driver = response_data.get('price_targets', {}).get(period, {}).get('driver', 'N/A')
                output.append(f"**{label}**: ${target['price']:.2f} (Range: ${target['range_low']:.2f} - ${target['range_high']:.2f})")
                output.append(f"- Key Driver: {driver}\n")
            
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
            action = response_data.get('action', {})
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
            output.append(f"- **Raw Valuation Gap**: {inputs['raw_val_gap_pct']:.1f}%")
            output.append(f"- **Sector Premium Adjustment**: {inputs['sector_premium_adjustment']*100:.0f}%")
            output.append(f"- **Adjusted Valuation Gap**: {inputs['adj_val_gap_pct']:.1f}%")
            output.append(f"- **Catalyst Score**: +{inputs['catalyst_score_pct']:.1f}%")
            output.append(f"- **Risk Score**: -{inputs['risk_score_pct']:.1f}%")
            output.append(f"- **Momentum Score**: {inputs['momentum_score_pct']:+.1f}%")
            output.append(f"\n**Expected Return Formula**:")
            output.append(f"- 40% × Valuation ({inputs['adj_val_gap_pct']:.1f}%) = {0.4 * inputs['adj_val_gap_pct']:.1f}%")
            output.append(f"- 40% × Net Catalysts/Risks ({inputs['net_catalyst_risk_pct']:.1f}%) = {0.4 * inputs['net_catalyst_risk_pct']:.1f}%")
            output.append(f"- 20% × Momentum ({inputs['momentum_score_pct']:.1f}%) = {0.2 * inputs['momentum_score_pct']:.1f}%")
            output.append(f"- **Total**: {fixed_numbers['expected_return_pct_12m']:.1f}%")
            
            return '\n'.join(output)
            
        except Exception as e:
            # Fallback to simple format
            return f"## Investment Rating: {fixed_numbers['rating']}\n\n{llm_response}"
