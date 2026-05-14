# demo-repository

## Project Overview
Container repo housing automation utilities. Current active feature: **trendwatch** —
daily GitHub Actions job that scans for **new Claude Code Skills** (in the format
`.claude/skills/<name>/SKILL.md`) across GitHub (code search + topic search), Reddit
(with keyword post-filter), and X/Threads (disabled by default), runs Claude analysis,
and posts a scored Telegram digest with test plans.

## Key Files
| File | Purpose |
|------|---------|
| `trendwatch/trendwatch.py` | Orchestrator: fetch → state/delta → normalize → analyzer → report → Telegram |
| `trendwatch/analyzer.py` | Anthropic SDK wrapper, prompt caching, JSON parsing, `claude-sonnet-4-6` default |
| `trendwatch/prompts.py` | SYSTEM_PROMPT (Russian, cached) + USER_PROMPT_TEMPLATE |
| `trendwatch/state.py` | `digests/state.json` read/write + delta computation |
| `trendwatch/normalizer.py` | Cross-source tool-name aggregation (KNOWN_TOOLS + alias map) |
| `trendwatch/report.py` | JSON analysis → Markdown for `digests/YYYY-MM-DD.md` |
| `trendwatch/telegram_client.py` | `send_text` (LLM mode) + `send_digest` (fallback links) |
| `trendwatch/skill_db.py` | Persistent skill DB (`recommended.json` + `watchlist.json`) — one-shot recommendations + signal-based graduation |
| `trendwatch/index_writer.py` | Generates Markdown indexes in `digests/index/` (all / by_category / by_month) |
| `trendwatch/links.py` | Builds public github.com URLs to the indexes for the Telegram footer (reads `GITHUB_REPOSITORY`) |
| `trendwatch/sources/{github,reddit,twitter,threads}.py` | Per-source fetchers |
| `trendwatch/get_chat_id.py` | One-shot helper to capture Telegram chat_id |
| `trendwatch/config.py` | Keywords, subreddits, source toggles, `GITHUB_CODE_QUERIES`, `REDDIT_KEYWORDS_FILTER`, `VERIFY_GITHUB_SKILLS` |
| `trendwatch/requirements.txt` | `requests`, `anthropic>=0.40` |
| `.github/workflows/trendwatch.yml` | Daily cron 09:00 UTC + commit-back of `digests/` |
| `digests/` | Committed daily reports (`YYYY-MM-DD.md`) and `state.json` snapshot |
| `index.html` / `package.json` | Legacy GitHub demo files |

## Commands
- `pip install -r trendwatch/requirements.txt` — install deps
- `python trendwatch/get_chat_id.py` — print chat_ids that messaged the bot
- `python trendwatch/trendwatch.py` — full pipeline (analyzer + Telegram)
- `python trendwatch/trendwatch.py --dry-run` — fetch + print, no API calls
- `python trendwatch/trendwatch.py --no-analyzer` — links-only fallback (no Anthropic)

## Secrets (GitHub repository secrets)
- `APIFY_API_TOKEN` — Apify token for X/Threads scrapers
- `TELEGRAM_BOT_TOKEN` — bot token from @BotFather
- `TELEGRAM_CHAT_ID` — destination chat for digests
- `ANTHROPIC_API_KEY` — Claude API key from console.anthropic.com

## Conventions
- Secrets never committed; read from env only.
- One Python script per source; orchestrator composes a single Telegram message.
- Failures in a single source must not break the whole run.
- Analyzer failure → fallback to plain-link `send_digest` (marker `[FALLBACK_LINKS]`); state is NOT saved on failure so deltas survive for the next run.
- Model overridable via `TRENDWATCH_MODEL` env (default `claude-sonnet-4-6`); `max_tokens` overridable via `TRENDWATCH_MAX_TOKENS` (default 12000).
- GitHub items are grouped by repo (one digest entry per `repo_full_name`, all skill folders listed in `skills`/`skills_count`).
- Dedupe filter: repos already shown earlier are dropped unless they gained ≥5 stars or have `has_new_skills`. If everything is filtered out → short "no new items" Telegram message (marker `[NO_NEW_ITEMS]`); state is still saved.
- Persistent skill DB: repos promoted to `top_test` are saved to `digests/recommended.json` and EXCLUDED from future digests forever (one-shot recommendation). `top_watch` repos are saved to `digests/watchlist.json` with `signal_to_wait` + baseline metrics; on subsequent runs they graduate back into `top_test` when `delta_stars ≥ 5`, `delta_skills_count ≥ 1`, or `cross_source_count` grew. Watchlist items expire after 30 days. Markdown indexes regenerated to `digests/index/` and linked in the Telegram footer.

<!-- updated-by-superflow:2026-05-14 -->
