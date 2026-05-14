# trendwatch

Daily digest of fresh **Claude Code Skills** discovered on GitHub and Reddit, scored by Claude and posted to a Telegram chat.

## What counts as a Claude Skill

A Claude Skill is a folder `.claude/skills/<name>/` containing a `SKILL.md` file. `SKILL.md` holds instructions / context / scripts that Claude Code auto-loads when you work in a repo that ships the folder. Skills are usually distributed through GitHub repositories (often a single repo holding many skills) and occasionally through marketplace listings. trendwatch looks specifically for this layout — a generic AI project, agent framework, or library is **not** a Claude Skill and will be filtered into `excluded.not_a_skill` by the analyzer.

Skills are bucketed into four categories:
- `marketing_skill` — SEO, growth, copy, content distribution, ad ops
- `vibe_coding_skill` — IDE / coding-assistant skills (refactor, debug, scaffolding, code review)
- `ai_content_skill` — content creation (text, video script, image prompt, audio)
- `general_skill` — anything else that fits the SKILL.md format but doesn't match the three above

## Sources in Sprint 3

- **GitHub** — three combined strategies (code search for `path:.claude/skills filename:SKILL.md`, repo search by topics `claude-skill[s]`/`claude-code-skill[s]`, and a description keyword search), all deduped and optionally verified against the repo's `/.claude/skills/` listing.
- **Reddit** — public `new.json` endpoints with a post-filter (`REDDIT_KEYWORDS_FILTER` in `config.py`) so only posts that mention `skill` / `SKILL.md` / `.claude/skills` / `claude skill` survive. `REDDIT_MIN_SCORE` is lowered to 5 because the niche has low traffic.
- **X / Threads** — disabled by default (`SOURCES.twitter = False`, `SOURCES.threads = False` in `config.py`). They are too noisy for this niche and burn Apify credits. Flip the toggle to re-enable, but expect more not_a_skill exclusions.

GitHub Code Search **requires authentication**. The GitHub Actions workflow already wires `GITHUB_TOKEN` for you; for a local dry-run set `GITHUB_TOKEN` manually with at least `public_repo` scope.

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

## Source APIs

- **GitHub** and **Reddit** use free public APIs (no Apify credits burned). GitHub now needs `GITHUB_TOKEN` for code search.
- **X** and **Threads** use Apify actors and are disabled by default. To swap actors when re-enabling, edit `APIFY_TWITTER_ACTOR` / `APIFY_THREADS_ACTOR` in `trendwatch/config.py`. Actor input shapes vary between authors — if a source returns 0 items, check the actor's input schema in the Apify console and adjust the POST body in `trendwatch/sources/twitter.py` or `threads.py`.

## How analysis works

The pipeline now has an LLM analysis step between the fetchers and Telegram:

1. **Python preprocesses** — fetchers pull items from GitHub / Reddit / X / Threads, `normalizer.py` extracts candidate tool names and counts cross-source mentions, `state.py` diffs against `digests/state.json` (committed back by CI) to flag new items and stargazer/score growth since yesterday.
2. **Claude scores and ranks** — `analyzer.py` sends the preprocessed data to `claude-sonnet-4-6` (override via `TRENDWATCH_MODEL`). The long system prompt is sent with `cache_control: ephemeral` so subsequent runs hit the prompt cache. The model returns strict JSON: rankings, top_test / top_watch / top_skip, a best pick, and a Russian Telegram summary.
3. **Outputs** — the full report is written to `digests/YYYY-MM-DD.md` (committed back by the workflow) and the `telegram_summary` field is sent to Telegram via `send_text` (plain text, no MarkdownV2 escaping needed).

If the Anthropic API call or JSON parse fails for any reason, the orchestrator falls back to the original "list of links" digest so a daily message still goes out. Look for `[ANALYSIS_OK]`, `[FALLBACK_LINKS]`, `[NO_NEW_ITEMS]`, or `[DRY_RUN]` in the workflow logs to see which path ran.

## Persistent skill database (Sprint 5)

trendwatch now keeps a memory of every Claude Skill repo it has ever recommended so a single repo never wins the daily slot twice.

- **`digests/recommended.json`** — every repo the analyzer promoted to `top_test` is stored here forever. Before the analyzer runs we filter these URLs out of the input, so a recommended skill is one-shot: once you've been told to test it, it never shows up again.
- **`digests/watchlist.json`** — repos placed in `top_watch` are saved with the model-supplied `signal_to_wait`, baseline metrics (`stars`, `skills_count`, `cross_source_count`), `added_date`, and a 30-day `expires_at`. On each subsequent run we re-check the baselines:
  - `delta_stars >= 5`, `delta_skills_count >= 1`, or a growing `cross_source_count` graduates the item.
  - Graduates are passed back to the analyzer as a separate `graduated_candidates` field; the model is instructed to promote them to `top_test` and explain the promotion using the human-readable `trigger` string (e.g. `stars +12`).
  - Watchlist items past `expires_at` are pruned automatically.
- **`digests/index/`** — browsable Markdown indexes regenerated on every successful run from `recommended.json`:
  - `digests/index/all.md` — full history, newest first, grouped by month header.
  - `digests/index/by_category/{marketing_skill,vibe_coding_skill,ai_content_skill,general_skill}.md` — one table per canonical category.
  - `digests/index/by_month/YYYY-MM.md` — one table per month.
- **Telegram footer** — every digest (including the `[NO_NEW_ITEMS]` short message) ends with public links to these indexes. URLs are built from the `GITHUB_REPOSITORY` env var GitHub Actions sets automatically, with a hard-coded fallback for local runs.

All four JSON/Markdown artifacts live under `digests/` and are picked up by the workflow's existing `git add digests/` commit-back step — no workflow change required.

## Repo-level grouping and dedupe (Sprint 4)

- **One repo = one digest entry.** GitHub items are grouped by `repo_full_name`; all skill folders inside `.claude/skills/` are listed in a single entry's `skills` field and summarised in `meta` ("⭐ N • K skills: name1, name2, name3…"). A repo with 21 skills produces one item, not 21.
- **Dedupe across days.** Repos already shown in earlier digests aren't shown again unless they gained 5+ stars or added new skill folders (`has_new_skills`). The orchestrator applies this filter before the analyzer runs.
- **No new items short message.** If every candidate is filtered out, the analyzer is skipped entirely and Telegram receives a one-line "no new Claude Skills" message (marker `[NO_NEW_ITEMS]`). State is still saved so the same items don't reappear next run.
- **Analyzer headroom.** `max_tokens` is now 12 000 (override via `TRENDWATCH_MAX_TOKENS`); `analyzer.py` logs input/output sizes and stop reason and raises a clear error if a response is truncated.

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
