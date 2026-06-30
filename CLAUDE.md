# demo-repository

## Project Overview
Container repo housing automation utilities. Three active tracking pipelines:

1. **trendwatch** — daily GitHub Actions job (09:00 UTC) that scans for **new
   Claude Code Skills** (`.claude/skills/<name>/SKILL.md`) across GitHub
   (code search + topic search). Runs Claude analysis, posts a scored Telegram
   digest, **enriches each promoted skill** (`enrich.py`: reads each SKILL.md →
   Russian description + category + tags) and **auto-pushes** the result to the
   web catalog (`catalog.py` → Supabase ingest). Reddit/X/Threads sources exist
   but are **disabled**. Also supports a **`--backfill`** mode (enrich + push
   arbitrary repos).
2. **workflows** — second pipeline (12:00 UTC) that scans for **ready-made n8n
   and Make workflows** (JSON files importable directly) across GitHub
   (n8n + Make topics, code search for workflow JSON signatures). Reuses
   trendwatch primitives (`analyzer`, `state`, `skill_db`, `telegram_client`,
   `index_writer`, `links`, `report`) and writes all artifacts to
   `digests/workflows/`. Same Telegram chat as skills. Reddit source disabled.
3. **opensource** — third pipeline (~every 3 days, 10:00 UTC) that scans GitHub
   for **ready-to-use / self-hostable open-source products & platforms** (whole
   repos, NOT skills/workflows: deploy as-is, rebrand + attach API, or
   vibe-code on top). Topic + name/description/readme search + a seed list of
   example repos. Reuses trendwatch primitives; artifacts to
   `digests/opensource/`. Same Telegram chat; header `🧩 Open Source Radar`.
   Bot source `opensource` (button `📦 Open Source`).

> Change history & rationale: [`docs/CHANGELOG.md`](docs/CHANGELOG.md). Bot
> UI/data glossary: [`CONTEXT.md`](CONTEXT.md). Catalog contract:
> [`docs/skill-radar-import-payload.md`](docs/skill-radar-import-payload.md).

