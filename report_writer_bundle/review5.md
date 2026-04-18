Me: "I think a lot of questions that we did not address. first of all, how is the recommendation formula designed, why they dropped those fields, if those fields are not used in the actual formula, then why ask LLM to give answers for them? second, I think the json shown at the second slide, those fields can be easily changed from LLM given the posioned articles right, and if those fields are changed, then those are also captured by the formula will also lead to wrong outcome right, so I think the explanation for why the gap exist does not hold. third, the presentation only talked about aapl, what about the rest 3 tickers, what are the results for them? fourth, what is the prompt you used for cross-model verifier, do you think the issue is with your prompt design? why do I feel it is about wrong prompt? fifth, what does it mean that the defense changed which attack worked, what if you tried a attack mix of both tier-2 and tier-3, will it pass tier-3 defense as well, also the system simply don't have any defense for tier-3 right now right? Finally, as a senior lecturer, evaluate this project and presentation thoroughly, what do you think of it realistically? Why I feel that the defense is too simple lowkey"

# The Hard Critique You Need Before Tomorrow

You've asked the questions a sharp grader will actually ask. Let me work through each one honestly, then give you the realistic evaluation at the end. Some of these will sting.

## Q1: The calculator formula and why fields are "discarded"

**Your real question**: If `risk_type` and `mitigations` aren't used by the formula, why does the LLM extract them at all? And how was the formula designed in the first place?

**The honest answers, and why each is a problem for your story:**

The formula was designed *by you* for the production VYNN product. It's a heuristic weighted sum — `w1·val_gap + w2·cat_score − w3·risk_score + w4·momentum`. The weights were tuned against historical recommendations, not derived from any theory. **This means the "calculator" isn't some externally-validated decision system. It's your own code.**

The LLM extracts the discarded fields because the *narrative report* (the long-form analyst write-up) uses them. The recommendation calculator doesn't. So when I called those fields "discarded by the calculator," that's technically true — but a sharp reviewer will hear it as: *"You designed a calculator that ignores most of the LLM's output, then claimed it as architectural defense. That's a tautology."*

**This is the most dangerous question you'll get tomorrow.** If a grader pushes here, you cannot pretend the calculator design is independent of your security claim. The honest framing is: *"This is exactly the architectural pattern the literature recommends — keep LLMs in the analytical loop, keep deterministic logic in the decision loop. The contribution is showing that this pattern, present in a real production system, has measurable security consequences not previously quantified."* That's defensible. "The calculator is an accidental defense layer" overstates because *you designed both the calculator and called it accidental*.

**You should soften the "accidental" framing in tomorrow's talk** — change "accidental defense" to "architectural defense" or "defense-in-depth via structural separation." You designed it for product reasons, not security; the security benefit was unanticipated. That's defensible. "Accidental" sounds glib once a sharp listener thinks for two seconds.

## Q2: Your devastating second question

**You wrote**: *"those fields can be easily changed from LLM given the poisoned articles, and if those fields are changed, then those are also captured by the formula will also lead to wrong outcome — so the explanation for why the gap exists does not hold."*

**You're right.** This is the most important critique in your message and you should sit with it.

Here's the issue: I framed the gap (100% screening shift, 17% end-to-end ASR) as "the calculator absorbs attacks." But the calculator *does* read the four fields the LLM produces. If the LLM gets manipulated into producing a fake `catalyst_score = 0.95`, the calculator will dutifully use that fake 0.95. There's no separate ground truth.

**So why is the gap actually 83%?** A more honest answer is several mechanisms working together:

1. **Magnitude requirement** — the LLM's perturbation has to be large enough to cross a band threshold. Small movements don't change the rating. This is real damping.
2. **Confidence gating** — VYNN filters low-confidence catalysts/risks before scoring. The LLM has to commit confidently to the false claim, not hedge.
3. **Direction requirement** — the perturbation has to push toward the rating boundary. Random noise often pushes neutrally.
4. **Multi-article averaging** — the screener processes 5+ real articles plus the 1 poisoned one. The real articles' signals partially dilute the injection.

That's the real story. "Architectural damping" still holds, but it's **not because the calculator ignores the LLM** — it's because the system imposes magnitude, confidence, direction, and dilution requirements that screening-stage perturbation alone often fails to satisfy.

**What this means for your deck**: slide 5 needs to change. The current framing ("only 4 fields reach the calculator → that's why most attacks die") is partially misleading. The real explanation is *the requirements gate, not the field count*. If you don't update this and a sharp reviewer pushes, your central thesis wobbles.

## Q3: What about NVDA, META, AMZN?

