# Investment Recommendation Text-Only Rewrite

You previously generated an investment recommendation that had validation issues.
The numeric fields have been AUTO-CORRECTED. Now rewrite ONLY the text fields.

## Issues Found

{issues_section}

## CORRECTED TEMPLATE (USE THIS EXACT STRUCTURE)

```json
{corrected_json}
```

## VALID EVIDENCE IDs

**ONLY cite these IDs**: {valid_evidence_ids}

Any other evidence ID (like [E99]) is INVALID and will fail validation.

## SOURCE EVIDENCE (AUTHORITATIVE FOR [E#] CLAIMS)

```json
{source_evidence_json}
```

Only `source_article_title` and `snippet` substantiate a cited claim. The
previous recommendation text is generated prose, not evidence. A valid ID is
not enough: the cited publisher text must directly support the whole sentence,
including every number.

## ITERATION CONTEXT

**This is Rewrite Attempt {attempt} of 3**

{iteration_guidance}

## Your Rewrite Task

Take the JSON structure above and rewrite these TEXT fields ONLY:

1. **`thesis`**: 2-4 sentences; [E#] on every news claim
2. **`valuation_perspective`**: keep exactly as given (it is fixed text)
3. **`price_targets.m3.driver`**: empty string (the fixed target is null)
4. **`price_targets.m6.driver`**: empty string (the fixed target is null)
5. **`price_targets.m12.driver`**: explain the deterministic intrinsic-value convergence basis, with NO [E#]; do not invent a news-driven return adjustment
6. **`catalysts`**: Array of statements with [E#] citations
7. **`risks`**: Array of statements with [E#] citations
8. **`scenarios.bull/base/bear.narrative`**: 2-3 sentences each; [E#] on every news claim
9. **`scenarios.bull/base/bear.watch`** and **`action.watch`**: short items to monitor
10. **`action.buyers`**: 1-2 sentences
11. **`action.holders`**: 1-2 sentences
12. **`monitoring_plan`**: Array of items to monitor

**Two kinds of sentence.** A news claim (what happened, what a source
reports) carries the [E#] of the item that states it. A model statement (the
rating, the fair value, the DCF range, the confidence alert's gaps and analyst
count, copied from the fields above) carries NO [E#]: no news item states
VYNN's numbers, and the validator checks those figures against the fixed
numbers instead. A watch or monitoring item cites [E#] only when it restates
a fact that item's title or snippet gives; a plain "what to watch" item takes
no citation.

## CRITICAL RULES - PRODUCTION STANDARDS

❌ **DO NOT**:
- Change ANY numeric fields (price, range_low, range_high, rating)
- Cite evidence IDs not in the valid list above
- Make specific news claims without [E#] citations
- Invent facts or figures not in evidence
- Use a citation for a claim that its `source_article_title` and `snippet` do
  not directly support; topical similarity is not support
- Add sector/peer averages or event dates unless the exact fact is present in
  the cited evidence
- Change the JSON structure or field names
- Leave a news claim without a citation
- Attach a news citation to a model-derived valuation, rating, or target fact

✅ **DO**:
- Keep ALL numeric fields EXACTLY as shown above
- Add [E#] to every source-backed news claim, and remove or qualify claims for
  which no source directly supports the wording
- Use ONLY valid evidence IDs from the list
- Remove or qualify any unsupported claim instead of decorating it with the
  nearest citation. If a date is not supplied, omit it or say it is unavailable
- Be professional, specific, and compelling
- ACHIEVE 95%+ citation coverage of news claims (THIS IS MANDATORY)
- Cite primary sources when discussing financial figures
- Keep every price-target driver empty when its corrected price is null

## Example of Good Citations

✅ "Apple reported Q3 revenue growth of 10% YoY [E1], driven by strong iPhone sales [E2]."
✅ "Regulatory challenges in the EU pose ongoing risks [E10], while AI competition intensifies [E8][E11]."
❌ "Apple had strong revenue growth." (no citation - FAILS VALIDATION)
❌ "Revenue reached $94B [E99]." (invalid evidence ID - FAILS VALIDATION)

## Output Format

Return the COMPLETE corrected JSON with:
- All numeric fields UNCHANGED
- Text fields rewritten with proper [E#] citations
- Same JSON structure as template above
- No invalid evidence IDs

Return STRICT JSON (copy structure from CORRECTED TEMPLATE above).
