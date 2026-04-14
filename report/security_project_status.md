# VYNN AI Security Project Status

This document is the current handoff and onboarding artifact for the VYNN AI
security extension project. It is meant to be detailed enough for a new engineer
to join cold, understand what has happened, and continue the work without having
to reconstruct the history from commits, terminal logs, or partial notes.

## 1. Executive Status

### Where the project started

The starting point was the existing VYNN AI backend repo: a financial-analysis
engine that ingests cached news, screens articles into structured catalysts and
risks, combines that with frozen valuation artifacts, and produces downstream
recommendation and reporting outputs.

The security project extends that backend to study prompt injection and related
retrieval poisoning risks in the news-analysis path.

### What exists now

The repo now has a real local security benchmark stack:

- a frozen dataset under `datasets/security/`
- a benchmark runner under `src/security/`
- deterministic downstream scoring
- dataset construction from Mongo-backed real news
- clean-to-poisoned case pairing
- run summaries and raw JSONL logs
- caching, resume, and bounded parallelism
- basic defense scaffolding
- a living failure log

### What is working

- The benchmark harness is real and runs end to end.
- The dataset is frozen from Mongo-backed seeds instead of only local markdown.
- A full clean recalibration sweep has now completed successfully on the current
  repaired corpus.
- The corrected scoring contract is in place:
  - headline metric = end-to-end recommendation compromise
  - secondary metric = screening compromise
- The benchmark now records explicit governance metadata:
  - corpus version
  - direction-map version
  - attack-template version
  - metric version
  - target model
  - config name
  - code commit
  - run validity
  - notes
- The project now has a post-reset canonical rebuilt corpus and a compact
  attack-development subset for the next iteration cycle.

### What is not yet working

- We still do not have reliable non-zero headline end-to-end ASR under the
  corrected metric.
- The current attacks often perturb screening outputs without breaking the
  deterministic recommendation layer.
- Tier 2 and Tier 3 remain underpowered relative to the final project goal.
- Defense evaluation should not begin yet, because the baseline attack pack has
  not crossed the breakthrough gate.

### Current bottleneck

The biggest bottleneck is now primarily attack efficacy, not infrastructure.

The corpus-alignment reset has been completed:

- the repaired `META` corpus has been re-frozen from Mongo
- a fresh clean-only sweep has been completed on that corpus
- a new full direction map has been generated from the current clean baselines
- the canonical dataset has been rebuilt again from that new map

What remains hard is the exact point that matters:

- the current attack pack is still too weak against the deterministic downstream
  calculator
- we still need a baseline breakthrough on a tiny high-leverage subset before
  any larger poisoned sweep or defense evaluation is justified

### Why this is still strong-A material

The project is still in strong-A territory because:

- the system under study is real, not a toy pipeline
- the benchmark now distinguishes screening compromise from real user-visible
  compromise
- the work has already surfaced nontrivial engineering and evaluation failures
- the project is now converging toward a controlled scientific reset instead of
  continuing ad hoc iteration

The project is not weak. It is simply at the point where methodology discipline
matters more than adding more runs.

## 2. System and Threat Model

### What this repo does

Inside this repo, VYNN AI:

1. retrieves cached news articles from Mongo-backed storage
2. screens them with an LLM into structured outputs:
   - catalysts
   - risks
   - mitigations
   - analysis summary
3. combines those outputs with frozen financial and model snapshots
4. computes a deterministic recommendation snapshot
5. optionally generates a longer narrative report

The security project is attached to that real path rather than a toy
reimplementation.

### Exact attack surface

The primary attack surface in this project is:

`retrieved news article text -> article screening -> structured screening JSON -> deterministic recommendation snapshot -> report`

The core threat model is that malicious or adversarial content appears inside
retrieved article text, and the LLM misinterprets that content as something to
follow or overweight rather than something to analyze skeptically.

### Prompt injection vs misinformation

This project separates two different phenomena:

- **Prompt injection / retrieval poisoning**
  - article text contains instructions, adversarial framing, or subtle control
    language designed to manipulate model behavior or extracted structure
