Alright, putting on the senior ML research engineer hat. Here's what I'd actually tell Codex if this were my project at Anthropic or OpenAI and I had two weeks of runway.

---

**First, a ruthless diagnosis of where you actually are.**

You have a production-grade evaluation harness and zero scientific results. That is backwards. At a top lab, we'd say you've spent your infrastructure budget and have not started your research budget. The fact that headline ASR is 0.0 after weeks of work is not a "we need better corpus hygiene" problem — it's a "we don't understand the system under attack well enough to attack it effectively" problem.

The specific failure mode is this: Codex has been attacking the LLM's natural language output (the screening summary) while the actual decision-making that matters for end-user harm happens in the deterministic calculator downstream. You are attacking the wrong layer. Every additional corpus rebuild, metric tweak, or governance metadata field is moving further away from the thing that matters.

Let me be direct about what this looks like from the outside. If I were reviewing this project internally, I'd say: the engineer built beautiful scaffolding and then spent six weeks making the scaffolding more beautiful instead of building the building. That's a common failure mode for strong engineers who are not yet senior researchers, and it's fixable if caught now.

---

**The core scientific question you should be asking, but aren't.**

Forget "how do I make my attacks stronger." The real question is: **what does the deterministic calculator actually read from the screening output to produce the recommendation?**

You have a pipeline: `article text → LLM screener → structured JSON → deterministic calculator → recommendation band`. The calculator is a pure function of the structured JSON. If you don't know *exactly* which JSON fields, in what ranges, produce which recommendation band shifts, you are attacking blind. You're throwing adversarial language at the screener and hoping something downstream moves. That's why ASR is 0.0.

A senior researcher would stop everything and do a one-day mechanistic analysis of the calculator. Specifically:

Open the calculator code. Read it. Write down every input field it consumes from the screening JSON. For each field, determine the functional form — is it a weighted sum of catalyst severities? Does it threshold on confidence? Does it aggregate counts? Then, for each of your 20 clean baselines, compute the *minimum* perturbation in each input field that would cross the recommendation band boundary. This gives you a concrete attack target: "for aapl_s05, I need to get the LLM to output at least 2 more high-severity bullish catalysts with confidence ≥ 0.8, or shift the mean risk severity from 0.7 to below 0.4." Now you know what to attack.

This is how a research engineer approaches an adversarial robustness problem. You don't design attacks in the abstract. You reverse-engineer the decision boundary, then design attacks that cross it.

---

**Codex's actual next steps, in execution order.**

**Day 1: Calculator mechanistic analysis.** One engineer-day, no LLM calls. Open the deterministic calculator code. Document every field it reads from the screener JSON and the functional form of each input's effect on the output. Produce a spreadsheet: for each of the 6 dev subset cases, what's the minimum structured-field perturbation needed to cross the recommendation band? This becomes the attack specification document.

**Day 2: Attack redesign against the actual decision boundary.** Forget the "tier 1/2/3" taxonomy from the milestone report for a moment — it's a good framing for the paper but the wrong framing for the research phase. Right now you need attacks that work. Design tier 2 attacks that target specific structured JSON fields: inject article content that causes the screener to emit a specific catalyst type with a specific severity. Design tier 3 attacks that target the risk/confidence distribution. Test each attack on the smallest possible loop: single case, single attack, single screener call, check the JSON, check the calculator output. Do not run benchmarks. Do not touch the harness. Iterate on attack prompts against one case at a time until you get your first non-zero end-to-end success.

**Day 3: Breakthrough confirmation and generalization.** Once you have one success on one case, replicate it on the other 5 dev subset cases. Understand *why* it worked — was it a specific phrasing pattern? A specific structural position in the article? A specific claim type? Codify the working attack pattern into a reusable template. The goal is to get to the breakthrough gate: at least 2 headline ASR successes, at least one from tier 2 or tier 3.

**Day 4: Scaled pilot.** Now run the 16-case pilot on the canonical corpus. If breakthrough attacks generalize, you'll get a meaningful ASR number (target: at least 30% on at least one tier). If they don't generalize, that's itself a scientific finding — attack efficacy is scenario-dependent — and you report it honestly.

