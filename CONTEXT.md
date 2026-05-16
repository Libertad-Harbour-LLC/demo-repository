# Domain glossary

Stable vocabulary for the repo. Use these terms exactly — don't drift into
"channel," "service," "tab," "handler." When a refactor introduces a concept
not listed here, add it before merging (per `mattpocock/skills` →
`improve-codebase-architecture` discipline).

The pipeline-level structure lives in [CLAUDE.md](CLAUDE.md); this file is
the bot's UI/data vocabulary.

## Bot (api/telegram.py)

**Source** — one of `{skills, n8n, make}`. A logical data namespace the bot
serves. Each Source has its own recommended/watchlist files in `digests/`,
its own category enum, and a `tool_filter` (skills: `None`; n8n: `"n8n"`;
make: `"make"`). `make` shares the workflows files with `n8n` but filters by
tool. Registered in `SOURCES` at the top of `api/telegram.py`.

**Item** — a single entry in a Source. Either a **recommended item** (lives
in `digests/<source>/recommended.json` under the `skills` key, includes
scoring, category, skill list, etc.) or a **watch item** (lives in
`watchlist.json` under `items` with `signal_to_wait` + `metric_baseline`).
Both schemas converge in the bot via `_normalize_watch_item`. Identified
by `url` (primary key).

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
`screen_source_menu`, `screen_categories`, `screen_months`, `screen_page`.
A Screen is what `deliver` sends to Telegram.

**deliver** — the single transport adapter. Takes a Screen and either
sends it as a new Telegram message or edits an existing one
(`edit_message_id`). The only place where `sendMessage` vs
`editMessageText` is chosen. Optional `reply_keyboard` is honoured only on
the send path (Telegram cannot change reply_keyboard on an edited message).

**nav_token** — the suffix portion of `callback_data` that identifies a
View for pagination: `"list"` (= `ALL_VIEW`), `"cat:<X>"`, `"month:<YYYY-MM>"`.
**Byte-stable across releases** — inline keyboards live in user chat
history indefinitely and fire whatever string was baked at send time.

**Route** — a parsed `callback_data` string. Format:
`src:<source>:<action>[:<args>]` or the bare `menu` for the top picker.
Parsed inline in `handle_callback` (still flat — candidate #5 for future
deepening).

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