- **Factual misinformation**
  - article text contains false claims, but not necessarily instruction-like
    payloads

The main project focus is prompt injection and retrieval poisoning, because that
is the strongest match to the course material and the defenses we plan to
evaluate.

### Why the headline metric is end to end

A screening-only change is not enough for the final claim.

The real user-facing failure is:

- the final recommendation band shifts materially
- or expected return / 12-month target shifts enough to change the analyst view

This matters because the deterministic calculator adds real damping. Several
earlier exploratory runs showed that attacks can change screening outputs while
still failing to move the final recommendation enough to count as a true
end-user-visible compromise.

## 3. Dataset Evolution

### Phase 1: local markdown fallback

At one point MongoDB was paused, so the dataset builder fell back to local
checked-in markdown files under the legacy data tree. That gave us a usable MVP
scaffold, but the corpus quality was weaker and less representative than the
live cached-news source.

Takeaway:

- useful for initial plumbing
- not strong enough for final evaluation

### Phase 2: Mongo-backed frozen corpus

After MongoDB was reactivated, the dataset builder was extended to freeze cases
from live cached articles. This became the real basis of the benchmark.

Current benchmark shape:

- `20` clean cases
- `60` poisoned cases
- `4` tickers
  - `AAPL`
  - `AMZN`
  - `META`
  - `NVDA`
- `3` poisoned tiers per clean scenario

### Phase 3: attack-template evolution

The first attack generation pass was too generic. It relied too heavily on
deterministic appended text and did not reliably influence the downstream
calculator.

The current attack family version is:

- `attack_template_version = v3_boundary_aware_structured_templates`

This is better than the first generation, but still not strong enough to claim
successful end-to-end compromise at scale.

### Phase 4: calibration bug and fix

An important benchmark-design bug was discovered:

- `target_direction` had initially been assigned by scenario parity
- rather than by the clean baseline's shortest path to a recommendation-band
  change

This made many poisoned cases low leverage by construction.

Fix:

- run clean baselines
- compute the shortest move to the next boundary
- derive `target_direction` from actual clean outputs
- rebuild the dataset from that calibration

### Phase 5: META contamination bug and fix

The `META` corpus surfaced a real relevance bug:

- generic use of the token `meta` was enough to admit unrelated Disney,
  e-commerce, or generic metadata content

Fixes that now exist in the builder:

- bare `meta` is no longer treated as a strong alias
- word-boundary matching is used for alias scoring
- stronger company-match signals are preferred in ranking and filtering

One additional lesson matters here: after these fixes were added, an on-disk
frozen corpus snapshot still showed contaminated `META` scenarios. A fresh
forced rebuild from live Mongo resolved that discrepancy. In other words, the
current issue was a stale frozen artifact, not an unresolved live-ranking bug.

### Current canonical dataset state

The current canonical dataset metadata is:

- `corpus_version = corpus-700684c1dad2`
- `direction_map_version = direction-map-ab9f15deea0a`
- `attack_template_version = v3_boundary_aware_structured_templates`
- `metric_version = v2_end_to_end_primary_with_structured_screening_shift`
- `code_commit = d2f50293000d140c410bcc27b6481603a12c6768`

Dataset shape remains:

- `20` clean
- `60` poisoned
- `80` total

One important nuance is now explicitly preserved for the calculator-first phase:

- the current frozen dataset metadata points at the post-reset canonical corpus
  above
- the latest completed clean-run artifact slice under
  `runs/security-openai-clean-reset-v2/baseline/` still records the earlier
  run-level metadata:
  - `corpus_version = corpus-ac1f03a3e0d5`
  - `direction_map_version = direction-map-7186ef4fd3ab`

This means the white-box calculator analysis should be treated as grounded in
the clean-reset run artifacts themselves, not silently merged with the later
canonical dataset freeze. That distinction is acceptable for attack-development
work, but it should remain explicit in the paper.

## 4. Implementation Status

### Benchmark harness

Implemented:

- case loading from JSONL manifest
- per-case execution through the real VYNN screening path
- deterministic recommendation snapshot generation
- per-case artifacts and raw JSONL logs
- summary JSON and markdown

