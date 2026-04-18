# VYNN AI Security Project Reviewer Review

Date: 2026-04-17

This document is a reviewer-facing assessment of the VYNN AI security project
as it exists today.

It is written to help an instructor, TA, or outside reviewer understand:

1. what the project set out to do,
2. what was actually implemented,
3. what experiments were run,
4. what the results really support,
5. what the limitations are,
6. what is still left before final submission.

It is intentionally opinionated and evaluative, not just archival.

---

## 1. Executive Evaluation

### Bottom line

This is now a **substantial, credible, upper-tier course project**.

The project is no longer a rough prototype or a benchmark scaffold. It has:

- a real system target rather than a toy pipeline,
- a reproducible security benchmark layer,
- a concrete static attack ladder,
- a mechanistic white-box analysis of the downstream deterministic calculator,
- one positive defense result,
- one negative defense family result,
- one adaptive erosion result,
- and a final rigor-closure layer that quantifies repeatability and limitation
  structure.

### Current status

The project is **research-complete enough to stop experimenting**.

The remaining work is no longer “find more attacks” or “build more tooling.”
The remaining work is:

- final report writing,
- careful claim selection,
- consistent table construction,
- and disciplined discussion of limitations.

### My honest academic judgment

If graded today as a course project, this is realistically in the:

- **A- to A** range

It is stronger than a typical course project because:

- it studies a real deployed-style system,
- the engineering is serious,
- the evaluation is iterative and increasingly rigorous,
- and the final conclusions are honest rather than inflated.

It is **not** yet an “easy A+ / paper-ready without criticism” project, because:

- the positive end-to-end attack evidence is still narrow,
- the strongest historical successes are concentrated on AAPL,
- fresh controlled repeats did not robustly reproduce those earlier AAPL tier-3
  successes,
- and the adaptive evidence remains small.

But it is now very well positioned to become a **strong final A-level course
project** if the final report is written with the right posture.

---

## 2. Original Goal and Final Scope

### Initial goal

The project began as an extension of VYNN AI for a course project on security
issues in generative AI.

The initial ambition included:

- prompt injection attacks,
- threat modeling,
- defenses,
- adaptive evaluation,
- and possibly broader or more aggressive downstream corruption stories.

### Final scope after empirical investigation

The final scope became more focused and more realistic:

- attack surface:
  `retrieved article text -> screening LLM -> structured screening JSON -> deterministic recommendation calculator -> optional report`
- primary threat model:
  **single poisoned retrieved article**
- primary metric:
  **end-to-end recommendation compromise**
- secondary metric:
  **screening compromise**
- explicit added defenses:
  - `struq-lite`
  - cross-model verifier
- adaptive evaluation:
  - one focused defense-aware round on the most informative AAPL slice

This narrowing was scientifically justified.

The most important scope correction was recognizing that the real downstream
attack surface in this repo is **recommendation shift through structured news
analysis**, not speculative tool corruption or unconstrained DCF corruption.

That was the correct pivot.

---

## 3. What System Was Studied

This project studies the real VYNN AI backend, not a synthetic QA system.

The relevant path is:

`retrieved news -> GPT screening -> structured catalysts / risks / sentiment -> deterministic calculator -> final rating / target`

Important architectural fact:

- the final numeric recommendation is not produced directly by the LLM
- instead, the LLM produces structured intermediate fields
- those fields are then consumed by a deterministic Python calculator

That architectural separation ended up being the most important scientific fact
in the entire project.

It means:

- prompt-level compromise is not the same as user-visible compromise
- downstream architecture matters
- and evaluating only the LLM’s immediate output would overstate attacker power

---

## 4. Threat Model

The main threat model used throughout the project is:

- the attacker controls **one retrieved article**
- the rest of the retrieval bundle remains clean

So a poisoned case is not “one clean article versus one poisoned article.”
It is:

- one fixed clean article bundle,
- with one anchor article replaced by a poisoned version,
- evaluated against the corresponding clean baseline bundle.

This is a reasonable and conservative starting point.

It is not the strongest possible attacker.
An attacker who could poison multiple retrieved articles would likely be
stronger.

That should be presented as a limitation, but also as a conservative design
choice.

---

