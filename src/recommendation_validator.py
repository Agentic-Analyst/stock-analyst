#!/usr/bin/env python3
"""
recommendation_validator.py - Comprehensive Validation & Auto-Correction

Validates LLM output and auto-corrects violations:
1. Numbers must match FixedNumbers exactly
2. All evidence IDs must exist in EvidencePack
3. Material claims must have citations
4. No invented facts or metrics

If validation fails, auto-corrects and triggers LLM text-only rewrite.
"""

import re
import json
from typing import Dict, Any, List, Tuple, Set


class RecommendationValidator:
    """
    Validates and auto-corrects LLM recommendation output.
    Ensures 100% determinism and evidence-backed claims.
    """
    
    # Pattern to find evidence citations like [E1] or [E2][E3]
    EVIDENCE_PATTERN = re.compile(r'\[E(\d+)\]')
    
    # Pattern to find sentences (handle abbreviations like U.S., Dr., etc.)
    # Split on . ! ? but not on abbreviations
    SENTENCE_PATTERN = re.compile(r'(?<!\b[A-Z])(?<!\b[A-Z][a-z])(?<!\bU\.S)(?<!\bU\.K)(?<!\bDr)(?<!\bMr)(?<!\bMs)(?<!\bInc)(?<!\bCo)(?<!\bCorp)(?<!\betc)(?<!\bi\.e)(?<!\be\.g)[.!?]+(?=\s+[A-Z]|$)', re.MULTILINE)
    
    def validate_and_correct(
        self,
        llm_response: str,
        fixed_numbers: Dict[str, Any],
        evidence_pack: Dict[str, Any]
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """
        Validate LLM response and auto-correct if needed.
        
        Returns:
            (corrected_json, validation_report)
        """
        
        # Parse JSON from response
        try:
            response_data = self._extract_json(llm_response)
        except Exception as e:
            return None, {
                "valid": False,
                "errors": [f"JSON parsing failed: {str(e)}"],
                "auto_corrected": False
            }
        
        # Build validation report
        validation_report = {
            "valid": True,
            "errors": [],
            "warnings": [],
            "auto_corrected": False,
            "corrections_made": []
        }
        
        # Get valid evidence IDs
        valid_evidence_ids = {ev['id'] for ev in evidence_pack.get('evidence', [])}
        
        # 1. Validate and correct numeric fields
        numeric_corrections = self._validate_numbers(
            response_data, 
            fixed_numbers, 
            validation_report
        )
        
        if numeric_corrections:
            response_data = numeric_corrections
            validation_report["auto_corrected"] = True
        
        # 2. Validate evidence citations
        invalid_citations = self._validate_evidence_citations(
            response_data,
            valid_evidence_ids,
            validation_report
        )
        
        if invalid_citations:
            validation_report["errors"].append(
                f"Invalid evidence IDs cited: {invalid_citations}"
            )
            validation_report["valid"] = False
        
        # 3. Check citation coverage
        coverage = self._check_citation_coverage(
            response_data,
            valid_evidence_ids,
            validation_report
        )
        
        # PRODUCTION REQUIREMENT: 95% minimum coverage
        if coverage < 95.0:
            validation_report["errors"].append(
                f"Citation coverage {coverage:.1f}% is below required 95% threshold"
            )
            validation_report["valid"] = False
        
        # 4. Check for unsupported claims
        unsupported = self._check_unsupported_claims(
            response_data,
            evidence_pack,
            validation_report
        )
        
        if unsupported:
            validation_report["warnings"].extend(unsupported)
        
        return response_data, validation_report
    
    def _extract_json(self, response: str) -> Dict[str, Any]:
        """Extract JSON from LLM response with robust cleaning."""
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
    
    def _validate_numbers(
        self,
        response_data: Dict[str, Any],
        fixed_numbers: Dict[str, Any],
        report: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Validate all numeric fields match FixedNumbers.
        Auto-correct if mismatched.
        """
        corrections_needed = False
        corrected_data = response_data.copy()
        
        # 1. Check rating
        if response_data.get('rating') != fixed_numbers['rating']:
            report["corrections_made"].append(
                f"Rating corrected: {response_data.get('rating')} → {fixed_numbers['rating']}"
            )
            corrected_data['rating'] = fixed_numbers['rating']
            corrections_needed = True
        
        # 2. Check price targets
        if 'price_targets' not in corrected_data:
            corrected_data['price_targets'] = {}
        
        for period in ['m3', 'm6', 'm12']:
            expected = fixed_numbers['targets'][period]
            
            if period not in corrected_data['price_targets']:
                corrected_data['price_targets'][period] = {}
            
            actual = corrected_data['price_targets'][period]
            
            # Check price
            if actual.get('price') != expected['price']:
                report["corrections_made"].append(
                    f"{period} price: {actual.get('price')} → {expected['price']}"
                )
                corrected_data['price_targets'][period]['price'] = expected['price']
                corrections_needed = True
            
            # Check range_low
            if actual.get('range_low') != expected['range_low']:
                report["corrections_made"].append(
                    f"{period} range_low: {actual.get('range_low')} → {expected['range_low']}"
                )
                corrected_data['price_targets'][period]['range_low'] = expected['range_low']
                corrections_needed = True
            
            # Check range_high
            if actual.get('range_high') != expected['range_high']:
                report["corrections_made"].append(
                    f"{period} range_high: {actual.get('range_high')} → {expected['range_high']}"
                )
                corrected_data['price_targets'][period]['range_high'] = expected['range_high']
                corrections_needed = True
        
        return corrected_data if corrections_needed else None
    
    def _validate_evidence_citations(
        self,
        response_data: Dict[str, Any],
        valid_evidence_ids: Set[str],
        report: Dict[str, Any]
    ) -> List[str]:
        """
        Check that all cited evidence IDs exist in evidence pack.
        Returns list of invalid IDs.
        """
        # Collect all text fields to check
        text_fields = [
            response_data.get('thesis', ''),
            response_data.get('valuation_perspective', '')
        ]
        
        # Add price target drivers
        for period in ['m3', 'm6', 'm12']:
            driver = response_data.get('price_targets', {}).get(period, {}).get('driver', '')
            text_fields.append(driver)
        
        # Add catalysts
        for cat in response_data.get('catalysts', []):
            if isinstance(cat, dict):
                text_fields.append(cat.get('statement', ''))
            else:
                text_fields.append(str(cat))
        
        # Add risks
        for risk in response_data.get('risks', []):
            if isinstance(risk, dict):
                text_fields.append(risk.get('statement', ''))
            else:
                text_fields.append(str(risk))
        
        # Add scenarios
        scenarios = response_data.get('scenarios', {})
        for scenario_type in ['bull', 'base', 'bear']:
            scenario = scenarios.get(scenario_type, {})
            if isinstance(scenario, dict):
                text_fields.append(scenario.get('narrative', ''))
        
        # Add action
        action = response_data.get('action', {})
        if isinstance(action, dict):
            text_fields.append(action.get('buyers', ''))
            text_fields.append(action.get('holders', ''))
        
        # Add monitoring plan
        for item in response_data.get('monitoring_plan', []):
            text_fields.append(str(item))
        
        # Find all cited evidence IDs
        cited_ids = set()
        for text in text_fields:
            matches = self.EVIDENCE_PATTERN.findall(text)
            cited_ids.update([f"E{m}" for m in matches])
        
        # Find invalid IDs
        invalid_ids = cited_ids - valid_evidence_ids
        
        if invalid_ids:
            report["errors"].append(
                f"Invalid evidence IDs: {sorted(invalid_ids)}"
            )
        
        return sorted(invalid_ids)
    
    def _check_citation_coverage(
        self,
        response_data: Dict[str, Any],
        valid_evidence_ids: Set[str],
        report: Dict[str, Any]
    ) -> float:
        """
        Check what percentage of material sentences have citations.
        Returns coverage percentage.
        
        Checks ALL text fields:
        - thesis
        - valuation_perspective
        - price_targets.m3/m6/m12.driver
        - catalysts[].statement
        - risks[].statement
        - scenarios.bull/base/bear.narrative
        """
        # Collect sentences from ALL key fields
        key_texts = []
        
        # Core narrative fields
        key_texts.append(response_data.get('thesis', ''))
        key_texts.append(response_data.get('valuation_perspective', ''))
        
        # Price target drivers (often missed!)
        price_targets = response_data.get('price_targets', {})
        for period in ['m3', 'm6', 'm12']:
            driver = price_targets.get(period, {}).get('driver', '')
            if driver:
                key_texts.append(driver)
        
        # Catalyst statements
        catalysts = response_data.get('catalysts', [])
        for cat in catalysts:
            if isinstance(cat, dict):
                stmt = cat.get('statement', '')
            else:
                stmt = str(cat)
            if stmt:
                key_texts.append(stmt)
        
        # Risk statements
        risks = response_data.get('risks', [])
        for risk in risks:
            if isinstance(risk, dict):
                stmt = risk.get('statement', '')
            else:
                stmt = str(risk)
            if stmt:
                key_texts.append(stmt)
        
        # Scenario narratives
        scenarios = response_data.get('scenarios', {})
        for scenario_type in ['bull', 'base', 'bear']:
            scenario = scenarios.get(scenario_type, {})
            if isinstance(scenario, dict):
                narrative = scenario.get('narrative', '')
                if narrative:
                    key_texts.append(narrative)
        
        # Extract sentences from all collected texts
        sentences = []
        for text in key_texts:
            if text:
                # Split by sentence boundaries (handles U.S., Inc., etc.)
                text_sentences = re.split(self.SENTENCE_PATTERN, text)
                # Clean and filter empty strings
                text_sentences = [s.strip() for s in text_sentences if s.strip()]
                sentences.extend(text_sentences)
        
        # Filter to material sentences
        # Criteria: >= 4 words AND (has factual claim keywords OR mentions specific entities)
        material_sentences = []
        factual_keywords = [
            'revenue', 'growth', 'earnings', 'sales', 'margin', 'profit',
            'risk', 'catalyst', 'competitive', 'regulatory', 'launch', 'product',
            'will', 'could', 'expected', 'anticipated', 'indicates', 'suggests',
            'shows', 'driven', 'quarter', 'year', 'increase', 'decrease',
            'strong', 'weak', 'high', 'low', 'impact', 'potential', 'likely'
        ]
        
        for sent in sentences:
            sent_clean = sent.strip()
            word_count = len(sent_clean.split())
            
            # Skip very short sentences (connectors like "However,")
            if word_count < 4:
                continue
            
            sent_lower = sent_clean.lower()
            
            # Skip self-referential statements about the recommendation's own calculations
            # These don't need evidence citations
            self_ref_patterns = [
                'the current price',
                'priced at',
                'price target',
                'expected return',
                'the base case',
                'the bull case',
                'the bear case',
                'scenario aligns',
                'target of $',
                'target reflects',
                'p/e ratio is',
                'p/e ratio of',
                'pe ratio is',
                'pe ratio of',
                'current p/e',
                'current pe',
                'not applicable'
            ]
            
            is_self_ref = any(pattern in sent_lower for pattern in self_ref_patterns)
            if is_self_ref:
                continue
            
            # Check if sentence has factual claim
            has_claim = any(keyword in sent_lower for keyword in factual_keywords)
            
            # Also include sentences with numbers, percentages, dollar amounts
            has_numbers = any(char.isdigit() for char in sent_clean)
            
            if has_claim or has_numbers:
                material_sentences.append(sent_clean)
        
        if not material_sentences:
            report["coverage_details"] = {
                "material_sentences": 0,
                "cited_sentences": 0,
                "coverage_pct": 100.0
            }
            return 100.0  # No material claims to cite
        
        # Count cited sentences and track which ones lack citations
        cited_count = 0
        uncited_sentences = []
        cited_sentences = []
        
        for sent in material_sentences:
            if self.EVIDENCE_PATTERN.search(sent):
                cited_count += 1
                cited_sentences.append(sent)
            else:
                uncited_sentences.append(sent)
        
        coverage = (cited_count / len(material_sentences)) * 100
        
        report["coverage_details"] = {
            "material_sentences": len(material_sentences),
            "cited_sentences": cited_count,
            "coverage_pct": coverage,
            "uncited_sentences": uncited_sentences[:10],  # Show first 10 for debugging
            "cited_sentences": cited_sentences[:5]  # Show first 5 examples
        }
        
        return coverage
    
    def _check_unsupported_claims(
        self,
        response_data: Dict[str, Any],
        evidence_pack: Dict[str, Any],
        report: Dict[str, Any]
    ) -> List[str]:
        """
        Check for specific unsupported claims.
        Returns list of warnings about unsupported claims.
        """
        warnings = []
        
        # Extract all evidence snippets for content checking
        evidence_content = ' '.join([
            ev.get('snippet', '') + ' ' + ev.get('reasoning', '')
            for ev in evidence_pack.get('evidence', [])
        ]).lower()
        
        # Check thesis for unsupported specific figures
        thesis = response_data.get('thesis', '')
        
        # Common unsupported claim patterns
        unsupported_patterns = [
            (r'\$\d+\.?\d*\s*billion', 'specific dollar amounts'),
            (r'\d+%\s+(?:growth|increase|decrease)', 'specific percentage changes'),
            (r'(?:strong|weak|healthy)\s+(?:pre-order|demand)', 'demand claims without evidence'),
        ]
        
        for pattern, claim_type in unsupported_patterns:
            matches = re.finditer(pattern, thesis, re.IGNORECASE)
            for match in matches:
                matched_text = match.group()
                # Check if this appears in evidence
                if matched_text.lower() not in evidence_content:
                    warnings.append(
                        f"Potentially unsupported {claim_type}: '{matched_text}'"
                    )
        
        return warnings
    
    def needs_rewrite(self, validation_report: Dict[str, Any]) -> bool:
        """
        Check if LLM needs to rewrite text due to corrections.
        PRODUCTION STANDARD: Trigger rewrite if:
        - Auto-corrections applied
        - Any validation errors
        - Coverage below 95%
        """
        return (
            validation_report.get("auto_corrected", False) or
            len(validation_report.get("errors", [])) > 0 or
            validation_report.get("coverage_details", {}).get("coverage_pct", 100) < 95.0
        )
    
    def get_uncited_sentences(self, validation_report: Dict[str, Any]) -> List[str]:
        """
        Get list of sentences that lack citations.
        Useful for targeted rewrite feedback.
        """
        return validation_report.get("coverage_details", {}).get("uncited_sentences", [])