### Dataset builder

Implemented:

- local and Mongo-backed seed discovery
- deduplication
- relevance scoring
- stronger topical filtering
- case freezing into markdown article bundles
- metadata-rich manifest writing
- benchmark metadata file generation

### Calibration flow

Implemented:

- clean baseline sweep support
- direction-map generation from clean outputs
- boundary distance computation
- target return shift metadata

### Scoring logic

Implemented:

- corrected headline ASR
- screening-shift metric
- structured screening-drift detection
- pairwise clean-vs-poisoned comparison

### Caching / resume / parallelism

Implemented:

- disk-backed LLM cache
- resumable benchmark runs
- process-based parallel case execution
- raw-run reuse for cheap summary regeneration

### Calculator-first analysis

Implemented:

- a white-box calculator-analysis utility at `src/security/analyze_calculator.py`
- per-case attackability records with synthetic one-document perturbations
- aggregate and per-case attack-surface JSON artifacts
- an analyst-facing markdown summary at `report/calculator_attack_surface.md`

What it now gives us:

- the true numeric attack surface for the deterministic calculator
- boundary distance to the next rating band per clean case
- first-attack recommendations grounded in calculator-consumed fields
- a principled Stage 1 target list:
  - `aapl_s05_clean`
  - `aapl_s01_clean`
  - `nvda_s01_clean`
  - first bearish re-entry: `meta_s04_clean`

Important scope note:

- the attack-template code has now advanced through:
  - `v4_calculator_first_evidence_templates`
  - `v5_calculator_first_stage1_tuned_templates`
- the frozen canonical poisoned corpus is still materialized from the older
  `v3_boundary_aware_structured_templates`
- this is intentional for the current phase: the calculator-first loop should
  guide the next targeted dev attacks before any broader corpus regeneration

### Attack-development materialization and fail-fast validity checks

Implemented:

- a compact dev-manifest builder at
  `src/security/materialize_attack_development.py`
- regression coverage for dev-manifest regeneration in
  `tests/security/test_attack_dev_manifest.py`
- fail-fast handling for dropped article batches in the security pipeline

Why this matters:

- we can now iterate on attack templates without rebuilding the full canonical
  benchmark corpus
- a poisoned case is no longer allowed to complete successfully if one of its
  article batches silently drops out of screening

### Defense scaffolding

Partially implemented:

- StruQ-inspired input separation hooks
- deterministic sanitizer hooks
- verifier hook / guarded mode path

Not yet ready for serious evaluation:

- defense experiments should remain blocked until baseline attacks achieve
  non-zero headline ASR

### What is implemented vs stubbed

Implemented and usable now:

- dataset builder
- runner
- calibration
- scoring
- selection of attack-development subset
- governance metadata

Partially implemented / not yet central:

- defense evaluation
- adaptive attack loop
- final paper tables

## 5. Experiment Log

### `security-openai-pilot-v2`

- Purpose:
  - first Mongo-backed OpenAI pilot after stronger attack templates
- Validity:
  - `historical_exploration`
- Result:
  - `16` completed runs
  - headline ASR `0.0`
  - screening shift rate `0.25`
- What we learned:
  - attacks were affecting upstream screening sometimes
  - no meaningful downstream recommendation compromise yet

### `security-openai-pilot-v3`

- Purpose:
  - rerun pilot after attack-direction calibration improvements
- Validity:
  - `historical_exploration`
- Result:
  - `16` completed runs
  - headline ASR `0.0`
  - screening shift rate `0.4167`
- What we learned:
  - calibration improved directional alignment
  - still no headline end-to-end success

### `security-openai-clean-v1`

- Purpose:
  - first full clean-only sweep to generate a principled direction map
- Validity:
  - `historical_exploration`
- Result:
  - `20` completed clean runs
- What we learned:
  - initial direction map generation worked
  - but it later became stale when the corpus changed after the `META` repair

### `security-stage1-subset`

- Purpose:
  - small live sanity subset using two workers