## Key Files
| File | Purpose |
|------|---------|
| `trendwatch/trendwatch.py` | Orchestrator: fetch → state/delta → normalize → analyzer → report → Telegram |
| `trendwatch/analyzer.py` | Anthropic SDK wrapper, prompt caching, JSON parsing, `claude-sonnet-4-6` default |
| `trendwatch/prompts.py` | SYSTEM_PROMPT (Russian, cached) + USER_PROMPT_TEMPLATE |
| `trendwatch/state.py` | `digests/state.json` read/write + delta computation |
| `trendwatch/normalizer.py` | Cross-source tool-name aggregation (KNOWN_TOOLS + alias map) |
| `trendwatch/report.py` | JSON analysis → Markdown for `digests/YYYY-MM-DD.md` (+ embeds the `## Import payload` block) |
| `trendwatch/import_payload.py` | Builds the machine-readable `## Import payload` (catalog contract); category dictionary + normalization |
| `trendwatch/enrich.py` | Per-skill enrichment: reads each `SKILL.md`, batched Claude call → Russian `description` + `category` + `tags` |
| `trendwatch/catalog.py` | Idempotent POST of the Import payload to the web-catalog ingest endpoint (`x-radar-secret`) |
| `trendwatch/telegram_client.py` | `send_text` (LLM mode) + `send_digest` (fallback links) |
| `trendwatch/skill_db.py` | Persistent skill DB (`recommended.json` + `watchlist.json`) — one-shot recommendations + signal-based graduation |
| `trendwatch/index_writer.py` | Generates Markdown indexes in `digests/index/` (all / by_category / by_month) |
| `trendwatch/links.py` | Builds public github.com URLs to the indexes for the Telegram footer (reads `GITHUB_REPOSITORY`) |
| `trendwatch/sources/{github,reddit,twitter,threads}.py` | Per-source fetchers (only `github` enabled) |
| `trendwatch/sources/_http.py` | Shared GitHub GET helper: `get_json_with_backoff` (429/Retry-After aware) + `build_github_headers` (prefers `GH_SEARCH_TOKEN`); used by both pipelines' fetchers |
| `trendwatch/get_chat_id.py` | One-shot helper to capture Telegram chat_id |
| `trendwatch/config.py` | Keywords, subreddits, source toggles, `GITHUB_CODE_QUERIES`, `REDDIT_KEYWORDS_FILTER`, `VERIFY_GITHUB_SKILLS` |
| `trendwatch/requirements.txt` | `requests`, `anthropic>=0.40` |
| `.github/workflows/trendwatch.yml` | Daily cron 09:00 UTC + commit-back of `digests/` |
| `.github/workflows/workflows.yml` | Daily cron 12:00 UTC + commit-back of `digests/workflows/` |
| `digests/` | Committed daily reports (`YYYY-MM-DD.md`), `state.json`, `recommended.json`, `watchlist.json`, `index/` |
| `workflows/workflows.py` | Workflows orchestrator (n8n + Make pipeline) — reuses trendwatch primitives via import |
| `workflows/config.py` | Workflows keywords, topics, code queries, subs, paths under `digests/workflows/`, `CATEGORIES`, `TOOLS` |
| `workflows/prompts.py` | Workflows SYSTEM_PROMPT (Russian, cached) — n8n/Make-focused schema |
| `workflows/normalizer.py` | Cross-source aggregation with workflow-specific `KNOWN_TOOLS` (wraps `trendwatch.normalizer`) |
| `workflows/sources/{n8n_github,make_github,reddit}.py` | Per-source fetchers; both GitHub fetchers share `_github_common.py` (`fetch_workflows`, `list_repo_workflows` for Fix-2 explosion, `_select_with_recency`) |
| `digests/workflows/` | Workflows-pipeline reports (`YYYY-MM-DD.md`), `state.json`, `recommended.json`, `watchlist.json`, `index/{all,by_category,by_tool,by_month}` |
| `opensource/opensource.py` | Open Source radar orchestrator (deployable-OSS-products pipeline) — reuses trendwatch primitives |
| `opensource/config.py` | OSS topics, description queries, `SEED_REPOS`, paths under `digests/opensource/`, `CATEGORIES` (`*_oss`) |
| `opensource/prompts.py` | Open Source SYSTEM_PROMPT (Russian, cached) — "ready-to-use product vs library" schema |
| `opensource/sources/github.py` | Repo-level discovery: topic + name/description/readme search + seed injection |
| `opensource/normalizer.py` | Cross-source aggregation wrapping `trendwatch.normalizer` with OSS vocabulary |
| `digests/opensource/` | Open Source pipeline reports + `state.json`, `recommended.json`, `watchlist.json`, `index/` |
| `.github/workflows/opensource.yml` | ~Every-3-days cron (10:00 UTC) + commit-back of `digests/opensource/` |
| `.github/workflows/backfill.yml` | Manual `skill-backfill` (workflow_dispatch `urls` input OR push to `.github/backfill-urls.txt`) → `trendwatch.py --backfill` |
| `.github/trigger-{trendwatch,workflows,opensource}` | Sentinel files; a push that edits one runs that pipeline with `--force` (operator trigger from anywhere) |
| `api/telegram.py` | Vercel webhook for the interactive Telegram bot. 4 sources (Claude Skills / N8N / Make / Open Source), category & month browsing, per-item detail, search/random/whatsnew/stats, `🤖 Объясни` (→ `api/llm.py`). Reads data JSONs via authed contents API when `BOT_GITHUB_TOKEN` is set (private repos) |
| `api/llm.py` | One-shot Anthropic call behind the bot's `🤖 Объясни простыми словами` button (prompt-injection-guarded, Haiku default) |
| `docs/skill-radar-import-payload.md` | Contract for the `## Import payload` block (bot side) + enrichment/auto-push/backfill spec |
| `docs/decisions/` | ADRs (0001–0008): Route sum-type, Items deep module, fail-closed admin gate, push-trigger sentinel, etc. |
| `CONTEXT.md` | Bot UI/data domain glossary (Source, Item, Items, View, Screen, Route, deliver, nav_token) |
| `scripts/{cleanup_db.py,llm_smoke_test.py}` | Maintenance helpers (DB cleanup; LLM eval smoke test) |
| `requirements.txt` (root) | Vercel deploy deps (`requests`) — separate from `trendwatch/requirements.txt` |
| `vercel.json`, `.vercelignore`, `bot-README.md` | Vercel deploy config + Russian deploy guide |
| `index.html` / `package.json` | Legacy GitHub demo files |

