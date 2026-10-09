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

from src.model_statements import bind_numbers, is_model_statement, model_facts, subject_names


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

        # The prose may not name a rating the calculator did not set: "We rate
        # Apple a BUY." under a fixed STRONG SELL. The Street's own rating
        # ("53 analysts rate it STRONG BUY") is not VYNN's and is left alone.
        conflicts = self._prose_rating_conflicts(response_data, fixed_numbers)
        if conflicts:
            validation_report["errors"].append(
                f"{len(conflicts)} sentence(s) name a rating other than the fixed "
                f"{fixed_numbers.get('rating')}: "
                + "; ".join(json.dumps(sentence) for sentence in conflicts[:5])
            )
            validation_report["valid"] = False

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
            # The rewrite is shown every one of these by field: a count alone
            # left the same claims standing through all three attempts.
            validation_report["citation_support_issues"] = support_issues[:25]
            validation_report["valid"] = False

        # 3. Check citation coverage
        coverage = self._check_citation_coverage(
            response_data,
            valid_evidence_ids,
            validation_report,
            fixed_numbers,
            evidence_pack,
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

    # A compound the claim hyphenates ("free-cash-flow") is joined into one
    # token. It matches the same hyphenated compound in the source as before
    # (and, at seven letters or more, carries a claim alone as before), and
    # the source's own spaced words joined the same way ("free cash flow"),
    # but then only as one shared word: "long-term" against "long term" never
    # carries a claim by itself. A plain claim word never matches the spaced
    # source words joined ("slowdown" is not "slow down"). Validator only: the
    # article screener keeps its tokens.
    _HYPHENATED_WORD = re.compile(r"[A-Za-z][A-Za-z0-9']*(?:-[A-Za-z][A-Za-z0-9']*)+")
    _WORD = re.compile(r"[A-Za-z][A-Za-z0-9']*")
    _ISO_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")
    _MONTHS = (
        "january", "february", "march", "april", "may", "june", "july",
        "august", "september", "october", "november", "december",
    )

    @classmethod
    def _compounds(cls, text: str) -> Set[str]:
        tokens: Set[str] = set()
        for word in cls._HYPHENATED_WORD.findall(text or ""):
            tokens |= cls._support_tokens(word.replace("-", ""))
        return tokens

    @classmethod
    def _plain_tokens(cls, text: str) -> Set[str]:
        return cls._support_tokens(cls._HYPHENATED_WORD.sub(" ", text or ""))

    @classmethod
    def _joined_runs(cls, text: str) -> Set[str]:
        words = cls._WORD.findall(cls._HYPHENATED_WORD.sub(" ", text or ""))
        tokens: Set[str] = set()
        for size in (2, 3):
            for start in range(len(words) - size + 1):
                tokens |= cls._support_tokens("".join(words[start:start + size]))
        return tokens

    @classmethod
    def _date_numbers(cls, value: Any, claim: str) -> Set[str]:
        """The year and day of an evidence item's date that the claim writes as a date.

        The explainer is shown each item's date and told to state a date only
        when the evidence supplies it, so "reported on September 11, 2026
        [E2]" is supported by E2's date, not by its snippet. Only beside the
        item's own month's name ("September 11", "11 Sept. 2026", "September
        2026"): "$11 million" is not the 11th and "throughout 2026" is not a
        date the item gives. Numbers only, never shared wording.
        """
        match = cls._ISO_DATE.match(str(value or ""))
        if not match or not 1 <= int(match.group(2)) <= 12:
            return set()
        year, day = match.group(1), str(int(match.group(3)))
        name = cls._MONTHS[int(match.group(2)) - 1]
        month = rf"(?:{name}|{name[:3]}|{name[:4]})\.?"
        numbers: Set[str] = set()
        patterns = (
            rf"\b{month}\s+(?P<d>\d{{1,2}})(?:st|nd|rd|th)?\b(?:,?\s+(?P<y>\d{{4}})\b)?",
            rf"\b(?P<d>\d{{1,2}})(?:st|nd|rd|th)?\s+{month}(?:,?\s+(?P<y>\d{{4}})\b)?",
            rf"\b{month},?\s+(?P<y>\d{{4}})\b",
        )
        for pattern in patterns:
            for found in re.finditer(pattern, claim, re.IGNORECASE):
                groups = found.groupdict()
                if groups.get("d") and str(int(groups["d"])) == day:
                    numbers.add(day)
                if groups.get("y") == year:
                    numbers.add(year)
        return numbers

    @classmethod
    def _cited_source(
        cls, cited_ids: Set[str], evidence_by_id: Dict[str, Dict[str, Any]], claim: str = "",
    ) -> Tuple[str, Set[str]]:
        """The cited items' publisher text, and the numbers it supports."""
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
        numbers = cls._support_numbers(evidence)
        for evidence_id in cited_ids:
            numbers |= cls._date_numbers(
                (evidence_by_id.get(evidence_id) or {}).get("date"), claim)
        return evidence, numbers

    @staticmethod
    def _subject(evidence_pack: Any, fixed_numbers: Any) -> Tuple[Optional[str], Optional[str]]:
        """The company's name and ticker, from the pack the engine labels."""
        subject = (evidence_pack or {}).get("subject") if isinstance(evidence_pack, dict) else None
        subject = subject if isinstance(subject, dict) else {}
        name = subject.get("name") if isinstance(subject.get("name"), str) else None
        ticker = subject.get("ticker") or (fixed_numbers or {}).get("ticker")
        return (name if name and name.strip() and name != "N/A" else None), ticker

    @classmethod
    def _subject_tokens(cls, name: Optional[str], ticker: Any) -> Set[str]:
        """The company's own name as support tokens: never shared wording.

        Every article about Microsoft says "Microsoft", and at nine letters
        it carried any claim alone; with one topical word, "Apple" and
        "China" made "the figures show Apple will exit China" supported.
        """
        return cls._support_tokens(" ".join(sorted(subject_names(name, ticker, stem=False))))

    @classmethod
    def _beside_figure(cls, text: str, token: str, figures: Set[str], reach: int = 2) -> bool:
        """True when `token` stands within `reach` words of one of `figures`."""
        units = re.findall(r"[A-Za-z][A-Za-z0-9'’-]*|\d[\d,]*(?:\.\d+)?", text or "")
        word_at = [i for i, unit in enumerate(units) if token in cls._support_tokens(unit)]
        figure_at = [i for i, unit in enumerate(units)
                     if unit[0].isdigit() and cls._support_numbers(unit) & figures]
        return any(abs(w - f) <= reach for w in word_at for f in figure_at)

    @classmethod
    def _support_failure(
        cls, sentence: str, cited_ids: Set[str], evidence_by_id: Dict[str, Dict[str, Any]],
        subject: Optional[Set[str]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Why the cited publisher text does not support the sentence, or None."""
        claim = cls.EVIDENCE_PATTERN.sub("", sentence)
        evidence, evidence_numbers = cls._cited_source(cited_ids, evidence_by_id, claim)
        if not evidence.strip():
            return {"reason": "no_source_text"}
        claim_numbers = cls._support_numbers(claim)
        missing = sorted(claim_numbers - evidence_numbers)
        if missing:
            return {"reason": "numbers_not_in_source", "numbers": missing}
        subject = subject or set()
        plain = (cls._plain_tokens(claim) & cls._plain_tokens(evidence)) - subject
        claim_compounds = cls._compounds(claim)
        exact = claim_compounds & cls._compounds(evidence)
        spaced = (claim_compounds & cls._joined_runs(evidence)) - exact
        if len(plain | exact | spaced) >= 2 or any(len(token) >= 7 for token in plain | exact):
            return None
        # A data table shares few words with any sentence about it ("P/E Ratio
        # 345.73 EPS (TTM) $ 1.08"): two of its exact figures, each specific (a
        # decimal or three digits, not a year) and printed in the publisher
        # text itself, entail the sentence when they share a word that stands
        # beside one of them in both texts and is not the company's name
        # ("The 22.6% and 18.1% figures confirm Apple's antitrust exposure").
        specific = {
            number for number in claim_numbers & cls._support_numbers(evidence)
            if ("." in number or len(number.lstrip("+-")) >= 3)
            and not re.fullmatch(r"(?:19|20)\d\d", number)
        }
        if len(specific) >= 2 and any(
            cls._beside_figure(claim, token, specific)
            and cls._beside_figure(evidence, token, specific)
            for token in plain
        ):
            return None
        return {"reason": "wording_not_in_source"}

    @classmethod
    def _citation_supported(
        cls, sentence: str, cited_ids: Set[str], evidence_by_id: Dict[str, Dict[str, Any]],
    ) -> bool:
        return cls._support_failure(sentence, cited_ids, evidence_by_id) is None

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
        facts = model_facts(fixed_numbers)
        name, ticker = self._subject(evidence_pack, fixed_numbers)
        subject = self._subject_tokens(name, ticker)
        subject_stems = subject_names(name, None) if name else set()
        issues = []
        for field, text in self._all_text_with_paths(response_data):
            for sentence in re.split(self.SENTENCE_PATTERN, text or ""):
                cited = {f"E{number}" for number in self.EVIDENCE_PATTERN.findall(sentence)}
                if not cited or not cited.issubset(evidence_by_id):
                    continue
                failure = self._support_failure(sentence, cited, evidence_by_id, subject)
                if failure is None:
                    continue
                issue = {
                    "claim": sentence.strip()[:300],
                    "citations": sorted(cited),
                    "field": field,
                    **failure,
                }
                if failure["reason"] == "numbers_not_in_source":
                    claim = self.EVIDENCE_PATTERN.sub("", sentence)
                    bound, _ = bind_numbers(claim, facts)
                    if is_model_statement(claim, facts, subject_stems):
                        # Only VYNN's figures, which no news states: the
                        # sentence needs no citation, not a better one.
                        issue["reason"] = "model_figures_cited_to_news"
                    elif set(failure["numbers"]) & {n.replace(",", "") for n in bound}:
                        # News and VYNN's figures in one sentence: dropping
                        # the citation would leave the news claim uncited.
                        issue["reason"] = "news_mixed_with_model_figures"
                issues.append(issue)
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

    _RATING_IN_PROSE = re.compile(r"\b(STRONG BUY|STRONG SELL|BUY|SELL|HOLD)\b")
    _THIRD_PARTY = re.compile(
        r"\b(?:analysts?|street|consensus|finnhub|yahoo|brokers?|ratings|peers?)\b", re.I)

    def _prose_rating_conflicts(
        self, response_data: Dict[str, Any], fixed_numbers: Dict[str, Any],
    ) -> List[str]:
        rating = str((fixed_numbers or {}).get("rating") or "").strip()
        if not rating:
            return []
        conflicts = []
        for field, text in self._all_text_with_paths(response_data):
            if field in ("rating", "valuation_perspective") or field.startswith("price_targets"):
                continue
            for sentence in re.split(self.SENTENCE_PATTERN, text or ""):
                labels = set(self._RATING_IN_PROSE.findall(sentence))
                if labels - {rating} and not self._THIRD_PARTY.search(sentence):
                    conflicts.append(sentence.strip()[:200])
        return conflicts

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
        # restated). Replacing the valuation perspective with the fixed text
        # happens on every response and leaves no other field stale, so it
        # alone never sends a valid narrative back for a rewrite.
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
        evidence_pack: Optional[Dict[str, Any]] = None,
    ) -> float:
        """
        Check what percentage of material news sentences have citations.
        Returns coverage percentage.

        Counts every sentence of the printed narrative (thesis, catalysts,
        risks, scenario narratives) that makes a factual claim or states a
        figure, and every printed watch, monitoring or action item that states
        a figure or a date: those must cite the item that gives it.

        Not counted: a model statement (model_statements.is_model_statement:
        it restates VYNN's own rating, fair value, range or alert and says
        nothing else), which the contract forbids citing to news; and the
        price-target drivers, which the report never prints. Counting the
        12-month driver failed every run on that one sentence. Phrases such as
        "the bear case" or "expected return" no longer excuse a sentence: "The
        bear case reflects Apple losing its appeal" is a news claim.
        """
        facts = model_facts(fixed_numbers)
        name, _ = self._subject(evidence_pack, fixed_numbers)
        subject = subject_names(name, None) if name else set()
        narrative = [response_data.get('thesis', '')]
        for key in ('catalysts', 'risks'):
            for row in response_data.get(key, []) or []:
                narrative.append(row.get('statement', '') if isinstance(row, dict) else str(row))
        scenarios = response_data.get('scenarios', {}) or {}
        items = []
        for scenario_type in ['bull', 'base', 'bear']:
            scenario = scenarios.get(scenario_type, {})
            if isinstance(scenario, dict):
                narrative.append(scenario.get('narrative', ''))
                items.extend(str(w) for w in scenario.get('watch') or [])
        action = response_data.get('action', {}) or {}
        if isinstance(action, dict):
            items.extend([str(action.get('buyers') or ''), str(action.get('holders') or '')])
            items.extend(str(w) for w in action.get('watch') or [])
        items.extend(str(m) for m in response_data.get('monitoring_plan', []) or [])

        def split(texts):
            for text in texts:
                for sentence in re.split(self.SENTENCE_PATTERN, text or ""):
                    if sentence.strip():
                        yield sentence.strip()

        # Material: >= 4 words AND (a factual claim keyword OR a figure)
        material_sentences = []
        model_statements = []
        factual_keywords = [
            'revenue', 'growth', 'earnings', 'sales', 'margin', 'profit',
            'risk', 'catalyst', 'competitive', 'regulatory', 'launch', 'product',
            'will', 'could', 'expected', 'anticipated', 'indicates', 'suggests',
            'shows', 'driven', 'quarter', 'year', 'increase', 'decrease',
            'strong', 'weak', 'high', 'low', 'impact', 'potential', 'likely'
        ]
        candidates = [(s, True) for s in split(narrative)] + [(s, False) for s in split(items)]
        for sent_clean, is_narrative in candidates:
            # Skip very short sentences (connectors like "However,")
            if len(sent_clean.split()) < 4:
                continue
            sent_lower = sent_clean.lower()
            has_claim = any(keyword in sent_lower for keyword in factual_keywords)
            has_figure = bool(self._support_numbers(self.EVIDENCE_PATTERN.sub("", sent_clean)))
            if is_narrative:
                if not (has_claim or any(char.isdigit() for char in sent_clean)):
                    continue
            elif not has_figure or not bind_numbers(sent_clean, facts)[1]:
                # A watch, monitoring or action item with no figure or date
                # ("Next quarterly results"), or only VYNN's own ("stage
                # entry against the 12-month convergence case"), states
                # nothing a source must give.
                continue
            if is_model_statement(sent_clean, facts, subject):
                model_statements.append(sent_clean)
                continue
            material_sentences.append(sent_clean)
        
        if not material_sentences:
            report["coverage_details"] = {
                "material_sentences": 0,
                "cited_sentences": [],
                "cited_count": 0,
                "model_statements": len(model_statements),
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
            "model_statements": len(model_statements),
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
