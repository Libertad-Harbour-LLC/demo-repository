# Domain glossary

Stable vocabulary for the repo. Use these terms exactly — don't drift into
"channel," "service," "tab," "handler." When a refactor introduces a concept
not listed here, add it before merging (per `mattpocock/skills` →
`improve-codebase-architecture` discipline).

The pipeline-level structure lives in [CLAUDE.md](CLAUDE.md); this file is
the bot's UI/data vocabulary.

## Bot (api/telegram.py)

**Source** — one of `{skills, n8n, make, opensource}`. A logical data namespace
the bot serves. Each Source has its own recommended/watchlist files in
`digests/`, its own category enum, and a `tool_filter` (skills: `None`; n8n:
`"n8n"`; make: `"make"`; opensource: `None`). `make` shares the workflows files
with `n8n` but filters by tool. `opensource` (deployable OSS products/platforms)
reads its own `digests/opensource/` files. Registered in `SOURCES` at the top of
`api/telegram.py`.

**Item** — a single entry in a Source. Either a **recommended item** (lives
in `digests/<source>/recommended.json` under the `skills` key, includes
scoring, category, skill list, etc.) or a **watch item** (lives in
`watchlist.json` under `items` with `signal_to_wait` + `metric_baseline`).
Both schemas converge in the bot via `Items._tag_watch`. Identified by
`url` (primary key).

**Items** (plural) — the loaded, deduped (recommended wins over watch on
URL collision), tool-filtered, sorted collection of Items for one Source.
Built via `Items.load(source_key)`; supports `len()`, `iter()`, slicing,
plus `filter_by_category`, `filter_by_month`, `filter_for_view`. Filter
methods return a new Items (immutable chain). Source identity is carried
on the instance so chained filters know the Source they came from.

**Status** — an Item's lifecycle state, set by the bot at merge time, not
stored: `recommended` (default) or `watch`. Watch items render with a 👀
prefix.

**View** — a selector for what to show on a paginated screen. Sealed sum
type with three kinds: `all` (everything in the Source), `category(cat)`
(filtered to one category), `month(ym)` (filtered to one `YYYY-MM`). A
View carries its own `nav_token` and dispatch keys (`kind`, `arg`).
Factories: `ALL_VIEW`, `category_view(cat)`, `month_view(ym)`.

**Screen** — a `(text, inline_keyboard_or_None)` tuple. Pure rendering
result: no transport, no side effects. Built by `screen_top_menu`,
`screen_source_menu`, `screen_categories`, `screen_months`, `screen_page`,
`screen_item`. A Screen is what `deliver` sends to Telegram.

**Detail screen** — `screen_item(source_key, url_id)`. Full per-Item view:
category, score, full skills_in_repo, test_steps, metric, description.
For watch Items: signal_to_wait + why_interesting + baseline metrics.
Reached via `[📋 N]` buttons in any paginated list. Back navigation
returns to the unfiltered list (page 0) — the original filter/page
context isn't preserved (would inflate callback_data past Telegram's
64-byte limit).

**Explain** — `[🤖 Объясни простыми словами]` button on the Detail screen.
Single-shot Anthropic call (`api/llm.py` → `explain_item`); produces a
3-5 sentence plain-Russian explanation of the Item. Sent as a NEW
Telegram message so the Detail screen stays visible above. Gated by
`LLM_ENABLED` (i.e. `ANTHROPIC_API_KEY` env var) — button hidden if
the key isn't set. Failure mode (timeout / 5xx / empty response):
fallback message "Не удалось получить объяснение." The system prompt
is cacheable; Item content goes through the user message wrapped in
`<item>...</item>` and treated as data (mitigates prompt injection
from pipeline-supplied descriptions). Per `agents-best-practices`
MVP guidance: answer-only autonomy, no tool loop.

**url_id** — 8-char sha1 prefix of an Item's URL. Used inside
`callback_data` as a compact stable identifier when `repo_full_name` is
either too long (workflows pipeline stores `"owner/repo: wf-name"`
which exceeds Telegram's 64-byte callback limit) or contains a colon
that would collide with our `:` delimiter. Built by `_url_id(url)`,
reverse-looked-up by `Items.find_by_url_id(uid)`.

**deliver** — the single transport adapter. Takes a Screen and either
sends it as a new Telegram message or edits an existing one
(`edit_message_id`). The only place where `sendMessage` vs
`editMessageText` is chosen. Optional `reply_keyboard` is honoured only on
the send path (Telegram cannot change reply_keyboard on an edited message).

**nav_token** — the suffix portion of `callback_data` that identifies a
View for pagination: `"list"` (= `ALL_VIEW`), `"cat:<X>"`, `"month:<YYYY-MM>"`.
**Byte-stable across releases** — inline keyboards live in user chat
history indefinitely and fire whatever string was baked at send time.

**Route** — a parsed `callback_data` string. Sealed sum type with nine
kinds: `top_menu`, `source_menu`, `categories`, `months`, `list`,
`category`, `month`, `item`, `explain`. Constructed only via
`Route.parse(callback_data)`, which returns `None` on any malformed or
unknown-source input (the webhook then silently no-ops). Wire format is
`src:<source>:<action>[:<args>]` or the bare `menu` — **byte-stable
across releases** since inline keyboards persist in chat history
indefinitely. `handle_callback` is a pure dispatch on `route.kind`.

**Page** — zero-based pagination index within a View's filtered Items.
PAGE_SIZE = 5. Pagination buttons encode `<route>:<page>` in
`callback_data`.

## Cross-cutting

**Pipeline** — see CLAUDE.md. Two of them (`trendwatch`, `workflows`).
The bot reads only their committed JSON output, never their internals.

**Idempotency marker** (`last_sent_date`) — per-pipeline date stamp in
`digests/state.json` (skills) and `digests/workflows/state.json`. The
orchestrator short-circuits if this matches today (UTC). `--force` to
bypass. Not visible to the bot.
