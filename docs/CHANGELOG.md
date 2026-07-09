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

### skills.sh source + tree-wide skill discovery + frontmatter (PR #71)
Borrowed from studying `vercel-labs/skills` (the `npx skills` CLI + skills.sh
registry):
- **New source `skills_sh`** — queries `skills.sh/api/search` per domain term;
  results carry **install counts** (real usage telemetry from CLI installs).
  `merge_installs` folds the count onto the GitHub twin item (one repo = one
  digest item); registry-only repos stay standalone. Analyzer prompt: installs
  outrank stars for traction (≥100→6+, ≥1000→8+, ≥500→confidence high).
- **Tree-wide verification** — `_skill_folders_from_tree` replaces the
  `.claude/skills`-only contents probe: one recursive git-tree call finds every
  `SKILL.md` (case-insensitive) incl. `skills/<cat>/<skill>/` catalogs,
  cross-agent dirs (`.agents/.codex/.opencode/.github/.windsurf` + 5 new code
  queries), root-level skills. Same request cost, cap 50/repo.
- **Frontmatter fallback** — `parse_frontmatter` (no YAML dep) extracts
  `name`/`description` from SKILL.md before the LLM; author's description
  ships if the Claude call fails; hint passed into the enrichment prompt.
  `raw_skill_md_url` now also accepts blob URLs (root-level skills).
- Product ideas noted, not implemented: install-count telemetry for our own
  catalog, `.well-known/skills` (agentskills.io) as a future non-GitHub source.

### Workflow catalog cards — 4 metadata fields + automation ingest (PR #68)
- The site's «Шаблоны автоматизаций» now renders our workflows alongside the n8n
  library as identical chip cards. Each `digests/workflows/recommended.json`
  entry gained 4 optional, backwards-compatible fields: `node_count`,
  `complexity` (simple≤5 / medium 6–15 / complex>15 — n8n-library thresholds),
  `integrations` (real services from node types / Make module prefixes; generic
  control/protocol nodes excluded), `trigger_type`.
- `workflows/wf_meta.py` — pure extractor (n8n `nodes` + Make `flow`/`modules`),
  `merge` across a repo's workflows, `fields_for` omit-empty rules.
  `workflows/wf_enrich.py` — fetches each entry's JSON(s) and writes the fields
  (injectable seam). `workflows/catalog.py` — idempotent POST of the whole
  `recommended.json` to `…/ingest-automation-workflows` (`x-automation-secret`,
  env `AUTOMATION_INGEST_SECRET`).
- Wired into the pipeline: new promotions are enriched + the DB is pushed each
  run. One-time/operator retrofit of existing entries via
  `workflows.py --backfill-meta`. Categories are now free-form `<slug>_workflow`
  (site auto-creates unknown ones). `tests/test_wf_meta.py` locks thresholds,
  service naming, trigger detection, omit rules, and the push guard.

### Reddit disabled (PR #66)
- Reddit 403-blocks Actions IPs and needs unmaintained API creds; contributed 0.
  `SOURCES["reddit"] = False` in both configs; removed the unused
  `REDDIT_CLIENT_ID/SECRET` CI passthrough. `reddit.py` kept dormant.

### Other
- `.claude/skills/superflow/` installed (autonomous dev workflow skill).
- `auto-assign.yml` (`pozil/auto-assign-issue`) fails on every PR with
  "Couldn't find issue info in current context" — **pre-existing, unrelated**,
  non-required check; safe to ignore when merging (or fix separately).