## Commands
- `pip install -r trendwatch/requirements.txt` — install deps (shared between pipelines)
- `python trendwatch/get_chat_id.py` — print chat_ids that messaged the bot
- `python trendwatch/trendwatch.py` — skills pipeline (analyzer + Telegram)
- `python trendwatch/trendwatch.py --dry-run` — skills fetch + print, no API calls
- `python trendwatch/trendwatch.py --no-analyzer` — skills links-only fallback
- `python workflows/workflows.py` — workflows pipeline (analyzer + Telegram)
- `python workflows/workflows.py --dry-run` — workflows fetch + print, no API calls
- `python workflows/workflows.py --no-analyzer` — workflows links-only fallback
- `python opensource/opensource.py` — Open Source radar (analyzer + Telegram)
- `python opensource/opensource.py --dry-run` — OSS fetch + print, no API calls
- `python trendwatch/trendwatch.py --backfill <repo-url> …` — enrich + push given repos to the web catalog (no analyzer/Telegram)
- `python trendwatch/trendwatch.py --backfill-file urls.txt` — same, URLs from a file

## Secrets (GitHub repository secrets)
- `APIFY_API_TOKEN` — Apify token for X/Threads scrapers
- `TELEGRAM_BOT_TOKEN` — bot token from @BotFather
- `TELEGRAM_CHAT_ID` — destination chat for digests
- `ANTHROPIC_API_KEY` — Claude API key from console.anthropic.com
  (**also required in Vercel env vars** if you use the bot — gates the
  `🤖 Объясни простыми словами` button; without it the button is hidden.
  Check current state at `GET https://<vercel-url>/api/telegram` →
  `llm_enabled` field in the JSON response.)
- `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` — **not used**: the Reddit source
  is disabled (`SOURCES["reddit"] = False` in both configs). Reddit 403-blocks
  Actions IPs and the OAuth route needs creds we don't maintain. To re-enable,
  flip the toggle and set these (script-app creds from reddit.com/prefs/apps).
- `GH_SEARCH_TOKEN` (optional) — classic PAT (`public_repo` scope is enough).
  Used in preference to `GITHUB_TOKEN` for GitHub search; a user PAT has its
  own code-search quota, dodging shared secondary rate limits (429) that
  killed code search on Actions runners.
- `SKILL_RADAR_INGEST_SECRET` (**required for catalog auto-push**) — shared
  secret for the Supabase ingest function; sent as `x-radar-secret`. Without it
  the per-run POST to the web catalog is skipped (digest/Telegram unaffected).

## Vercel bot env vars (set in Vercel project → Settings → Environment Variables)
- `TELEGRAM_BOT_TOKEN` — same bot token as the cron pipeline
- `TELEGRAM_WEBHOOK_SECRET` (optional) — random string; if set, used to validate incoming Telegram POST headers
- `BOT_REPO` (optional, default `Libertad-Harbour-LLC/demo-repository`) — repo to fetch `recommended.json` from
- `BOT_BRANCH` (optional, default `main`)
- `BOT_GITHUB_TOKEN` (**required if `BOT_REPO` is PRIVATE**) — PAT with read
  access to the repo. `raw.githubusercontent.com` returns 404 for private
  repos without auth, so without this the bot reads empty data (all categories
  show 0, lists show «Пусто»). With it, the bot fetches the data JSONs via the
  authenticated GitHub contents API. Falls back to `GITHUB_TOKEN`. Not needed
  for a public repo. Verify via `GET /api/telegram` → `github_read_token_set`.

