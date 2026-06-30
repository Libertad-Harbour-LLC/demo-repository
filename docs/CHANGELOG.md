# Changelog

High-level record of notable changes so a fresh session has context.
`CLAUDE.md` is the source of truth for **current** state; this file is the
**history/why**. Newest first.

## 2026-06 — discovery breadth, web catalog, Open Source radar, workflows yield

### Skills discovery broadened beyond coding (PR #48)
- Skill categories 4 → 9 (added content, video, photo, design, webdev) across
  prompt, `index_writer`, `links`, bot `_SKILLS_CATS`.
- Anti-coding-bias rule in the analyzer prompt (domain diversity, don't penalize
  low-star niche skills); category routing rule.
- Broader Reddit subs + domain-targeted `SKILL.md` GitHub code queries.
- Same treatment for the **workflows** pipeline (categories 6 → 9: +video, photo,
  web). `tests/test_search_coverage.py` locks domain coverage.

### Dead discovery channels fixed (PR #49)
- `trendwatch/sources/_http.py`: `get_json_with_backoff` (honours `Retry-After`,
  retries, returns `RATE_LIMITED`); both pipelines' GitHub fetchers delegate to
  it. Code-search queries paced ~7.5s apart, one page per query.
- Legacy `/search/code` does **not** support `OR` → rewrote domain queries as
  single-term (guarded by a regression test).
- Reddit switched to app-only OAuth when creds set (later disabled, see below).
- Optional `GH_SEARCH_TOKEN` preferred over `GITHUB_TOKEN` for search.

### Machine-readable catalog payload + enrichment + auto-push (PR #50, #57, #60)
- `import_payload.py`: builds the `## Import payload` block (completeness:
  joins analyzer output with fetched items so every skill folder is listed).
- `enrich.py`: per-`SKILL.md` batched Claude enrichment → RU description +
  category (from `SKILL_CATEGORY_NAMES`) + tags. `catalog.py`: idempotent POST
  to Supabase ingest (`SKILL_RADAR_INGEST_SECRET`). `--backfill` / `--backfill-file`
  modes + `backfill.yml` workflow. Owner-approved 5 categories added (PR #57).
- Contract: `docs/skill-radar-import-payload.md`.

### Bot fix: private-repo data fetch (PR #58)
- `BOT_REPO` went private → `raw.githubusercontent.com` 404s → bot showed empty.
  `_http_get_json` now routes through the authed GitHub contents API when
  `BOT_GITHUB_TOKEN`/`GITHUB_TOKEN` is set. (Repo later made public.)

### Open Source radar — 3rd pipeline + bot source (PR #59, #60, #61, #62)
- `opensource/` pipeline (every ~3 days): deployable OSS *products* via topic +
  description search + `SEED_REPOS`. New bot source `opensource` (`📦 Open Source`).
- Owner seeds always force-promoted to recommended; awesome-lists dropped from
  the pool (`_looks_like_list`); products-only analyzer bar; watch/recommended
  dedup invariant.

### Workflows low-yield fix (PR #63, #65)
- Root cause (measured funnel): fetch hit the 80-cap (static top-stars), analyzer
  promoted ~2/run. Fixes: `MAX_ITEMS_PER_SOURCE` 80→150 + `_select_with_recency`
  (recency rotation), `ANALYZER_MAX_ITEMS=60`, looser `verified=True` bar
  (`final_score≥5.5`, never skip), broader n8n/Make validators (arrays +
  collections). Result on a real run: worth_showing 32→100, promotions 2→5.
- **Fix 2 (per-workflow catalog):** `_explode_promotions` expands each promoted
  repo into one entry per individual workflow JSON (`list_repo_workflows`, git
  tree, cap 25/repo); repo-level dedup by `repo_full_name`.

### Reddit disabled (PR #66)
- Reddit 403-blocks Actions IPs and needs unmaintained API creds; contributed 0.
  `SOURCES["reddit"] = False` in both configs; removed the unused
  `REDDIT_CLIENT_ID/SECRET` CI passthrough. `reddit.py` kept dormant.

### Other
- `.claude/skills/superflow/` installed (autonomous dev workflow skill).
- `auto-assign.yml` (`pozil/auto-assign-issue`) fails on every PR with
  "Couldn't find issue info in current context" — **pre-existing, unrelated**,
  non-required check; safe to ignore when merging (or fix separately).