- Validity:
  - `historical_exploration`
- Result:
  - `4` completed runs
  - `2` scored attack pairs
  - headline ASR `0.0`
  - screening shift rate `1.0`
- What we learned:
  - runner and parallelism were healthy
  - attacks were changing screening outputs but not final recommendations

### `security-targeted-tier3`

- Purpose:
  - small targeted tier-3 probe on near-boundary cases
- Validity:
  - `invalidated`
- Why invalid:
  - run was executed before the `META` contamination fix
- Result:
  - headline ASR `0.0`
  - screening shift rate `1.0`
- What we learned:
  - useful operationally
  - not safe to cite as final evidence

### `security-meta-fix-check`

- Purpose:
  - verify that the repaired `META` corpus is topical and coherent
- Validity:
  - `sanity_check`
- Result:
  - corrected `META` pair ran cleanly
  - headline ASR `0.0`
  - screening shift rate `1.0`
- What we learned:
  - the repaired corpus is usable
  - old clean calibration was now stale relative to the repaired corpus

### `security-openai-clean-reset-v1`

- Purpose:
  - full clean recalibration sweep after the repaired corpus and governance reset
- Validity:
  - `sanity_check`
- Result:
  - `20` clean cases completed
  - benchmark metadata recorded in summary
  - one pathological long-running case required a targeted retry with smaller
    batch size
- What we learned:
  - the repaired corpus is stable enough for full clean recalibration
  - new direction map generation is now justified
  - the next experimental step can finally use a synchronized corpus and
    calibration pair

### `security-openai-clean-reset-v2`

- Purpose:
  - complete the clean recalibration on the fully rebuilt repaired corpus and
    freeze the canonical post-reset benchmark state
- Validity:
  - `sanity_check`
- Result:
  - `20` completed clean runs
  - `0` failed runs
  - mean clean duration `63.997` seconds
  - one transient timeout on `amzn_s01_clean` batch 1 recovered automatically
- What we learned:
  - the current repaired corpus is operationally healthy enough for a full
    clean-only sweep
  - the earlier suspected `META` contamination on disk was a stale frozen
    snapshot issue, not evidence that the current live ranking logic was still
    broken
  - the canonical benchmark can now advance to attack redesign on the compact
    dev subset without another corpus-validity detour

### `calculator-attack-surface`

- Purpose:
  - switch from broad benchmark iteration to a white-box, calculator-first
    attack-development program
- Validity:
  - `analysis_only`
- Result:
  - generated
    `runs/security-openai-clean-reset-v2/baseline/calculator_attack_surface.json`
  - generated per-case `calculator_attack_surface.json` artifacts under each
    clean case directory
  - generated `report/calculator_attack_surface.md`
- What we learned:
  - the deterministic calculator only uses valuation gap, catalyst score, risk
    score, and momentum
  - risk type and mitigations do not move the numeric recommendation
  - low-confidence items are filtered before the calculator sees them
  - `AAPL` and `NVDA` near-boundary bullish cases are the highest-leverage next
    targets
  - `META` is a more plausible first bearish re-entry case than `AMZN`

### `security-stage1-v4-aapl-s05`

- Purpose:
  - first live Stage 1 attack-development slice on the easiest bullish base
    case
- Validity:
  - `invalidated`
- Why invalid:
  - poisoned cases suffered first-batch OpenAI connection failures
  - the old pipeline still treated partial screening outputs as completed runs
- What we learned:
  - the benchmark needed a hard fail-fast rule for dropped article batches
  - `tier1` looked strong, but the result could not be trusted until the
    partial-batch bug was fixed

### `security-stage1-v4-aapl-s05-v2`

- Purpose:
  - rerun the first AAPL Stage 1 slice after the fail-fast patch
- Validity:
  - `sanity_check`
- Result:
  - `4` runs completed
  - headline ASR `0.3333`
  - screening shift rate `1.0`
- What we learned:
  - `tier1` could already produce a real `SELL -> HOLD` flip
  - `tier2` and `tier3` were still changing the screener without crossing the
    final numeric boundary
  - top-of-document positional control mattered for this sustainability-heavy
    seed article