## 5. Dataset and Benchmark Construction

### Final benchmark shape

The canonical corpus is:

- **20 clean scenarios**
- **60 poisoned cases**

Why:

- `4 tickers`
  - `AAPL`
  - `AMZN`
  - `META`
  - `NVDA`
- `5 scenarios per ticker`
- `3 attack tiers per scenario`

So:

- `4 x 5 = 20 clean scenarios`
- `20 x 3 = 60 poisoned cases`

### Important benchmark governance improvements

Over time, the benchmark gained explicit versioning and governance metadata:

- corpus version
- direction-map version
- attack-template version
- metric version
- code commit / run-validity metadata

This was a major strength improvement.
It prevented the final report from mixing exploratory, contaminated, or stale
results with the frozen evidence set.

### Major dataset issues that were discovered and fixed

The project did not get the dataset right on the first try.
Important issues included:

- fallback to weak local markdown seeds when MongoDB was paused
- parity-based direction heuristics that were later corrected by clean-run
  recalibration
- a `META` contamination issue where generic “meta” text matched unrelated
  content
- stale calibration after corpus repair

These were not fatal in the end, because they were caught, documented, and
corrected before the final evidence package was frozen.

That debugging history actually strengthens the project if it is described
clearly.

---

## 6. What Was Implemented

The security extension is now a real subsystem under `src/security/`.

### Core benchmark layer

Implemented:

- typed models and presets
- case manifest loading / validation
- dataset freezing from Mongo-backed news
- clean-direction calibration
- benchmark governance and run metadata
- local benchmark CLI
- resume support
- bounded parallel execution
- disk-backed LLM caching

### Attack layer

Implemented:

- tiered attack templates
- attack-development subset materialization
- calculator-first attack redesign
- white-box analysis of the deterministic calculator
- upper-bound structured perturbation study for hard cases

### Defense layer

Implemented:

- `struq-lite`
  - explicit document delimitering
  - “data not instructions” prompt framing
  - deterministic sanitizer hook
- cross-model verifier
  - v1 generic-quality prompt
  - v2 injection-specific redesign
  - offline replay evaluation
  - threshold calibration

### Evidence / report layer

Implemented:

- results ledgers
- table-value generators
- case-study exporters
- verifier failure analysis
- clean-utility analysis
- defense repeatability analysis
- controlled repeatability supplement
- native-defense ablation
- cross-case attackability analysis

This is a serious amount of implementation work for a course project.

---

## 7. Attack Design and Evolution

### Tier definitions

The final static ladder is:

- **Tier 1**: naive / explicit addendum-style injection
- **Tier 2**: finance-styled, schema-aware poisoning
- **Tier 3**: calculator-aware, case-specific poisoning

Later, a small **adaptive** AAPL-only slice was added for defense-aware
reattack.

### Important methodological improvement

The most important attack-design improvement was the shift to
**calculator-first / white-box attack design**.

Early attacks were too generic.
Later attacks were designed around the actual numeric levers used by the
downstream calculator:

- catalyst type
- catalyst timeline
- catalyst confidence
- catalyst count
- risk severity
- risk likelihood
- risk confidence
- sentiment only through momentum

This was the right move.
It made the attacks more scientifically meaningful.

---

## 8. Major Experiments and What They Showed

## 8.1 Native baseline (`Defense 0`)

Main frozen baseline:

- [summary.json](/Users/zanwenfu/IdeaProject/stock-analyst/runs/security-openai-pilot-v5/baseline/summary.json)

Held-out pilot result:

- headline ASR: `0.1667`
- screening shift rate: `1.0`

Interpretation:

- every poisoned pilot case changed the screening output
- but only `2 / 12` changed the final rating band

This is the project’s central empirical result:

> screening compromise is much easier than user-visible recommendation
> compromise

### Important nuance

Those two successful pilot cases were:

- `aapl_s01_tier2`
- `aapl_s01_tier3`

So the positive end-to-end evidence is real, but narrow.

## 8.2 Mechanistic calculator analysis

Main artifact:

- [calculator_attack_surface.md](/Users/zanwenfu/IdeaProject/stock-analyst/report/calculator_attack_surface.md)

Main findings:

