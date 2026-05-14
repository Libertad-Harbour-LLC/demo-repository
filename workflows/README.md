# workflows — Daily n8n / Make Workflow Radar

A second tracking pipeline parallel to `trendwatch/`. Scans GitHub (n8n +
Make topics, code search for workflow JSONs) and Reddit (n8n / Make /
automation subs) for **ready-made workflows** that users can download as
JSON and import directly into n8n or Make.

Runs daily at **12:00 UTC** via `.github/workflows/workflows.yml` (the
skills pipeline runs at 09:00). Same Telegram bot, same chat — just a
different header (`⚙️ Daily Workflow Radar — YYYY-MM-DD`).

## Sources

| Source | Module | Notes |
|---|---|---|
| GitHub (n8n) | `workflows/sources/n8n_github.py` | code search for `nodes`/`connections` + n8n topics; verifies JSON signature |
| GitHub (Make) | `workflows/sources/make_github.py` | code search for `flow`/`modules` + make-blueprint topics; verifies JSON signature |
| Reddit | `workflows/sources/reddit.py` | wraps `trendwatch.sources.reddit` with workflow-specific subs + keyword filter |

The n8n / Make GitHub fetchers share a parameterised core in
`workflows/sources/_github_common.py` (group by repo, fetch the JSON
capped at `MAX_JSON_FETCH_BYTES` bytes, validate against the tool's JSON
signature).

## Output

All artifacts live under `digests/workflows/` (isolated from the skills
pipeline's `digests/`):

- `digests/workflows/YYYY-MM-DD.md` — daily report
- `digests/workflows/state.json` — last-run snapshot for deltas
- `digests/workflows/recommended.json` — promoted workflows DB
- `digests/workflows/watchlist.json` — watchlist DB
- `digests/workflows/index/all.md`
- `digests/workflows/index/by_category/<cat>.md`
- `digests/workflows/index/by_tool/{n8n,make,other}.md`
- `digests/workflows/index/by_month/<YYYY-MM>.md`

## Configuration

Edit `workflows/config.py`:

- **Add a subreddit** → append to `REDDIT_SUBREDDITS`.
- **Add a GitHub topic** → append to `GITHUB_TOPICS_N8N` or
  `GITHUB_TOPICS_MAKE`.
- **Add a code-search query** → append to `GITHUB_CODE_QUERIES_N8N` or
  `GITHUB_CODE_QUERIES_MAKE`.
- **Disable a source** → flip the matching flag in `SOURCES`.
- **Add a category** → extend the `CATEGORIES` tuple; the index writer
  will pick up the new slug on the next run.

## Reuse with `trendwatch/`

The workflows pipeline imports and reuses these trendwatch modules
directly (no duplication):

| trendwatch module | what we reuse |
|---|---|
| `trendwatch.state` | `load_state(path=...)` / `save_state(path=...)` / `compute_deltas` |
| `trendwatch.skill_db` | recommended / watchlist DB + graduation logic |
| `trendwatch.analyzer` | Anthropic call (with `system_prompt` kwarg = workflows prompt) |
| `trendwatch.normalizer` | called from `workflows.normalizer` with a workflows-specific `KNOWN_TOOLS` |
| `trendwatch.index_writer` | called with `categories=`, `tools=`, `default_category=` |
| `trendwatch.links` | `build_footer(category="workflows")` for the Telegram footer |
| `trendwatch.telegram_client` | `send_text` / `send_digest` |
| `trendwatch.report` | `to_markdown` (header is rewritten to "Daily Workflow Radar") |

## Commands

```bash
pip install -r trendwatch/requirements.txt
python workflows/workflows.py --dry-run     # fetch + print, no API calls
python workflows/workflows.py --no-analyzer # plain link digest (no Anthropic)
python workflows/workflows.py               # full pipeline (analyzer + Telegram)
```

## Secrets

Same as the skills pipeline — set in **GitHub repository secrets**:

- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`
- `ANTHROPIC_API_KEY`
- `GITHUB_TOKEN` (provided by Actions automatically)
- `APIFY_API_TOKEN` (reserved for future X/Threads support)