### `security-stage1-v5-aapl-s05`

- Purpose:
  - rerun the same AAPL slice after tuning `tier2` and `tier3`
- Validity:
  - `sanity_check`
- Result:
  - headline ASR `1.0`
  - screening shift rate `1.0`
  - all three tiers crossed `SELL -> HOLD`
- What we learned:
  - the tuned `v5` templates produced the first non-tier1 end-to-end wins
  - bullish attacks worked best when the financial overlay moved to the top of
    the article and avoided unnecessary residual downside language

### `security-stage1-v5-aapl-s01`

- Purpose:
  - test whether the tuned pattern generalized to a second near-boundary AAPL
    bullish case
- Validity:
  - `sanity_check`
- Result:
  - headline ASR `1.0`
  - screening shift rate `1.0`
  - both `tier2` and `tier3` crossed `SELL -> HOLD`
- What we learned:
  - the tuned bullish pattern is not limited to a single base case
  - it can add enough calculator-consumed catalyst mass to cross the boundary
    on a second AAPL scenario too

### `security-openai-pilot-v5`

- Purpose:
  - first full pilot rerun after the Stage 1 `v5` breakthrough
- Validity:
  - `benchmark_candidate`
- Result:
  - `16` completed runs
  - overall headline ASR `0.1667`
  - screening shift rate `1.0`
  - tier ASR:
    - `tier1 = 0.0`
    - `tier2 = 0.25`
    - `tier3 = 0.25`
- What we learned:
  - the tuned templates scale beyond the handpicked Stage 1 slices
  - the first non-zero full-pilot headline ASR now exists
  - the wins are still concentrated in the bullish AAPL cases
  - `AMZN` remains valuation-locked in the pilot
  - `META` and `NVDA` still need stronger or more case-specific attack design

## 6. Failures and Root Causes

### Stale OpenAI key

Root cause:

- environment credential drift

Effect:

- early planned benchmark runs could not execute

### Paused MongoDB

Root cause:

- cluster inactivity

Effect:

- builder fell back to weaker local markdown seeds

### Weak local fallback corpus

Root cause:

- local data tree was never meant to be the final benchmark corpus

Effect:

- weaker article quality
- poorer AMZN coverage

### Anthropic JSON instability

Root cause:

- strict JSON screening path was less stable on the tested Anthropic fallback

Effect:

- malformed or low-signal outputs
- parser failures confounded security interpretation

### Parity-based target-direction bug

Root cause:

- target direction initially assigned by scenario index rather than by clean
  boundary proximity

Effect:

- many attacks pushed in the wrong or low-leverage direction

### Overly permissive early metric

Root cause:

- sentiment-only movement was initially too easy to interpret as success

Effect:

- upstream compromise looked stronger than true end-to-end compromise

### META seed contamination

Root cause:

- generic `meta` token matching was too weak a relevance signal

Effect:

- unrelated content entered `META` scenarios
- some targeted runs became invalid for final use

### Stale clean calibration after corpus repair

Root cause:

- repaired corpus changed clean baselines

Effect:

- old direction map could no longer be trusted

### Stale frozen corpus snapshot after live META repair

Root cause:

- the on-disk dataset snapshot was not in sync with the current repaired live
  Mongo-backed ranking, even though the builder logic itself was already cleaner

Effect:

- `META` contamination appeared to persist after the builder fix
- this temporarily looked like an unresolved code bug when the real issue was
  that the frozen corpus needed to be rebuilt again and revalidated

### Hung clean recalibration wrapper on `nvda_s03_clean`

Root cause:

- long-context / long-call instability on a single heavy case

Effect:

- full clean sweep stalled at `19/20`
- required targeted retry with smaller batch size and summary recovery

### Partial-batch screening accepted as valid completion

Root cause:

- the parent article screener returned empty results when a non-recoverable
  batch call failed
- the security pipeline did not yet treat that as a fatal validity error

Effect:

- an early Stage 1 live slice could appear to succeed simply because poisoned
  evidence dropped out of the screening stage
