# trendwatch

Daily digest of fresh AI marketing / vibe-coding items from GitHub, Reddit, X, and Threads, posted to a Telegram chat.

## Setup

1. Create a Telegram bot via [@BotFather](https://t.me/BotFather) and copy the bot token.
2. Send `/start` to your new bot from your personal account (or the group/channel you want digests in).
3. Locally grab your chat_id:

   ```bash
   pip install -r trendwatch/requirements.txt
   TELEGRAM_BOT_TOKEN=xxx python trendwatch/get_chat_id.py
   ```

   Copy the `chat_id` printed for your chat.
4. In the repo, go to **Settings -> Secrets and variables -> Actions** and add:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
   - `APIFY_API_TOKEN` (for X + Threads via Apify actors)
   - `ANTHROPIC_API_KEY` — get one at <https://console.anthropic.com/>. Required for LLM analysis; without it the bot falls back to the legacy link-list mode automatically.
5. Trigger the workflow manually the first time: **Actions -> trendwatch -> Run workflow**.
6. Verify the digest message arrived in your Telegram chat.
7. Tune `trendwatch/config.py` to taste — keywords, subreddits, GitHub topics, source toggles.

## Sources

- **GitHub** and **Reddit** use free public APIs (no Apify credits burned).
- **X** and **Threads** use Apify actors. To swap actors, edit `APIFY_TWITTER_ACTOR` / `APIFY_THREADS_ACTOR` in `trendwatch/config.py`. Actor input shapes vary between authors — if a source returns 0 items, check the actor's input schema in the Apify console and adjust the POST body in `trendwatch/sources/twitter.py` or `threads.py`.

## How analysis works

The pipeline now has an LLM analysis step between the fetchers and Telegram:

1. **Python preprocesses** — fetchers pull items from GitHub / Reddit / X / Threads, `normalizer.py` extracts candidate tool names and counts cross-source mentions, `state.py` diffs against `digests/state.json` (committed back by CI) to flag new items and stargazer/score growth since yesterday.
2. **Claude scores and ranks** — `analyzer.py` sends the preprocessed data to `claude-sonnet-4-6` (override via `TRENDWATCH_MODEL`). The long system prompt is sent with `cache_control: ephemeral` so subsequent runs hit the prompt cache. The model returns strict JSON: rankings, top_test / top_watch / top_skip, a best pick, and a Russian Telegram summary.
3. **Outputs** — the full report is written to `digests/YYYY-MM-DD.md` (committed back by the workflow) and the `telegram_summary` field is sent to Telegram via `send_text` (plain text, no MarkdownV2 escaping needed).

If the Anthropic API call or JSON parse fails for any reason, the orchestrator falls back to the original "list of links" digest so a daily message still goes out. Look for `[ANALYSIS_OK]`, `[FALLBACK_LINKS]`, or `[DRY_RUN]` in the workflow logs to see which path ran.

## Local dry-run

```bash
python trendwatch/trendwatch.py --dry-run       # no API calls; prints stubbed messages
python trendwatch/trendwatch.py --no-analyzer   # skip LLM; send legacy link digest
python trendwatch/trendwatch.py                 # full LLM pipeline (needs ANTHROPIC_API_KEY)
```

`--dry-run` does not require any Telegram secrets. `--no-analyzer` skips the analyzer and state I/O entirely and is useful if you want to bypass the LLM for a one-off run.

## Troubleshooting

- **401 Unauthorized from Telegram** — wrong `TELEGRAM_BOT_TOKEN`.
- **"chat not found"** — wrong `TELEGRAM_CHAT_ID`, or the bot was never `/start`-ed from that chat.
- **Apify 402 Payment Required** — Apify account is out of credits. Top up or disable `twitter`/`threads` in `config.SOURCES`.
- **Apify run-sync timeout** — actor took >240s. Lower `MAX_ITEMS_PER_SOURCE` or pick a faster actor.
- **GitHub 403 rate limit** — set the `GITHUB_TOKEN` env var (the workflow already wires the default token).
- **Empty digest every day** — relax `REDDIT_MIN_SCORE` or broaden `GITHUB_TOPICS` / `KEYWORDS`.