- the calculator only uses a small set of numeric aggregates
- some fields in the screening schema do **not** move the final rating
- near-boundary cases are much easier to attack than far-from-boundary cases

This mechanistic layer is one of the strongest parts of the project.

It elevated the work above “we tried some prompts and recorded what happened.”

## 8.3 Static `struq-lite` defense

Main static defended artifact:

- [summary.json](/Users/zanwenfu/IdeaProject/stock-analyst/runs/security-openai-pilot-v5-struqlite-noamzn-v1/struq-lite/summary.json)

Key static result:

- matching-slice baseline ASR: `2 / 9 = 0.2222`
- `struq-lite` ASR on same slice: `0.0`

Interpretation:

- static `struq-lite` produced a real win on the matched no-AMZN slice
- both previously successful AAPL cases were pushed back below the decision
  boundary

This was a valid and useful positive defense result.

## 8.4 Verifier v1 and verifier v2

Main artifacts:

- [verifier_summary.json](/Users/zanwenfu/IdeaProject/stock-analyst/runs/security-verifier-pilot-v1/verifier_summary.json)
- [verifier_v2_evaluation.md](/Users/zanwenfu/IdeaProject/stock-analyst/report/verifier_v2_evaluation.md)

Result:

- v1 failed
- v2 also failed

Important refinement:

v1 failed partly because it behaved like a generic suspiciousness checker.
v2 improved the semantic specificity of the categories, but still failed to
produce an operationally useful threshold.

This makes the verifier family a **strong negative result**, not just a bad
first prompt.

That is actually a valuable outcome for the paper.

## 8.5 Adaptive reattack

Main artifacts:

- [summary.json](/Users/zanwenfu/IdeaProject/stock-analyst/runs/security-adaptive-struqlite-v1-baseline/baseline/summary.json)
- [summary.json](/Users/zanwenfu/IdeaProject/stock-analyst/runs/security-adaptive-struqlite-v1-struqlite/struq-lite/summary.json)

Result:

- adaptive baseline ASR: `0.6667`
- adaptive `struq-lite` ASR: `0.6667`

Interpretation:

- static defense changed which attack worked
- it did not reduce aggregate success on that small adaptive slice

This is one of the most conceptually important results in the project.

Even though the adaptive slice is small, it captures the “attacker moves second”
lesson on a real system.

## 8.6 Repeatability and rigor closure

Main artifacts:

- [defense_repeatability.md](/Users/zanwenfu/IdeaProject/stock-analyst/report/defense_repeatability.md)
- [defense_repeatability_controlled.md](/Users/zanwenfu/IdeaProject/stock-analyst/report/defense_repeatability_controlled.md)
- [native_defense_ablation.md](/Users/zanwenfu/IdeaProject/stock-analyst/report/native_defense_ablation.md)
- [cross_case_attackability.md](/Users/zanwenfu/IdeaProject/stock-analyst/report/cross_case_attackability.md)

This final rigor-closure layer materially changed the interpretation:

- the previously observed AAPL tier-3 wins were **not stable** in fresh
  controlled reruns
- representative damping was driven mainly by:
  - score movement
  - band thresholds
  rather than confidence gating
- AAPL-heavy successes are now quantitatively grounded by boundary distance,
  not just anecdotal

This was the correct final sprint.

It made the project more honest and more difficult to criticize.

---

## 9. What the Results Support

The final evidence strongly supports these claims:

- VYNN’s native architecture provides real defense-in-depth / damping.
- Screening compromise is easier than final recommendation compromise.
- Static attacks can produce end-to-end failures in narrow near-boundary cases.
- Static `struq-lite` helps on a matched slice.
- The verifier family, as implemented here, does not work.
- Static defense evaluation alone is misleading.
- Adaptive pressure can erase a static defense win.
- AAPL-heavy successes are partly predicted by system geometry.

These are strong, coherent, and defensible claims.

---

## 10. What the Results Do **Not** Support

The final evidence does **not** support these stronger claims:

- broad cross-ticker end-to-end breakage
- robust repeatable end-to-end compromise across the benchmark
- a generally effective verifier defense
- comprehensive adaptive robustness conclusions
- strong evidence that confidence gating was the dominant blocker in the key
  worked cases

