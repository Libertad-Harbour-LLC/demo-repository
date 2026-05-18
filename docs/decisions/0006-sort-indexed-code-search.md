# 0006 — `sort=indexed` in GitHub code search

**Date:** 2026-05-18. **Status:** Accepted. **Touches:** `trendwatch/sources/github.py`, `workflows/sources/_github_common.py`.

## Context
Both pipelines hit GitHub code search with no `sort` parameter →
default `best-match` (relevance). Result: every cron run returned
~the same top-20 SKILL.md / workflow JSON results. New files indexed
in the last 24h never bubbled up. Pipeline output stagnated despite
93k SKILL.md files existing on GitHub.

## Decision
- `sort=indexed&order=desc` → newest indexed first
- `per_page=100` (max for code search) instead of 20
- Pagination 2 pages → up to 200 raw candidates per query
- Multiple queries in config: each runs through this loop

Verified via direct MCP search: same `path:.claude/skills filename:SKILL.md`
query with `sort=indexed` returns repos NOT in DB
(`erikvullings/mithril-ui-form`, `roninjin10/the-only-skill-you-need`, ...)
that the old query missed.

## Consequences
- ✅ End-to-end validated: post-fix run produced **state items: 50**
  (vs 15), **rankings: 41** (vs 1), **promoted: 21** (vs 0).
- ⚠️ GitHub Code Search rate limit: 30 req/min authenticated. Our
  worst case (4 queries × 2 pages) = 8 req/run — well under the limit.
- ⚠️ Verification step (per-repo `/contents/.claude/skills` check)
  now sees more candidates → more API calls. Rate-limited to <5000/hr
  via authenticated GITHUB_TOKEN; ~200 calls/run.

## Alternatives Considered
- **Add `pushed:>since_date` filter to code search**: would skip
  static-but-useful repos that haven't pushed recently. Rejected.
- **Use REST API `/repos/search` instead**: different surface; we
  also use that via `_topic_search`. Both are needed.
- **Cache search results across runs**: would reintroduce the staleness
  problem.
