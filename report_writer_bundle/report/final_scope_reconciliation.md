# Final Scope Reconciliation

Date: 2026-04-14

This note reconciles the milestone proposal with the final implemented VYNN AI
security study. Its purpose is explicit: the project changed scope during
mechanistic investigation, and that change should be documented as a scientific
pivot rather than left implicit.

## 1. Original Milestone Scope

The milestone report described a broader study with three especially ambitious
elements:

- Tier 3 centered on tool-call / DCF behavior manipulation.
- The benchmark target size was 150+ poisoned articles across 10+ companies.
- Adaptive evaluation was framed as a larger multi-round protocol following the
  attacker-moves-second literature.

Those goals were reasonable at proposal time, but the implemented system and
the early benchmark evidence shifted the highest-value attack surface.

## 2. Why Tier 3 Changed

Tier 3 moved from "tool-call / DCF corruption" to "calculator-aware,
case-specific recommendation shift."

This was a deliberate scientific pivot, not a silent scope reduction.

What changed:

- White-box inspection of the deployed VYNN news-analysis path showed that the
  user-visible recommendation is dominated by a deterministic downstream
  calculator.
- The retrieved-news pipeline does not naturally expose a clean, repeatable
  tool-call corruption interface in the way the milestone narrative assumed.
- The strongest realistic retrieved-document attack surface in this repo is not
  arbitrary tool misuse. It is manipulation of the structured screening fields
  that the calculator actually consumes.

Why this is a better final Tier 3:

- It is faithful to the real code path that exists in this repository.
- It targets the exact mechanism that determines end-user recommendation
  outputs.
- It lets the study separate screening compromise from end-to-end compromise,
  which became one of the project’s central findings.

So the final Tier 3 definition is:

- calculator-aware, case-specific poisoning aimed at moving the deterministic
  recommendation boundary through catalyst / risk / sentiment fields that the
  calculator consumes.

## 3. Why the Benchmark Stabilized at 20 Clean + 60 Poisoned

The milestone envisioned a much larger article-level dataset. The final study
stabilized at 20 clean scenarios and 60 poisoned scenarios.

This change was driven by validity and reproducibility constraints:

- Each poisoned case needed a paired clean baseline.
- Each scenario required frozen local artifacts so results would remain stable
  across reruns.
- The most expensive step was not article generation itself; it was the full
  end-to-end news-analysis pass through screening, recommendation, and defense
  evaluation.
- Early iterations surfaced multiple validity issues that had to be fixed
  before scaling:
  - stale keys / paused MongoDB,
  - weak local fallback corpus,
  - parity-based direction-map bug,
  - `META` corpus contamination,
  - overly permissive early metrics.

The 20/60 benchmark was therefore the point where:

- scenario diversity remained meaningful across four tickers,
- paired clean-versus-poisoned evaluation stayed tractable,
- and the frozen artifact set became stable enough for defensible comparison.

This is smaller than the milestone aspiration, but scientifically stronger than
running a larger, less controlled benchmark.

## 4. Why Adaptive Evaluation Narrowed

The milestone framed adaptive evaluation as a broader multi-round protocol. The
final project implements one focused defense-aware adaptive round.

This narrowing happened for two reasons:

- Once the project established that only a subset of near-boundary cases were
  reliably attackable, the highest-value adaptive question became narrow:
  does the best explicit defense (`struq-lite`) retain its static benefit when
  the attacker moves second?
- The first adaptive round already answered the main methodological question:
  the static `struq-lite` win erodes under defense-aware reattack on the
  AAPL slice.

That result directly captures the security lesson from the attacker-moves-second
literature, even though the final course project does not execute a full
three-round adaptive program.

So the final adaptive scope is best understood as:

- Round 1 of a defense-aware adaptive evaluation,
- run on the most informative defended slice,
- sufficient to test whether the positive static defense result survives even
  modest adaptive pressure.

## 5. Why These Pivots Were Scientifically Justified

The scope changes were justified because they improved fidelity to the deployed
system and tightened the causal story of the paper.

The final project now answers a sharper question:

- In a real agentic financial-analysis pipeline with native defense-in-depth,
  how far can retrieved-news prompt injection propagate from screening outputs
  into deterministic recommendation outputs, and do explicit defenses improve
  robustness under adaptive pressure?

That question is narrower than the milestone proposal, but it is more honest
and better aligned with what the repository actually implements.

The key gains from the pivot were:

- a real end-to-end benchmark instead of a loosely specified article corpus,
- a mechanistic explanation for why many screening shifts do not become final
  recommendation shifts,
- one positive explicit defense result,
- one negative explicit defense result,
- one adaptive erosion result,
- and one principled limitation / upper-bound result.

## 6. Final Interpretation

The final project should therefore be read as:

- a controlled, mechanistic study of retrieved-news prompt injection against a
  defended production-style financial analysis system,
- not as a full reproduction of every milestone aspiration.

The milestone served its purpose by identifying the threat model and the
relevant course literature. The final implementation refined that scope around
the attack surface that proved to be both realistic and measurable in VYNN AI.
