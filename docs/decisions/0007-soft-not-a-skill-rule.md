# 0007 — Soft `not_a_skill` rule for verified high-star repos

**Date:** 2026-05-18. **Status:** Accepted. **Touches:** `trendwatch/prompts.py`, `trendwatch/analyzer.py`.

## Context
The analyzer's `not_a_skill` exclusion category was strictly enforced:
"если это просто AI-проект, библиотека, агент-фреймворк — не Skill,
не ранжируй в top_test/top_watch/best_pick". This is technically
correct (a UI library that ships a SKILL.md is not itself a Skill).
But it caused observable user pain: repos with verified `.claude/skills/`
directories AND huge star counts (Anytype 7k★, nativewind 7k★,
mksglu/context-mode 14k★) were silently excluded — user couldn't tell
why the digest was empty.

## Decision
Two layers, belt + suspenders:

**Layer 1 — prompt softening.** Narrow exception to `not_a_skill`:
if `verified=True AND stars ≥ 1000`, the LLM MUST place the repo in
`top_watch` with a note like "N skills inside an X-project". The
LLM still uses discretion for low-star noise.

**Layer 2 — Python guard.** `_inject_also_considered_tail` scans
`items_with_deltas` for repos with `stars ≥ 500` that don't appear
in `top_test/top_watch/best_pick`. If any, the orchestrator appends
a "🔍 Также рассмотрены, но не продвинуты" section to the Telegram
summary listing top 5 by stars. Skipped if the LLM already emitted
a 🔍 section.

## Consequences
- ✅ User now sees what was evaluated even when the LLM is
  conservative. No more "looks broken" digests.
- ✅ Code-enforced (Python), not prompt-only — per skill principle:
  "do not rely on prompt text for safety that must be enforced by code".
- ⚠️ Slight `top_watch` inflation. Real estate cost in Telegram message
  is ~10 lines. Acceptable.

## Alternatives Considered
- **Loosen the `_is_worth_showing` Python filter only**: ADR 0005;
  necessary but not sufficient — the LLM still excluded items.
- **Drop the `not_a_skill` rule entirely**: would promote actual
  non-skills (random projects with a `.claude/skills/` dir for
  unrelated reasons).
- **Mandate top_skip mention with reason in Telegram**: LLM-side
  rule, weaker guarantee. Python tail injection is stricter.