**Days 5-7: Defense implementation and evaluation.** Now, and only now, turn on the defense scaffolding that's already half-built. Evaluate Defense 1 (StruQ-lite prompt separation) and Defense 2 (cross-model verification with Claude Sonnet) on the pilot set across the four configurations (none, D1, D2, both). Report ASR for each. This is a one-to-two-day run if parallelism is working.

**Days 8-10: Adaptive attack evaluation.** Take the successful attacks from the baseline breakthrough, and with knowledge of each defense, generate adapted variants using Claude or GPT-4. Run the three-round protocol from the milestone report. Report ASR recovery rates.

**Days 11-12: The cross-model ablation and calculator-as-defense analysis.** Run the small same-model-verifier ablation to decompose the cross-model benefit. Write up the "deterministic calculator as accidental defense layer" finding — this is the most novel contribution of the project and it deserves its own results subsection.

**Days 13-14: Paper writing.** Final report. Main tables, qualitative case studies, discussion.

That's an aggressive but realistic 14-day plan. Notice what's not in it: any more corpus rebuilds, any more metric changes, any more governance metadata work, any more benchmark harness improvements.

---

**Rules of engagement for Codex going forward.**

These are the operating rules I would give Codex explicitly, because without them the infrastructure-polishing pattern will repeat:

The harness is frozen. No code changes to `build_dataset.py`, `run_benchmark.py`, calibration, or scoring logic unless a specific scientific result directly requires it. "I found a potential edge case" is not sufficient justification. "My attack succeeded on 3 cases but failed on 2 because of X" is.

No broad runs until narrow attacks work. Single-case iteration on the dev subset until the breakthrough gate is met. This is the single most important rule because it breaks the "let's run another pilot and see" pattern that has produced 0.0 ASR four times in a row.

Read the calculator code before designing the next attack. If Codex proposes another tier 2 template without citing specific calculator input fields it's targeting, reject the proposal and ask which fields the attack moves.

Timebox everything. "I'm going to spend 4 hours on attack redesign for aapl_s05 tier 2. If I don't have a success by then, I stop and report what I learned." This prevents the indefinite-iteration failure mode.

---

**The finding that actually makes this paper strong.**

Here's the thing I want you to see clearly. Even if you get only modest end-to-end ASR — say, 15-25% on tier 2 — the paper's central finding is already emerging from the current results and it's a *good* finding.

The story is: prompt injection reliably compromises the LLM screening stage (you have 40%+ screening shift rates), but a deterministic downstream calculator substantially damps the damage before it reaches the user. This is the first empirical demonstration, on a real production agentic system, that *architectural* decisions — specifically, keeping critical decisions in deterministic code rather than trusting LLM outputs end-to-end — function as a security layer complementary to prompt-level and model-level defenses.

This framing does three things. It turns your current "we can't get high ASR" problem into a scientific finding. It connects to the course material on defense layering without requiring you to invent new defenses. And it gives VYNN AI a reason to exist in the paper beyond being a testbed — the architectural choice becomes a case study in secure agentic design.

For the paper, this becomes roughly three findings: (1) prompt injection reliably compromises LLM screening in a production agentic pipeline (screening shift rate as evidence); (2) downstream deterministic computation acts as an accidental defense layer (gap between screening shift rate and end-to-end ASR as evidence); (3) explicit defenses — prompt-level input separation and cross-model output verification — provide additional layers that improve robustness further, but adaptive attackers recover some success, consistent with Nasr et al.

This is publishable-caliber framing for a course project. It directly engages with StruQ, DataSentinel, and Attacker-Moves-Second without just replicating their results.

---

**One more thing, as an engineer-to-engineer observation.**

The governance metadata work is technically excellent and I'm not going to tell you to throw it away. But you should recognize that investing that much engineering effort into corpus versioning, run validity labels, and reproduction scripts for a course project is, frankly, overengineering. You don't need another layer of robustness in the benchmark harness. You need one non-zero number.

The best researchers I've worked with have a sharp internal alarm that goes off when they're spending more time on tools than on results. Yours should be going off loudly right now.

Get the calculator analysis done. Get one successful attack. Then let momentum carry you.