## Conventions
- Secrets never committed; read from env only.
- One Python script per source; orchestrator composes a single Telegram message.
- Failures in a single source must not break the whole run.
- Analyzer failure → fallback to plain-link `send_digest` (marker `[FALLBACK_LINKS]`); state is NOT saved on failure so deltas survive for the next run.
- Model overridable via `TRENDWATCH_MODEL` env (default `claude-sonnet-4-6`); `max_tokens` overridable via `TRENDWATCH_MAX_TOKENS` (default 12000).
- GitHub items are grouped by repo (one digest entry per `repo_full_name`, all skill folders listed in `skills`/`skills_count`).
- Dedupe filter: repos already shown earlier are dropped unless they gained ≥5 stars or have `has_new_skills`. If everything is filtered out → short "no new items" Telegram message (marker `[NO_NEW_ITEMS]`); state is still saved.
- Persistent skill DB: repos promoted to `top_test` are saved to `digests/recommended.json` and EXCLUDED from future digests forever (one-shot recommendation). `top_watch` repos are saved to `digests/watchlist.json` with `signal_to_wait` + baseline metrics; on subsequent runs they graduate back into `top_test` when `delta_stars ≥ 5`, `delta_skills_count ≥ 1`, or `cross_source_count` grew. Watchlist items expire after 30 days. Markdown indexes regenerated to `digests/index/`.
- Workflows pipeline runs at **12:00 UTC** (skills at 09:00) and uses the **SAME Telegram chat** as skills — separate header (`⚙️ Daily Workflow Radar`). All workflows data lives in `digests/workflows/` and never mixes with the skills DB. The workflows index adds a `by_tool/` grouping (n8n / make / other) on top of the standard all / by_category / by_month layout.
- Workflows discovery tuning: fetch is `MAX_ITEMS_PER_SOURCE=150` selected by `_select_with_recency` (70% top-stars + recency tail, so new low-star workflows aren't truncated); analyzer input capped at `ANALYZER_MAX_ITEMS=60`; `verified=True` workflows promote at a lower bar (`final_score≥5.5`, never `skip`). **Per-workflow catalog (Fix 2):** a promoted repo is exploded by `_explode_promotions` into one `recommended.json` entry per individual workflow JSON (full git-tree enumeration, `EXPLODE_MAX_WORKFLOWS_PER_REPO=25`); the pre-analysis filter excludes already-exploded repos by `repo_full_name`.
- Reuse over duplication: `workflows/` AND `opensource/` import `trendwatch.{state,skill_db,analyzer,telegram_client,index_writer,report,normalizer}` and pass path/category/tool kwargs. The only pipeline-specific code is fetchers, prompts, normalizer vocabulary, and the orchestrator.
- **Skills catalog (`/claude-skills`):** after the skills digest, the report embeds a single machine-readable `## Import payload` JSON block (`import_payload.py`), each promoted skill is enriched (`enrich.py`: per-`SKILL.md` batched Claude call → RU description + dictionary category + tags), and the payload is POSTed to the Supabase ingest endpoint (`catalog.py`, `x-radar-secret`, idempotent upsert by repo slug / skill url). Suggested new categories are surfaced to the owner via Telegram. Category dictionary (`SKILL_CATEGORY_NAMES`, 24 slugs) is the single source of truth — the analyzer/enricher reuse it; new = `status:"suggested"`. Contract: `docs/skill-radar-import-payload.md`.
- **Open Source pipeline:** discovers deployable OSS *products* (not skills/workflows) via topic + description search + `SEED_REPOS` (owner-curated, force-promoted to recommended). `_looks_like_list` drops awesome-lists/link-collections from the pool. Digest header `🧩 Open Source Radar`; bot source `opensource`.
- **Once-per-day idempotency:** each orchestrator records `last_sent_date` in its own `state.json` via `state.mark_sent_today()` after a successful Telegram send. On run start, `state.was_sent_today()` short-circuits before the Anthropic call if the date matches today (UTC). Marker `[ALREADY_SENT_TODAY]`. Manual reruns can bypass with `--force`. This protects the Anthropic API budget against `workflow_dispatch` retries.
- **Daily Telegram messages stay lean:** no "База рекомендованных …" index footer, no "🗑 Пропустить" section. Users browse the DB via the interactive bot (`api/telegram.py`), which merges `recommended.json` + `watchlist.json` items and marks watch entries with 👀. `analyzer.py` post-processes `telegram_summary` to strip any stray 🗑-block the LLM emits from cached prompt memory.

<!-- updated-by-superflow:2026-05-14 -->
