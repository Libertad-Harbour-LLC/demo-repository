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
5. Trigger the workflow manually the first time: **Actions -> trendwatch -> Run workflow**.
6. Verify the digest message arrived in your Telegram chat.
7. Tune `trendwatch/config.py` to taste — keywords, subreddits, GitHub topics, source toggles.

## Sources

- **GitHub** and **Reddit** use free public APIs (no Apify credits burned).
- **X** and **Threads** use Apify actors. To swap actors, edit `APIFY_TWITTER_ACTOR` / `APIFY_THREADS_ACTOR` in `trendwatch/config.py`. Actor input shapes vary between authors — if a source returns 0 items, check the actor's input schema in the Apify console and adjust the POST body in `trendwatch/sources/twitter.py` or `threads.py`.

## Local dry-run

```bash
python trendwatch/trendwatch.py --dry-run
```

Prints the composed Telegram message(s) to stdout without sending. Telegram secrets are not required for dry-run.

## Troubleshooting

- **401 Unauthorized from Telegram** — wrong `TELEGRAM_BOT_TOKEN`.
- **"chat not found"** — wrong `TELEGRAM_CHAT_ID`, or the bot was never `/start`-ed from that chat.
- **Apify 402 Payment Required** — Apify account is out of credits. Top up or disable `twitter`/`threads` in `config.SOURCES`.
- **Apify run-sync timeout** — actor took >240s. Lower `MAX_ITEMS_PER_SOURCE` or pick a faster actor.
- **GitHub 403 rate limit** — set the `GITHUB_TOKEN` env var (the workflow already wires the default token).
- **Empty digest every day** — relax `REDDIT_MIN_SCORE` or broaden `GITHUB_TOPICS` / `KEYWORDS`.