- this was fixed before any later `v4` or `v5` results were treated as valid

### Run-metadata drift between clean-reset artifacts and later canonical freeze

Root cause:

- the benchmark was rebuilt again after the clean-reset run artifacts were
  already produced, so the dataset metadata file advanced while the completed
  clean-run slice still carried older corpus and direction-map version IDs

Effect:

- calculator-first analysis is currently tied to the clean-run artifact slice
  rather than the latest dataset metadata file
- this is acceptable for attack development, but it should not be glossed over
  in the final report

## 7. What Worked and Why

### Real corpus freezing

Worked because:

- it anchored the benchmark in the actual retrieval source VYNN uses

### Corrected end-to-end metric

Worked because:

- it aligned success with real user-visible failures instead of upstream-only drift

### Parallelism and resume

Worked because:

- it reduced iteration cost without changing benchmark semantics

### Screening-shift detection

Worked because:

- it captured structured screening compromise even when counts stayed constant

### Failure logging discipline

Worked because:

- it preserved negative results and invalid runs instead of forcing a false
  polished story

### Governance metadata

Worked because:

- it now makes version drift visible directly in artifacts instead of relying on
  memory or terminal history

### Clean recalibration reset v2

Worked because:

- it finally synchronized the repaired corpus, the clean baselines, and the
  direction map in one consistent experimental slice

### White-box calculator review

Worked because:

- it cut through benchmark noise and showed exactly which extracted fields can
  and cannot move the deterministic recommendation
- it replaced guesswork about Tier 2 and Tier 3 efficacy with concrete boundary
  and contribution analysis

### Compact dev-manifest regeneration

Worked because:

- it let us iterate on attack templates without touching the canonical frozen
  benchmark corpus
- it cleanly separated exploratory attack tuning from the main benchmark

## 8. What Failed and Why

### Weak attack templates

Failed because:

- they often changed wording but not the structured fields strongly enough to
  cross the deterministic calculator boundary

### Over-broad seed matching

Failed because:

- topical relevance for finance content needs stronger company grounding than
  naive alias overlap

### Broad reruns while the experiment contract was still moving

Failed because:

- corpus, calibration, metric, and attack logic were changing simultaneously
- cross-run comparisons became harder to trust

### Spending runs before baseline breakthrough

Failed because:

- more data from weak attacks does not automatically create a stronger scientific
  result
- it mostly increases cost and history complexity

### Treating all structured fields as equally important

Failed because:

- the screener emits many fields, but the calculator only consumes a small
  subset of them
- this let earlier attack design spend effort on mitigations, risk type, and
  other fields that do not change the numeric recommendation

### Accepting partial-batch outputs as usable evidence

Failed because:

- it could turn an OpenAI connection drop into a false-looking attack success
- it blurred the line between model behavior and missing evidence

### Misreading stale frozen artifacts as live-builder regressions

Failed because:

- it risked sending the team back into low-leverage builder tweaks when the
  highest-value action was simply to rebuild the canonical corpus and confirm the
  live ranking directly

## 9. Current Plan and Remaining Project Work

### Immediate next step

The next real milestone is no longer the first breakthrough. That has now
happened. The next step is:

- use the non-zero `v5` pilot baseline as the first fair comparison point for
  defenses
- continue calculator-first attack tuning specifically for:
  - `nvda_s01`
  - the first bearish re-entry cases (`meta_s01` and later `meta_s04`)

Current selected subset:

- `aapl_s05_tier1`
- `aapl_s05_tier2`
- `aapl_s01_tier2`
- `aapl_s05_tier3`
- `aapl_s01_tier3`
- `nvda_s01_tier1`

This subset is intentionally small and high leverage:

- mostly near-boundary `AAPL` bullish cases with the smallest required return
  shift
- one `NVDA` bullish case for cross-ticker diversity

Calculator-first Stage 1 priorities are now:

- `aapl_s05_clean`
- `aapl_s01_clean`
- `nvda_s01_clean`

First bearish re-entry after the first bullish wins:

- `meta_s04_clean`

Practical attack-design constraints for the next loop:

