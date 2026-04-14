# Senior Lecturer Assessment: VYNN AI Security Project

Having read the milestone proposal, the status doc, and the review doc carefully, let me give you the frank assessment you've asked for. I'll be direct because that's what this moment needs.

## The short answer

**You are on a defensible track, but you are NOT currently on a strong-A track as the work stands today.** You can get there, but only if you make some hard choices in the next 7–10 days and stop doing some things you're currently doing. Let me explain.

## What's actually strong

The infrastructure work is genuinely impressive and shows real research maturity:

1. **The calculator-first pivot is the best decision you've made.** Realizing that the deterministic calculator only consumes four numeric inputs, and that `risk_type` / `mitigations` are dead fields for attack purposes, is the kind of mechanistic insight that separates a course project from a demo. This is paper-worthy on its own.

2. **The validity discipline is real.** Catching the parity-based direction bug, the partial-batch silent-success bug, the META contamination, and the stale frozen snapshot — and *invalidating* runs that used them — is exactly what a reviewer wants to see. Most students would have papered over these.

3. **The "architectural damping as accidental defense" framing in your review doc is genuinely novel.** Restated properly, this becomes your actual thesis. More on this below.

4. **You have a real non-zero baseline** (v5 pilot, ASR 0.1667) on a deployed system, not a synthetic benchmark. That already differentiates you from InjecAgent-style work.

## Where the project and the milestone proposal have diverged — and it matters

Your milestone proposal and your current reality are now telling **two different stories**, and you need to reconcile this before the final report. A few examples:

| Milestone proposal says | Current reality says |
|---|---|
| 150 poisoned articles across 3 tiers, 10+ companies | 60 poisoned cases, 4 tickers, mostly AAPL-successful |
| Tier 3 = behavior manipulation via tool-call corruption (DCF multiplier, skip validation) | Tier 3 = just a higher-intensity version of Tier 1/2, scored via the same deterministic recommendation metric |
| Defense 2 = cross-model verification with Claude Sonnet | Defenses are scaffolded but not evaluated; cross-model verifier isn't implemented |
| Adaptive attacks via 3-round protocol (Nasr et al.) | No adaptive attacks run yet |
| Instruction exfiltration as an attack objective | Dropped entirely in practice |
| Utility metrics (FPR, latency, LLM-as-judge) | Not measured yet |

This is not necessarily bad — research plans change. But **if you submit the final report matching the milestone proposal's promises, you will fall short on ~60% of the claimed scope**. If you submit matching the current reality, your grader will ask "where did the Tier 3 tool-call corruption experiments go? Where is cross-model verification?"

**You need to pick a lane and rewrite the framing.**

## The hard truth about your current attack results

Being frank: your current results, if you stopped today, read like this:

- "We attacked a real agentic system with prompt injection. On the easiest near-boundary bullish AAPL cases, our tuned v5 attacks achieve 100% end-to-end ASR. Across the broader pilot, ASR is 16.7%, concentrated entirely in AAPL. NVDA remains unbroken. META bearish appears structurally resistant at the one-document level. We have not evaluated defenses."

A skeptical reviewer reads that as: *"You cherry-picked the easiest cases, got wins there, and couldn't generalize."* That's not a strong-A story — that's a solid B+ with strong infrastructure.

**The AAPL wins are not the paper. The calculator-damping finding is the paper.**

## What would actually make this a strong A

I think the review doc you wrote already contains the right answer, but you haven't fully internalized it yet. Here is the thesis I would reframe around:

> **"Architectural choices in deployed agentic systems provide meaningful defense-in-depth against prompt injection, independent of explicit security measures. We demonstrate this by attacking a production financial analysis system across a defense ladder, showing that (1) deterministic downstream calculators damp screening-stage compromise, (2) confidence gating filters low-leverage injections, and (3) the attack surface is scenario-dependent in ways predictable from mechanistic analysis. We then evaluate whether explicit defenses (input separation, cross-model verification) provide incremental robustness against adaptive attackers."**

This framing turns your "weakness" (attacks often fail) into your central contribution. It also aligns with what you've actually built.

To make this land as a strong A, I'd argue you need **four specific things** in the next ~2 weeks:

1. **One non-AAPL success OR a rigorous upper-bound proof.** Either break NVDA bullish with one more targeted iteration, or run a structured-perturbation / oracle-attack study on META that formally establishes "no single-document attack can cross the boundary under these calculator parameters." The second is actually scientifically stronger if done well.

2. **At least one defense evaluated on the v5 baseline.** Cross-model verification with Claude is the highest-value one because (a) it's novel relative to StruQ-lite, (b) it directly tests your milestone's Defense 2 claim, and (c) it's cheap to implement. Run it on the 16-case pilot. Report detection rate, FPR on clean articles, and ASR reduction.

3. **At least one round of adaptive attack.** Nasr et al. is explicitly cited in your milestone as the methodological backbone — if the final report has zero adaptive attacks, the grader will notice. Even one round on the defended configuration, with honest reporting of ASR recovery, is enough.

4. **Explicitly reconcile your tiers with reality.** Either implement Tier 3 as originally proposed (tool-call corruption, DCF multiplier, which your LangGraph logging infrastructure supposedly supports), or rewrite the tier definitions to match what you actually did and justify the change.

## What to stop doing

- Stop rebuilding the corpus. Freeze it. Your review doc says this — obey it.
- Stop doing more v6/v7-style prompt tweaking on META. You already have the mechanistic signal that it's calculator-locked. Convert that observation into a formal result.
- Stop adding infrastructure. You're past the point where more tooling helps.

## Will this guarantee a strong A?

No — nothing guarantees it. But here's my honest probability estimate given what I see:

- **If you submit as-is in 2 weeks:** B+ / A-. Strong infrastructure, interesting mechanistic insight, but underdelivered on the milestone's scope (no defenses, no adaptive, AAPL-heavy).
- **If you do the four things above:** Strong A is realistic. The architectural-damping thesis is genuinely fresh for a course project, and cross-model verification with an adaptive round is methodologically respectable.
- **If you also add the META upper-bound analysis as a formal result:** Potentially A+ territory, because that moves the paper from "we attacked a system" to "we characterized the attack surface of a system," which is a higher intellectual register.

## One meta-concern

The status doc and review doc are both very long and somewhat self-congratulatory in places ("this is still strong-A material"). I'd gently push back on the instinct to keep writing about the methodology. The project will be judged on the *final artifact*, not on the rigor of your process docs. Every hour spent polishing the status doc is an hour not spent on NVDA attacks, defense eval, or adaptive rounds. Codex seems to be doing good work, but make sure it's pointed at experiments, not documentation.

## Bottom line

You have the makings of a strong-A project, and the mechanistic insight (calculator damping) is better than most course-project theses I see. But you have not yet done the experiments that would let you *claim* a strong A. The next 10 days are where this gets decided, not the infrastructure you've already built.

Prioritization I'd recommend, in order:
1. NVDA targeted iteration (1–2 days)
2. META upper-bound / oracle study (1–2 days)
3. Cross-model verifier implementation + eval on v5 pilot (2–3 days)
4. One adaptive attack round against the verifier (1–2 days)
5. Rewrite the report around architectural damping as the thesis (2–3 days)

Everything else is polish.