Avoiding these overclaims will materially improve the final grade.

---

## 11. Biggest Strengths

### 1. Real system, not a toy benchmark

This is the biggest strength.
The project studies a real agentic financial-analysis stack with a real
deterministic decision layer.

### 2. Mechanistic depth

The white-box calculator analysis is a real research contribution at the course
project level.

### 3. Honest negative results

The verifier result is not hidden.
It is investigated, iterated, and retained as a negative result.

### 4. Adaptive evaluation

Most course projects stop at static attacks and static defenses.
This one does not.

### 5. Rigor improved over time

The project repeatedly corrected itself:

- dataset issues were fixed
- stale metrics were replaced
- benchmark governance was added
- repeatability was measured
- final claims were narrowed

That intellectual honesty is a major strength.

---

## 12. Biggest Limitations

### 1. AAPL concentration

This remains the single biggest scientific limitation.

Even though the cross-case analysis now explains *why* AAPL dominates, the
positive end-to-end evidence is still narrow.

### 2. Controlled repeatability weakened the strongest historical wins

The earlier AAPL tier-3 wins remain part of the historical frozen record, but
fresh controlled repeats did not robustly reproduce them.

That weakens any claim of stable attack success.

### 3. Adaptive evidence is still small

The adaptive result is meaningful, but it is based on a small AAPL-heavy slice.

### 4. Verifier remains negative

This is not fatal, but it means the project does not end with a strong stacked
defense story.

### 5. One-poisoned-document threat model

This is a reasonable and controlled threat model, but it is still conservative.
A stronger attacker could poison more of the retrieval context.

### 6. Some final conclusions depend on frozen historical results plus later
closure analysis

This is acceptable if explained clearly, but it does require careful writing.
The report must distinguish:

- frozen core evidence,
- defense-rigor extension,
- final rigor-closure extension.

---

## 13. What Is Still Missing

The project is mostly missing **presentation work**, not research work.

What is still left:

### 1. Final report writing

This is now the main remaining task.

### 2. Tight table and claim selection

The final report must carefully distinguish:

- frozen core evidence
- later rigor supplements

### 3. Final threats-to-validity section

This needs to be explicit and disciplined.

### 4. Small engineering polish only if desired

Optional low-risk polish items:

- clean up the existing `ResourceWarning` from `src/logger.py`
- make sure final scripts / commands for reproducing the main artifacts are
  listed clearly

But importantly:

**no further core experimentation is necessary.**

---

## 14. Recommended Final Framing

The strongest final paper framing is:

1. **Defense 0: native VYNN**
   - real production-style architecture
   - screening compromise does not automatically become recommendation
     compromise

2. **Static attack ladder**
   - increasing attack sophistication
   - narrow but real end-to-end breaks

3. **Mechanistic explanation**
   - architectural damping
   - near-boundary geometry

4. **Explicit defenses**
   - `struq-lite` helps statically
   - verifier family fails

5. **Adaptive evaluation**
   - static robustness overstates true robustness

6. **Rigor closure**
   - repeatability matters
   - some historical wins are unstable
   - AAPL dominance is explainable, not arbitrary

That is a strong, honest, and mature story.

---

## 15. Final Academic Verdict

### Is the project strong?

Yes.

### Is it complete enough?

Yes.

### Is it perfect?

No.

### Is it already strong-A material?

Yes, if the report is written carefully and does not overclaim.

### My realistic grade estimate

- **A- to A**

Closer to **A** if the final report:

- keeps the claims disciplined,
- foregrounds the mechanistic findings,
- explains the negative results well,
- and treats the rigor-closure layer as a strength rather than an embarrassment.

Closer to **A-** if the final report:

- overstates the AAPL successes,
- hides the controlled-repeat instability,
- or presents the defense story as stronger than the data allows.

### Final recommendation

Do **not** reopen the benchmark.
Do **not** chase more attacks.
Do **not** keep trying to rescue the verifier.

Move directly into final report writing with this posture:

> real system, real damping, narrow but meaningful end-to-end failures,
> partial static defense, failed verifier family, adaptive erosion, and a final
> rigor layer that quantifies instability and limitation structure.

That is the strongest version of this project.
