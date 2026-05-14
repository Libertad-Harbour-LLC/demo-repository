# demo-repository

## Project Overview
Container repo housing automation utilities. Current active feature: **trendwatch** —
daily GitHub Actions job that pulls fresh items from GitHub, Reddit, X, and Threads
about AI marketing / vibe-coding tooling and posts a digest of links to a Telegram bot.

## Key Files
| File | Purpose |
|------|---------|
| `trendwatch/trendwatch.py` | Main daily scanner |
| `trendwatch/get_chat_id.py` | One-shot helper to capture Telegram chat_id |
| `trendwatch/config.py` | Keywords, subreddits, source toggles |
| `trendwatch/requirements.txt` | Python deps |
| `.github/workflows/trendwatch.yml` | Daily cron at 09:00 UTC |
| `index.html` / `package.json` | Legacy GitHub demo files |

## Commands
- `pip install -r trendwatch/requirements.txt` — install deps
- `python trendwatch/get_chat_id.py` — print chat_ids that messaged the bot
- `python trendwatch/trendwatch.py` — run one digest cycle locally

## Secrets (GitHub repository secrets)
- `APIFY_API_TOKEN` — Apify token for X/Threads scrapers
- `TELEGRAM_BOT_TOKEN` — bot token from @BotFather
- `TELEGRAM_CHAT_ID` — destination chat for digests

## Conventions
- Secrets never committed; read from env only.
- One Python script per source; orchestrator composes a single Telegram message.
- Failures in a single source must not break the whole run.

<!-- updated-by-superflow:2026-05-14 -->
