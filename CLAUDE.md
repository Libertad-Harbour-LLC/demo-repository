# demo-repository

## Project Overview
Container repo housing automation utilities. Current active feature: **trendwatch** —
daily GitHub Actions job that pulls fresh items from GitHub, Reddit, X, and Threads
about AI marketing / vibe-coding tooling and posts a digest of links to a Telegram bot.

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
| `trendwatch/sources/{github,reddit,twitter,threads}.py` | Per-source fetchers |
| `trendwatch/get_chat_id.py` | One-shot helper to capture Telegram chat_id |
| `trendwatch/config.py` | Keywords, subreddits, source toggles |
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
- Model overridable via `TRENDWATCH_MODEL` env (default `claude-sonnet-4-6`).

<!-- updated-by-superflow:2026-05-14 -->