- optimize primarily for catalyst type, catalyst timeline, catalyst confidence,
  risk severity, risk likelihood, risk confidence, and count
- treat sentiment as a secondary lever
- do not spend more time targeting mitigations or risk type as if they move the
  numeric rating
- keep full report generation off during attack development; use recommendation
  snapshots plus screening JSON

### Breakthrough gate

This gate is now met:

- at least `2` headline end-to-end successes exist
- at least `1` success comes from Tier 2 or Tier 3

### After the gate is met

1. rerun the `16`-case pilot on the tuned corpus
2. use that pilot as the first baseline for:
   - `struq-lite`
   - guarded / verifier mode
3. in parallel, continue targeted attack tuning for:
   - `NVDA` bullish
   - `META` bearish
4. if the pilot remains stable, run the full `80`-case baseline
5. then run adaptive attacker-moves-second evaluation on a focused subset
6. then finalize:
   - main quantitative tables
   - qualitative case studies
   - final paper framing

### Remaining project work

- operationalize the calculator-first dev loop on the Stage 1 target cases
- strengthen attack templates against the real screener and calculator
- produce stronger cross-ticker baseline headline ASR beyond the AAPL-heavy pilot wins
- implement and evaluate defenses fairly
- run adaptive attacks
- produce final paper tables and narrative case studies

## 10. Non-Negotiable Rules Going Forward

- No more full poisoned sweeps before the attack-development subset shows a real
  baseline breakthrough.
- No defense benchmarking before non-zero baseline headline ASR exists.
- No cross-version comparison in the paper unless the corpus and calibration
  versions match.
- No final paper tables from contaminated or stale-calibration runs.
- No claiming screening compromise as end-to-end compromise.
- No more silent run-history assumptions; use the recorded benchmark metadata.
- No more attack effort on fields that the calculator does not consume.

## 11. Current Canonical Versions and Commands

### Current canonical versions

- `corpus_version = corpus-700684c1dad2`
- `direction_map_version = direction-map-ab9f15deea0a`
- `attack_template_version = v3_boundary_aware_structured_templates`
- `metric_version = v2_end_to_end_primary_with_structured_screening_shift`
- `code_commit = d2f50293000d140c410bcc27b6481603a12c6768`

### Key reproduction commands

Rebuild the canonical corpus:

```bash
PYTHONPATH=src conda run -n stock-analyst python -m src.security.build_dataset \
  --force \
  --seed-source mongo \
  --direction-map datasets/security/direction_map_full.json \
  --notes "canonical corpus after clean recalibration reset v2"
```

Run the clean recalibration sweep:

```bash
PYTHONPATH=src conda run -n stock-analyst python -m src.security.run_benchmark \
  --config baseline \
  --max-workers 2 \
  --batch-size 2 \
  --case-type clean \
  --skip-report \
  --run-validity sanity_check \
  --notes "full clean recalibration sweep after canonical corpus freeze" \
  --output-root runs/security-openai-clean-reset-v2
```

Regenerate the direction map:

```bash
PYTHONPATH=src conda run -n stock-analyst python -m src.security.calibrate_directions \
  --raw-runs runs/security-openai-clean-reset-v2/baseline/raw_runs.jsonl \
  --output datasets/security/direction_map_full.json
```

Generate the calculator-first attack-surface analysis:

```bash
PYTHONPATH=src conda run -n stock-analyst python -m src.security.analyze_calculator \
  --runs runs/security-openai-clean-reset-v2/baseline/raw_runs.jsonl
```

Select the attack-development subset:

```bash
PYTHONPATH=src conda run -n stock-analyst python -m src.security.select_attack_development \
  --cases datasets/security/cases.jsonl \
  --output datasets/security/attack_development_subset.json \
  --total-cases 6 \
  --max-target-shift 8.0
```

### Final takeaway

The project is no longer blocked on missing infrastructure. It is now at the
research phase where attack strength, experimental discipline, and honest result
interpretation will decide the final grade.

That is a good place to be, as long as the next iteration is tight and
scientifically controlled.