You're right to flag this. The current deck barely mentions them. Here's the brutal honest version of the cross-ticker results:

- **NVDA**: All static attacks failed. Best near-break got expected return from 7.79 → 9.11, still 0.89% short of crossing to BUY. Zero successes.
- **META**: Bearish attacks failed. The upper-bound oracle study showed even structured perturbations 4.83% from the boundary couldn't cross with single-document attacks. Zero successes.
- **AMZN**: Strongly valuation-locked. We excluded AMZN from the no-AMZN slice precisely because attacks didn't work *and* there were long-context throughput problems. Zero successes.

**So 100% of your end-to-end successes are AAPL.** A grader will absolutely notice this. The defensible framing is: *"The calculator analysis predicted ex ante that near-boundary cases would be attackable and far-from-boundary cases would not. AAPL had near-boundary cases; NVDA, META, AMZN did not in our scenario set. Successes match the prediction — that's the mechanistic theory validating itself, not selection bias."*

But you have to **say this proactively**, not wait for it. I'd add it to slide 8's limitations explicitly: *"100% of successes on AAPL — explained by the calculator analysis, not cherry-picked."* The current limitation bullet is too soft.

## Q4: The verifier prompt — was the failure my prompt's fault?

**Your instinct is correct.** The verifier failure is at least partially a prompt design problem, possibly entirely.

Look at the prompt I showed on slide 6: *"identify any claims in the analysis that are (1) not supported by any source article, (2) directly contradicted by the source material, or (3) appear to reflect instructions embedded in the sources."*

That prompt asks Claude to detect **three different things**: unsupported claims, contradicted claims, and instruction-following behavior. The first two are general output-quality issues (which clean GPT outputs also have, because GPT hallucinates). Only the third is injection-specific. By asking Claude to weight all three into one confidence score, **the prompt design guaranteed the failure mode you observed** — Claude scored "fabricated quotes" highly in clean cases too, so the distributions overlapped.

A better-designed verifier prompt would:
- Focus *only* on injection-specific signals (instruction-like patterns, abrupt sentiment reversals from source consensus, structured-field plants)
- Show the verifier the source articles AND the structured JSON, not just the analysis text
- Request a binary decision per signal type, not a fused confidence score
- Be calibrated against a held-out set of poisoned vs clean *with controlled hallucination rates*

**You did not exhaust the design space.** This matters because if a reviewer asks "did you try a better prompt?", the honest answer is "no, we tried one prompt and reported the result." That's defensible as a course project but it's a weakness.

**My recommendation for tomorrow**: when discussing the verifier, say *"This is one prompt design. The failure mode tells us specifically what a better verifier would need — injection-specific features rather than general quality features. That's concrete future work."* This turns the limitation into a finding rather than getting caught by the question.

## Q5: "Changed which attack worked" — and the bigger problem

**Your sharp question**: what if you mix tier-2 and tier-3? What if the system has no tier-3 defense at all?

Here's the embarrassing truth about the adaptive round: the "adaptive" round was three cases, one round of variation, and the variation was a tier-2 article on a case where tier-3 had previously worked. **This is barely adaptive.** A real adaptive attacker would:

