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
from typing import Any, Dict, Iterator, List, Optional, Set, Tuple

# The evidence item the engine builds from its own deterministic outputs (the
# rating, the fair value and its range, the price at the run, the implied
# return, the confidence alert) and provider market data. A sentence that
# restates VYNN's figures cites it, and is checked against its text like any
# news claim against its source.
MODEL_EVIDENCE_ID = "E0"
RATING_LABELS = re.compile(r"\b(strong\s+buy|strong\s+sell|buy|sell|hold)\b", re.IGNORECASE)


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

    # Generic investment-language overlap does not prove that a source
    # supports a claim. These terms are removed before checking semantic
    # overlap so an unrelated article containing "growth" and "risk" cannot
    # launder a sentence through a valid [E#] token.
    _SUPPORT_STOPWORDS = {
        "about", "after", "again", "against", "also", "and", "because",
        "been", "before", "being", "between", "both", "business", "but",
        "catalyst", "company", "could", "current", "driver", "earnings",
        "from", "growth", "have", "into", "investment", "likely", "market",
        "more", "price", "rating", "revenue", "risk", "should", "stock",
        "target", "than", "that", "their", "there", "these", "they", "this",
        "through", "valuation", "were", "will", "with", "would", "year",
    }
    
    def validate_and_correct(
        self,
        llm_response: str,
        fixed_numbers: Dict[str, Any],
        evidence_pack: Dict[str, Any],
        rejected_claims: Optional[Set[str]] = None,
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """
        Validate LLM response and auto-correct if needed.

        `rejected_claims`: cited sentences an earlier attempt failed on. One
        that comes back with only its citation removed is still an uncited
        claim, in whichever printed field it stands.
        
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

        # Citation enforcement only makes sense when there is evidence to cite.
        # With an empty pack (no news for the ticker) every [E#] the model was
        # prompted into writing is unfixable — enforcing would send the rewrite
        # loop on an impossible task and fail the whole report. Bypass instead:
        # strip the citations, keep the numbers, deliver the report annotated.
        citation_enforcement = bool(valid_evidence_ids)
        validation_report["evidence_available"] = citation_enforcement
        if not citation_enforcement:
            validation_report["citation_enforcement_bypassed"] = True

        # 1. Validate and correct numeric fields
        numeric_corrections = self._validate_numbers(
            response_data,
            fixed_numbers,
            validation_report
        )

        if numeric_corrections:
            response_data = numeric_corrections
            validation_report["auto_corrected"] = True

        # Citation percentages are meaningless when the response contains no
        # report. Validate the required narrative shape before allowing an
        # empty object to score 100% on a zero-sentence denominator.
        structure_issues = self._validate_structure(
            response_data, fixed_numbers, evidence_pack
        )
        if structure_issues:
            validation_report["structure_issues"] = structure_issues
            validation_report["errors"].append(
                "Recommendation output is incomplete: "
                + "; ".join(structure_issues)
            )
            validation_report["valid"] = False

        # 2. Validate evidence citations
        invalid_citations = self._validate_evidence_citations(
            response_data,
            valid_evidence_ids
        )

        if invalid_citations:
            if citation_enforcement:
                validation_report["errors"].append(
                    f"Invalid evidence IDs cited: {invalid_citations}"
                )
                validation_report["valid"] = False
            else:
                response_data, removed = self.strip_citations(
                    response_data, valid_evidence_ids
                )
                validation_report["warnings"].append(
                    f"No news evidence available; removed {removed} fabricated citation(s)"
                )
                validation_report["corrections_made"].append(
                    f"Removed {removed} invalid citation(s) (no evidence pack)"
                )

        # A citation ID being real is necessary, not sufficient. Check that
        # every sentence carrying [E#] has actual topical or numeric support in
        # the cited evidence. This catches citation laundering: attaching an
        # unrelated but valid headline to a confident claim.
        support_issues = self._validate_citation_support(
            response_data, evidence_pack, fixed_numbers)
        if citation_enforcement and support_issues:
            validation_report["errors"].append(
                f"{len(support_issues)} cited claim(s) are not supported by their evidence"
            )
            # The rewrite is shown each one: given a count alone, it left the
            # same claims standing through all three attempts.
            validation_report["citation_support_issues"] = support_issues[:25]
            validation_report["valid"] = False

        # 3. Check citation coverage
        coverage = self._check_citation_coverage(
            response_data,
            valid_evidence_ids,
            validation_report,
            fixed_numbers,
            rejected_claims,
        )

        # PRODUCTION REQUIREMENT: 95% minimum coverage (only meaningful when
        # there is evidence available to cite)
        if citation_enforcement and coverage < 95.0:
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

    @staticmethod
    def _validate_structure(
        response_data: Dict[str, Any],
        fixed_numbers: Dict[str, Any],
        evidence_pack: Dict[str, Any],
    ) -> List[str]:
        """Reject vacuous but syntactically valid recommendation payloads."""
        data = response_data if isinstance(response_data, dict) else {}
        issues: List[str] = []

        thesis = data.get("thesis")
        if not isinstance(thesis, str) or len(thesis.strip()) < 20:
            issues.append("investment thesis is missing")

        evidence = [
            item for item in (evidence_pack or {}).get("evidence", [])
            if isinstance(item, dict)
        ]
        has_catalyst_evidence = any(
            str(item.get("type") or "").startswith("catalyst_")
            for item in evidence
        )
        has_risk_evidence = any(
            str(item.get("type") or "").startswith("risk_")
            for item in evidence
        )

        def has_statement(rows: Any) -> bool:
            return isinstance(rows, list) and any(
                isinstance(row, dict)
                and isinstance(row.get("statement"), str)
                and len(row["statement"].strip()) >= 10
                for row in rows
            )

        if has_catalyst_evidence and not has_statement(data.get("catalysts")):
            issues.append("source-backed catalysts are not summarized")
        if has_risk_evidence and not has_statement(data.get("risks")):
            issues.append("source-backed risks are not summarized")

        if evidence:
            scenarios = data.get("scenarios")
            scenarios = scenarios if isinstance(scenarios, dict) else {}
            missing_scenarios = [
                name for name in ("bull", "base", "bear")
                if not isinstance(scenarios.get(name), dict)
                or not isinstance(scenarios[name].get("narrative"), str)
                or len(scenarios[name]["narrative"].strip()) < 10
            ]
            if missing_scenarios:
                issues.append(
                    "scenario narratives are missing: "
                    + ", ".join(missing_scenarios)
                )
            monitoring = data.get("monitoring_plan")
            if not isinstance(monitoring, list) or not any(
                isinstance(item, str) and len(item.strip()) >= 10
                for item in monitoring
            ):
                issues.append("monitoring plan is missing")

        return issues

    @classmethod
    def _support_tokens(cls, text: str) -> Set[str]:
        tokens = set()
        for token in re.findall(r"[A-Za-z][A-Za-z0-9'-]{2,}", text or ""):
            token = token.lower().replace("’", "'").strip("'")
            if token.endswith("'s"):
                token = token[:-2]
            # A light stem catches stabilize/stabilized and launch/launches
            # without introducing an NLP dependency into the safety boundary.
            for suffix in ("ingly", "edly", "ation", "ments", "ment", "ies", "ing", "ed", "es", "s"):
                if token.endswith(suffix) and len(token) - len(suffix) >= 4:
                    token = token[:-len(suffix)]
                    break
            if len(token) >= 4 and token not in cls._SUPPORT_STOPWORDS:
                tokens.add(token)
        return tokens

    @staticmethod
    def _support_numbers(text: str) -> Set[str]:
        normalized = set()
        for value in re.findall(r"(?<![A-Za-z])[-+]?\d[\d,]*(?:\.\d+)?", text or ""):
            value = value.replace(",", "")
            if "." in value:
                value = value.rstrip("0").rstrip(".")
            normalized.add(value)
        return normalized

    @classmethod
    def _citation_supported(
        cls, sentence: str, cited_ids: Set[str], evidence_by_id: Dict[str, Dict[str, Any]],
    ) -> bool:
        return cls._support_failure(sentence, cited_ids, evidence_by_id) is None

    @classmethod
    def _support_failure(
        cls, sentence: str, cited_ids: Set[str], evidence_by_id: Dict[str, Dict[str, Any]],
        subject: Optional[Set[str]] = None, rating: Optional[str] = None,
    ) -> Optional[str]:
        """Why the cited text does not support the sentence, or None.

        Main's check, unchanged, plus two things that only make it stricter:
        the company's own name is never wording a source shares with a claim
        (every article about Microsoft says "Microsoft", and at nine letters
        it carried any claim alone), and a sentence citing the model item E0
        must state one of its figures or its rating, name no other rating,
        use no word its cited sources do not, and negate nothing they do not.
        E0 is the engine's own text, so a restatement needs no other word;
        "VYNN's fair value implies 33% upside [E0]" (the model says 33%
        downside) and "VYNN's fair value is not 33% below the market price
        [E0]" share every other word with it.
        """
        evidence = " ".join(
            " ".join(str(item.get(field) or "") for field in (
                # ``title`` is the upstream LLM's derived insight and
                # ``reasoning`` is its interpretation.  Treating either as
                # source evidence made citation validation tautological.  Only
                # the actual publisher headline/excerpt can support a claim.
                "source_article_title", "snippet",
            ))
            for evidence_id in cited_ids
            for item in [evidence_by_id.get(evidence_id) or {}]
        )
        if not evidence.strip():
            return "the cited item has no source text"
        claim = cls.EVIDENCE_PATTERN.sub("", sentence)
        claim_numbers = cls._support_numbers(claim)
        evidence_numbers = cls._support_numbers(evidence)
        if claim_numbers and not claim_numbers.issubset(evidence_numbers):
            missing = ", ".join(sorted(claim_numbers - evidence_numbers))
            return f"{missing} is not in the cited source"
        overlap = (cls._support_tokens(claim).intersection(cls._support_tokens(evidence))
                   - (subject or set()))
        if MODEL_EVIDENCE_ID in cited_ids:
            labels = {" ".join(label.lower().split()) for label in RATING_LABELS.findall(claim)}
            fixed = " ".join(str(rating or "").lower().split())
            if labels - {fixed}:
                return f"it names a rating ({', '.join(sorted(labels - {fixed}))}) that {MODEL_EVIDENCE_ID} does not"
            model_numbers = cls._support_numbers(" ".join(
                str((evidence_by_id.get(MODEL_EVIDENCE_ID) or {}).get(field) or "")
                for field in ("source_article_title", "snippet")))
            if not (claim_numbers & model_numbers) and not (fixed and fixed in labels):
                return f"it states none of {MODEL_EVIDENCE_ID}'s figures or its rating"
            novel = cls._support_tokens(claim) - cls._support_tokens(evidence) - (subject or set())
            if novel:
                # The words as written, not their stems: "lists, states", not
                # "list, stat", or the rewrite swaps one framing verb for another.
                written = []
                for word in re.findall(r"[A-Za-z][A-Za-z0-9'’-]{2,}", claim):
                    if cls._support_tokens(word) & novel and word.lower() not in written:
                        written.append(word.lower())
                return (f"it adds words {MODEL_EVIDENCE_ID} does not use ({', '.join(written)}): "
                        f"write the figures in {MODEL_EVIDENCE_ID}'s own words, with no framing "
                        f"of your own")
            # "not" is too short to be a token, and E0 itself says "not news":
            # a negation must stand in the cited text before the same word.
            def pairs(text):
                words = re.findall(r"[a-z0-9.%$]+", text.lower().replace("n't", " not"))
                return {(a, b) for a, b in zip(words, words[1:]) if a in cls._NEGATIONS}
            negated = pairs(claim) - pairs(evidence)
            if negated:
                return ("it negates what the cited sources do not: "
                        + ", ".join(" ".join(pair) for pair in sorted(negated)))
        if len(overlap) >= 2 or any(len(token) >= 7 for token in overlap):
            return None
        return "its wording is not what the cited source says"

    _NEGATIONS = {"not", "no", "never", "neither", "nor", "without"}

    @classmethod
    def _subject_tokens(cls, evidence_pack: Any, fixed_numbers: Any) -> Set[str]:
        """The company's own name and ticker, from the pack the engine labels."""
        subject = (evidence_pack or {}).get("subject") if isinstance(evidence_pack, dict) else None
        subject = subject if isinstance(subject, dict) else {}
        name = subject.get("name") if isinstance(subject.get("name"), str) else ""
        ticker = str(subject.get("ticker") or (fixed_numbers or {}).get("ticker") or "")
        corporate = {"inc", "incorporated", "corp", "corporation", "company", "holding",
                     "holdings", "group", "limited", "plc", "ltd", "the", "and"}
        words = [w for w in re.findall(r"[A-Za-z][A-Za-z']*", f"{name} {ticker.split('.')[0]}")
                 if w.lower() not in corporate]
        return cls._support_tokens(" ".join(words))

    def _validate_citation_support(
        self, response_data: Dict[str, Any], evidence_pack: Dict[str, Any],
        fixed_numbers: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        evidence_by_id = {
            str(item.get("id")): item
            for item in (evidence_pack or {}).get("evidence", [])
            if isinstance(item, dict) and item.get("id")
        }
        if not evidence_by_id:
            return []
        subject = self._subject_tokens(evidence_pack, fixed_numbers)
        rating = (fixed_numbers or {}).get("rating")
        issues = []
        for field, text in self._all_text_with_paths(response_data):
            for sentence in re.split(self.SENTENCE_PATTERN, text or ""):
                cited = {f"E{number}" for number in self.EVIDENCE_PATTERN.findall(sentence)}
                if not cited or not cited.issubset(evidence_by_id):
                    continue
                reason = self._support_failure(sentence, cited, evidence_by_id, subject, rating)
                if reason:
                    issues.append({
                        "claim": sentence.strip()[:300],
                        "citations": sorted(cited),
                        "field": field,
                        "reason": reason,
                    })
        return issues

    def strip_unsupported_citations(
        self, response_data: Dict[str, Any], evidence_pack: Dict[str, Any],
    ) -> Tuple[Dict[str, Any], int]:
        """Remove citations that fail support validation after rewrite attempts."""
        evidence_by_id = {
            str(item.get("id")): item
            for item in (evidence_pack or {}).get("evidence", [])
            if isinstance(item, dict) and item.get("id")
        }
        removed = 0

        def clean(text: str) -> str:
            nonlocal removed
            pieces = re.split(r"(?<=[.!?])(?=\s|$)", text)
            cleaned = []
            for piece in pieces:
                cited = {f"E{number}" for number in self.EVIDENCE_PATTERN.findall(piece)}
                if cited and not self._citation_supported(piece, cited, evidence_by_id):
                    count = len(self.EVIDENCE_PATTERN.findall(piece))
                    piece = self.EVIDENCE_PATTERN.sub("", piece)
                    piece = re.sub(r" {2,}", " ", piece)
                    piece = re.sub(r"\s+([.,;:!?])", r"\1", piece)
                    removed += count
                cleaned.append(piece)
            return "".join(cleaned).strip()

        def walk(node):
            if isinstance(node, dict):
                return {key: walk(value) for key, value in node.items()}
            if isinstance(node, list):
                return [walk(value) for value in node]
            if isinstance(node, str):
                return clean(node)
            return node

        return walk(response_data), removed

    @staticmethod
    def _all_text(response_data: Dict[str, Any]) -> List[str]:
        values = []

        def walk(node):
            if isinstance(node, dict):
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for value in node:
                    walk(value)
            elif isinstance(node, str):
                values.append(node)

        walk(response_data or {})
        return values

    @staticmethod
    def _all_text_with_paths(response_data: Dict[str, Any]) -> Iterator[Tuple[str, str]]:
        """Every string field with its path ("scenarios.bear.watch[0]")."""
        def walk(node, path):
            if isinstance(node, dict):
                for key, value in node.items():
                    yield from walk(value, f"{path}.{key}" if path else str(key))
            elif isinstance(node, list):
                for index, value in enumerate(node):
                    yield from walk(value, f"{path}[{index}]")
            elif isinstance(node, str):
                yield path, node

        yield from walk(response_data or {}, "")

    @classmethod
    def claim_key(cls, sentence: str) -> str:
        """A sentence without its citations, for exact comparison across attempts."""
        text = cls.EVIDENCE_PATTERN.sub("", sentence or "")
        return " ".join(text.split()).strip().rstrip(".;:").strip().lower()

    @staticmethod
    def engine_driver(fixed_numbers: Dict[str, Any]) -> str:
        """The 12-month driver the engine writes itself: the target assumption.

        The report never prints a driver. The model was asked to explain the
        convergence basis there and its sentence ("the published intrinsic
        value under an explicit 12-month convergence assumption") failed
        citation coverage in all 16 captured attempts.
        """
        return str((fixed_numbers or {}).get("target_assumption") or (
            "The 12-month case assumes convergence to the currently published "
            "intrinsic value; it is not a statistically forecast market price."))
    
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
        # Corrections the prose may now contradict (a rating or a price it
        # restated). The engine's own texts (valuation perspective, 12-month
        # driver) replace whatever the model wrote there on every response and
        # leave nothing else stale, so they alone never force a rewrite.
        narrative = report.setdefault("narrative_corrections", [])

        reliability = (fixed_numbers.get('inputs') or {}).get(
            'valuation_reliability') or {}
        if not fixed_numbers.get('rating_available', True):
            deterministic_perspective = (
                "No single fair value, directional rating or price target is "
                "stated for this run. "
                + str(fixed_numbers.get('rating_withheld_reason') or (
                    reliability.get('withheld_reason')
                    or "The valuation evidence does not support a defensible point call."
                )).strip().rstrip('.')
                + ". The published range contains model-method outputs, not "
                "probabilistic bull/base/bear targets."
            )
        else:
            deterministic_perspective = (
                "The published rating, target, and expected return are deterministic "
                "calculator outputs. Analyst consensus is an external benchmark and "
                "is not averaged into intrinsic value."
            )
        if corrected_data.get('valuation_perspective') != deterministic_perspective:
            corrected_data['valuation_perspective'] = deterministic_perspective
            report["corrections_made"].append(
                "valuation perspective replaced with deterministic methodology text"
            )
            corrections_needed = True
        
        # 1. Check rating
        if response_data.get('rating') != fixed_numbers['rating']:
            correction = (
                f"Rating corrected: {response_data.get('rating')} → {fixed_numbers['rating']}"
            )
            report["corrections_made"].append(correction)
            narrative.append(correction)
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

            if expected.get('price') is None and actual.get('driver'):
                report["corrections_made"].append(
                    f"{period} driver removed because no target is publishable"
                )
                corrected_data['price_targets'][period]['driver'] = ''
                corrections_needed = True
            elif expected.get('price') is not None and \
                    actual.get('driver') != self.engine_driver(fixed_numbers):
                report["corrections_made"].append(f"{period} driver set to the target assumption")
                corrected_data['price_targets'][period]['driver'] = self.engine_driver(fixed_numbers)
                corrections_needed = True
            
            # Check price
            if actual.get('price') != expected['price']:
                correction = f"{period} price: {actual.get('price')} → {expected['price']}"
                report["corrections_made"].append(correction)
                narrative.append(correction)
                corrected_data['price_targets'][period]['price'] = expected['price']
                corrections_needed = True
            
            # Check range_low
            if actual.get('range_low') != expected['range_low']:
                correction = (
                    f"{period} range_low: {actual.get('range_low')} → {expected['range_low']}"
                )
                report["corrections_made"].append(correction)
                narrative.append(correction)
                corrected_data['price_targets'][period]['range_low'] = expected['range_low']
                corrections_needed = True
            
            # Check range_high
            if actual.get('range_high') != expected['range_high']:
                correction = (
                    f"{period} range_high: {actual.get('range_high')} → {expected['range_high']}"
                )
                report["corrections_made"].append(correction)
                narrative.append(correction)
                corrected_data['price_targets'][period]['range_high'] = expected['range_high']
                corrections_needed = True
        
        return corrected_data if corrections_needed else None
    
    def _validate_evidence_citations(
        self,
        response_data: Dict[str, Any],
        valid_evidence_ids: Set[str]
    ) -> List[str]:
        """
        Check that all cited evidence IDs exist in evidence pack.
        Returns list of invalid IDs (the caller decides error vs. bypass).
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

        return sorted(invalid_ids)

    def strip_citations(
        self,
        response_data: Dict[str, Any],
        valid_evidence_ids: Set[str]
    ) -> Tuple[Dict[str, Any], int]:
        """
        Remove every [E#] token whose ID is not in valid_evidence_ids from all
        string fields, recursively. Walking the whole tree (rather than the
        field list in _validate_evidence_citations) guarantees no dangling
        citation survives in any field the report might print.

        Returns (cleaned_data, removed_count).
        """
        removed = 0

        def clean(text: str) -> str:
            nonlocal removed

            def repl(match):
                nonlocal removed
                if f"E{match.group(1)}" in valid_evidence_ids:
                    return match.group(0)
                removed += 1
                return ""

            out = self.EVIDENCE_PATTERN.sub(repl, text)
            if out != text:
                # Tidy the whitespace holes the removals leave behind
                out = re.sub(r' {2,}', ' ', out)
                out = re.sub(r'\s+([.,;:!?])', r'\1', out)
                out = out.strip()
            return out

        def walk(node):
            if isinstance(node, dict):
                return {k: walk(v) for k, v in node.items()}
            if isinstance(node, list):
                return [walk(v) for v in node]
            if isinstance(node, str):
                return clean(node)
            return node

        return walk(response_data), removed
    
    def _check_citation_coverage(
        self,
        response_data: Dict[str, Any],
        valid_evidence_ids: Set[str],
        report: Dict[str, Any],
        fixed_numbers: Optional[Dict[str, Any]] = None,
        rejected_claims: Optional[Set[str]] = None,
    ) -> float:
        """
        Check what percentage of material sentences have citations.
        Returns coverage percentage.
        
        Checks:
        - thesis
        - price_targets.m3/m6/m12.driver
        - catalysts[].statement
        - risks[].statement
        - scenarios.bull/base/bear.narrative
        - every printed watch, monitoring and action item that states a
          figure or a date: a source (a news item, or E0 for VYNN's own
          figures) must give it

        Every sentence counts unless it is text the engine wrote itself (the
        12-month driver), matched exactly. No phrase excuses a sentence: "The
        bear case reflects Apple losing its appeal" is a claim, and a sentence
        restating VYNN's figures cites E0.
        """
        engine_sentences = {
            sentence.strip()
            for text in (self.engine_driver(fixed_numbers or {}),)
            for sentence in re.split(self.SENTENCE_PATTERN, text)
            if sentence.strip()
        }
        # Collect sentences from ALL key fields
        key_texts = []
        
        # Core news narrative. Valuation perspective is validated against the
        # deterministic FixedNumbers contract; news citations cannot support a
        # DCF range, publication boundary, or model-derived target.
        key_texts.append(response_data.get('thesis', ''))
        
        # Price target drivers (often missed!)
        price_targets = response_data.get('price_targets', {})
        for period in ['m3', 'm6', 'm12']:
            target_row = price_targets.get(period, {}) or {}
            driver = target_row.get('driver', '') if target_row.get('price') is not None else ''
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

        # Printed items to monitor and act on: counted only when they state a
        # figure or a date. "Next quarterly results" needs no source; "the
        # earnings call on October 30, 2026" does.
        items = []
        for scenario_type in ['bull', 'base', 'bear']:
            scenario = scenarios.get(scenario_type, {})
            if isinstance(scenario, dict):
                items.extend(str(item) for item in scenario.get('watch') or [])
        action = response_data.get('action', {})
        if isinstance(action, dict):
            items.extend(str(action.get(key) or '') for key in ('buyers', 'holders'))
            items.extend(str(item) for item in action.get('watch') or [])
        items.extend(str(item) for item in response_data.get('monitoring_plan', []) or [])
        item_sentences = [
            sentence.strip()
            for text in items
            for sentence in re.split(self.SENTENCE_PATTERN, text or "")
            if sentence.strip()
            and self._support_numbers(self.EVIDENCE_PATTERN.sub("", sentence))
        ]
        
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
            # Text the engine wrote, matched exactly, is not the model's claim.
            if sent_clean in engine_sentences:
                continue
            
            sent_lower = sent_clean.lower()
            
            # Check if sentence has factual claim
            has_claim = any(keyword in sent_lower for keyword in factual_keywords)
            
            # Also include sentences with numbers, percentages, dollar amounts
            has_numbers = any(char.isdigit() for char in sent_clean)
            
            if has_claim or has_numbers:
                material_sentences.append(sent_clean)

        material_sentences.extend(
            sentence for sentence in item_sentences if len(sentence.split()) >= 4)

        # A sentence an earlier attempt cited and failed on, back with only its
        # citation removed, is the same claim uncited: in any printed field,
        # figure or not. Matched exactly once citations are stripped.
        if rejected_claims:
            rejected = {self.claim_key(claim) for claim in rejected_claims}
            for text in key_texts + items:
                for sentence in re.split(self.SENTENCE_PATTERN, text or ""):
                    sentence = sentence.strip()
                    if (sentence and sentence not in engine_sentences
                            and not self.EVIDENCE_PATTERN.search(sentence)
                            and self.claim_key(sentence) in rejected
                            and sentence not in material_sentences):
                        material_sentences.append(sentence)
        
        if not material_sentences:
            report["coverage_details"] = {
                "material_sentences": 0,
                "cited_sentences": [],
                "cited_count": 0,
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
            # The count has its own key: "cited_sentences" below holds the
            # example sentences (it once held both, and the list won).
            "cited_count": cited_count,
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
            ev.get('snippet', '')
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
        - A correction the prose may contradict (rating, prices)
        - Any validation errors
        - Coverage below 95%

        When citation enforcement was bypassed (no evidence pack), a rewrite
        can never improve the situation — numeric fixes are already applied
        in-code and there are no valid IDs the model could cite.
        """
        if validation_report.get("structure_issues"):
            return True
        if validation_report.get("citation_enforcement_bypassed"):
            return False
        return (
            bool(validation_report.get("narrative_corrections")) or
            len(validation_report.get("errors", [])) > 0 or
            validation_report.get("coverage_details", {}).get("coverage_pct", 100) < 95.0
        )
    
    def get_uncited_sentences(self, validation_report: Dict[str, Any]) -> List[str]:
        """
        Get list of sentences that lack citations.
        Useful for targeted rewrite feedback.
        """
        return validation_report.get("coverage_details", {}).get("uncited_sentences", [])
