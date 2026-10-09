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

1. **`thesis`**: 2-4 sentences with [E#] citations
2. **`valuation_perspective`**: keep exactly as given (the engine writes it)
3. **`price_targets.*.driver`**: keep exactly as given (the engine writes them)
4. **`catalysts`**: Array of statements with [E#] citations
5. **`risks`**: Array of statements with [E#] citations
6. **`scenarios.bull/base/bear.narrative`**: 2-3 sentences each with [E#] citations
7. **`scenarios.bull/base/bear.watch`** and **`action.watch`**: items to monitor
8. **`action.buyers`**: 1-2 of E0's sentences, word for word, with [E0]
9. **`action.holders`**: 1-2 of E0's sentences, word for word, with [E0]
10. **`monitoring_plan`**: Array of items to monitor

**E0 is VYNN's own figures and provider market data, not news.** A sentence
that states VYNN's rating, fair value, range, the share price used, the implied
return, the analysts' mean target, the confidence alert or a market-data figure
is one of E0's sentences, copied word for word, ending with [E0] and citing
nothing else. Never cite E0 for news or a news item for VYNN's figures or view;
keep the two in separate sentences. Quote E0 only in the thesis, the base case
narrative and the buyers' and holders' lines, which hold E0's sentences and
nothing else. Write evidence IDs only as citations in
brackets, never in the text. Any sentence or item that states a figure or a
date cites the item that gives it, or the figure is deleted.

## CRITICAL RULES - PRODUCTION STANDARDS

❌ **DO NOT**:
- Change ANY numeric fields (price, range_low, range_high, rating)
- Cite evidence IDs not in the valid list above
- Make specific claims without [E#] citations
- Invent facts or figures not in evidence
- Use a citation for a claim that its `source_article_title` and `snippet` do
  not directly support; topical similarity is not support
- Add sector/peer averages or event dates unless the exact fact is present in
  the cited evidence
- Change the JSON structure or field names
- Leave ANY material sentence without a citation
- Attach a news citation to a model-derived valuation, rating, or target fact
  (use one of E0's sentences, word for word, for those)

✅ **DO**:
- Keep ALL numeric fields EXACTLY as shown above
- Add [E#] to every source-backed news claim, and remove or qualify claims for
  which no source directly supports the wording
- Use ONLY valid evidence IDs from the list
- Remove or qualify any unsupported claim instead of decorating it with the
  nearest citation. If a date is not supplied, omit it or say it is unavailable
- Be professional, specific, and compelling
- Cite a source that states it on EVERY sentence and item (THIS IS MANDATORY)
- Cite primary sources when discussing financial figures
- Keep every price-target driver empty when its corrected price is null

## Example of Good Citations

✅ "Apple reported Q3 revenue growth of 10% YoY [E1]." (when E1 states exactly that)
❌ "Apple reported Q3 revenue growth of 10% YoY [E1], showing its pricing power." (adds a conclusion E1 does not state - FAILS the fact check)
❌ "Buy the shares now: Apple launched the iPhone Duo [E2]." (advice no source states - FAILS)
❌ "Apple had strong revenue growth." (no citation - FAILS VALIDATION)
❌ "Revenue reached $94B [E99]." (invalid evidence ID - FAILS VALIDATION)

## Output Format

Return the COMPLETE corrected JSON with:
- All numeric fields UNCHANGED
- Text fields rewritten with proper [E#] citations
- Same JSON structure as template above
- No invalid evidence IDs

Return STRICT JSON (copy structure from CORRECTED TEMPLATE above).
