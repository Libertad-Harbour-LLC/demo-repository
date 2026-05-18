# 0005 — `stars ≥ 100` bypass in dedup filter

**Date:** 2026-05-18. **Status:** Accepted. **Touches:** `trendwatch/trendwatch.py`, `workflows/workflows.py`.

## Context
`_is_worth_showing` originally let an item reach the LLM only if
`is_new=True OR has_new_skills=True OR delta_stars≥5`. A 7k-star repo
seen once and not promoted would never have `delta_stars ≥ 5` (no daily
growth), `is_new` flips to False on day 2, and `has_new_skills` is
False most of the time. Result: high-star skills repos silently
disappeared from analysis forever after their first sighting.

User report: "не верю что нет скиллов с 1000+ звёзд". Inspection showed
nativewind (7833★), atopile (3357★), halfwhey (282★) all in
`state.json` but filtered out before reaching the LLM.

## Decision
Add a fourth condition: `stars ≥ 100 → always pass`. The LLM gets to
re-evaluate the item every day. It still decides `top_test` /
`top_watch` / `top_skip` / `excluded` based on signal — we just stop
hiding the candidate from it.

Threshold rationale: 100 is below most low-signal repos but well
under any "real" skill (typical real Claude Skill repos start at 5k+
once they're known). False positives at 100★ are tolerable.

## Consequences
- ✅ The first cron run after this PR returned **41 ranked items**
  (vs 1 before), with 21 promoted to `top_test`.
- ⚠️ Slightly higher LLM input → ~$0.02 extra per analyzer call.
  Acceptable.
- ⚠️ The LLM sees the same high-star repos every day. Mitigated by
  the `is_recommended` filter — once promoted to `recommended.json`,
  one-shot rule kicks in.

## Alternatives Considered
- **Threshold 500★** (initial fix): too restrictive — atopile (3357★)
  passed but halfwhey (282★) didn't. Tuned to 100.
- **No threshold, always pass non-promoted**: would re-evaluate every
  noise repo daily. LLM cost spike.
- **Time-based: pass items seen >7 days ago**: indirectly correlated
  with star growth but more complex to reason about.