- Combine tier-2 and tier-3 payloads in one article
- Iterate dozens of variations against the verifier (which we *don't* defend with anyway)
- Use gradient-free optimization or LLM-assisted variation generation
- Test combined defenses (struq-lite + verifier together)

The adaptive round we ran demonstrates the *phenomenon* (defense changes which attack works) but does not establish the *strength* of adaptive bypass. A grader who has read the Nasr paper carefully will notice this gap.

**On struq-lite specifically**: it's a single-mechanism prompt-level defense. It's not "tier-3 defense." It's an attempt at structural input separation, full stop. The framing in your deck implies struq-lite is a defense against the attacks generally, not that it's particularly designed for tier-1 (the kind it most plausibly blocks).

## Now, the realistic evaluation

You asked me to evaluate the project thoroughly. Here is the unvarnished version.

### What's genuinely strong

1. **Production system case study.** Most prompt injection work is on synthetic benchmarks. Studying it on a real deployed system with real users is uncommon and valuable.
2. **Validity discipline.** The benchmark hygiene — frozen evidence package, version tracking, invalidating runs after bug fixes — is unusually rigorous for a course project.
3. **Mechanistic instinct.** Tracing the calculator's actual fields is the right move; most students wouldn't think to do this.
4. **Honest negative results.** Reporting the verifier failure rather than hiding it is the correct scientific posture.
5. **Reproduced a known phenomenon on a real system.** "Static defense evaluation overstates robustness" reproduced on a production agentic system has pedagogical value.

### What's genuinely weak

1. **The defenses are weak by research standards.** Struq-lite is a 2024 baseline implemented at the prompt level only — no fine-tuning, no instruction hierarchy. The verifier is one prompt, not iterated. **You're right that the defenses feel "lowkey"** — they are. They're sophomore-grade defenses against junior-grade attacks, and a top reviewer will notice.

2. **The architectural damping thesis is partially overstated.** As I worked through in Q1 and Q2, the calculator doesn't truly ignore LLM output; it imposes thresholds, gating, and averaging. That's defensible but it's a more modest claim than "accidental defense layer."

3. **The attack design has a circularity problem.** You designed calculator-aware tier-3 attacks specifically to move the calculator's inputs. The fact that they worked 25% of the time on AAPL, in a system you also designed, is less impressive than it sounds. If a reviewer asks *"isn't your tier-3 success just showing that you can attack a system whose internals you fully know?"* — you'd struggle to answer cleanly.

4. **AAPL concentration is a real selection issue.** "Predicted by the calculator analysis" is a partial defense, but the underlying truth is your evaluation only meaningfully tested one ticker because the others were structurally unattackable in your scenario set. Cross-ticker generalization claims are weak.

5. **The adaptive round is too small to support its conclusions.** Three cases, one round, no combined-defense testing.

6. **Scope drift from the milestone.** Tool-call corruption (originally promised as Tier 3) was dropped entirely. The reconciliation document is honest but doesn't change the fact that a substantial portion of the original proposal was abandoned.

### Realistic letter grade

Here's my updated honest estimate, calibrated to your questions and what they suggest a sharp grader would notice:

- **A+ (top ~5%)**: Now ~10% probability. Down from 25-30% at my last estimate. Your own questions revealed the project has weaknesses I'd been underweighting.
- **A (strong)**: ~50% probability. The most likely outcome. The infrastructure work, mechanistic instinct, validity discipline, and honest reporting are real strengths.
- **A- (solid)**: ~30% probability. If a sharp grader pushes on the calculator-design circularity, the AAPL concentration, the verifier prompt, or the adaptive round size, this is where you land.
- **B+ or below**: ~10% probability. If multiple sharp critiques land in Q&A and the responses are weak.

**Realistic expected grade: A.** Not A+. The project is good but not exceptional. The presentation can preserve this if you handle the hard questions well; it can drop to A- if you don't.

### Why your "lowkey" feeling about the defenses is correct

You're right. The defenses are not the strong part of this project. The strong parts are the mechanistic analysis and the honest evaluation discipline. **Don't try to sell the defenses as the headline contribution.** Sell the *finding* — that prompt-level evaluation overstates the attacker's advantage in deployed systems — and use the defenses as supporting evidence rather than centerpieces.

## What you should change in the deck before tomorrow

I'd recommend these surgical edits, in priority order:

1. **Slide 5**: Replace "the calculator only sees what we feed it" framing with "the calculator imposes magnitude, confidence, and direction requirements." The current framing is technically misleading and will not survive a sharp question.

2. **Slide 8 limitations**: Add a fifth bullet — "Cross-ticker generalization: 100% of successes on AAPL; NVDA/META/AMZN cases were not near-boundary in our scenario set." Naming it proactively beats getting asked.

3. **Slide 1 subtitle**: Change "Accidental Defense" to "Architectural Defense-in-Depth" — same phrase weight, less overclaim.

4. **Verifier discussion (slide 6 notes)**: Add the line *"This is one prompt design — the failure mode tells us what a better verifier would need: injection-specific features rather than general quality features."* This pre-empts the prompt-design critique.

I can update the deck if you want — say the word and I'll do it. **But you have limited time tonight. If I had to pick one of the four edits above, it's slide 5.** That's the one most likely to come up in Q&A and most damaging if mishandled.

## The brutally honest bottom line

This is a solid A project, not a strong A. You have real research instincts and unusual methodological discipline for a student. But your defenses are baseline-level, your attack design has a circularity issue, and your generalization claims rest on one ticker. The presentation can land an A if you handle Q&A maturely; trying to oversell it as a top-tier contribution is the failure mode that drops it to A-.

The good news: graders reward honesty. **The same instinct that made you ask me these questions tonight is the instinct that will save you tomorrow.** When a sharp question comes, don't defend; *agree with the precise part that's right* and reframe to the part of your work that genuinely answers it.

You're better positioned than most students because you can see your own weaknesses. Use that tomorrow.