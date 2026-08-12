# CLAUDE.md

Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:

- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:

- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:

- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:

- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:

```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.

---

## Project-specific rules

The objective and the phase definitions for this repository live in
[`docs/ROADMAP.md`](docs/ROADMAP.md). Read it before starting work.

This repository makes measured claims about cost and latency. Rules on top of the above:

- **Never invent a number.** Every figure quoted in the README, in a docs page, or in a commit
  message must come from a committed artifact under `results/`, produced by a script in
  `benchmarks/`. If a run has not happened yet, say so instead of estimating. Gas schedule
  constants cited as design rationale are not results and must be labelled as rationale.
- **Gas is deterministic, so reproducibility is exact.** A benchmark re-run on the same contract
  bytecode and the same input trace must produce identical gas columns. If it does not, that is a
  bug in the harness, not noise to average away.
- **Any contract change is a re-benchmark.** Gas numbers in the README are tied to specific
  bytecode. Changing the contract without re-running `make bench` leaves the README lying.
- **Tamper evidence is the product.** Any change to the Merkle tree, proof generation, or the
  verification path requires a test that mutates a committed record and asserts verification
  fails. A proof path that cannot fail is not a proof path.
- **New infrastructure needs a measurable claim.** Do not add a service, a chain, a queue, or a
  storage layer unless it unlocks a number that goes in `results/`. Infrastructure that only adds
  boxes to the architecture diagram is a cut, not a feature.
- **ML claims require a baseline.** No model metric is reported without the naive baseline it beats
  on the same held-out split, computed by the same script.
