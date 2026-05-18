# 0002 — Items as deep module

**Date:** 2026-05-17. **Status:** Accepted. **Touches:** `api/telegram.py`.

## Context
Pagination, filtering, dedup (recommended-vs-watch URL collision),
tool filter (`n8n` / `make`), and sort were spread across the call
sites that needed Items. Result: each new screen reimplemented some
subset; bugs were per-screen.

## Decision
`Items` is a `@dataclass(frozen=True, eq=False)` with one factory
`Items.load(source_key)` that does **all** the assembly:
- fetch `recommended.json` + `watchlist.json` from raw.githubusercontent.com
- tag watch entries via `_tag_watch`
- dedupe by URL (recommended wins)
- apply tool filter (n8n / make / None)
- stable sort by `first_recommended` desc, then `title`

Filters (`filter_by_category`, `filter_by_month`, `filter_for_view`)
return a new `Items`, never mutate. Source identity (`source_key`)
travels on the instance so chained filters know what they came from.

## Consequences
- ✅ Each new screen calls `Items.load(src).filter_for_view(view)` —
  zero per-screen logic to get right.
- ✅ Source registry (`SOURCES` dict) is the **only** place where
  per-source config lives (URLs, categories, tool filter).
- ⚠️ 60s in-process cache means changes to `recommended.json` take up
  to a minute to surface in the bot. Acceptable for a stateless serverless.

## Alternatives Considered
- **Flat module functions** (`load_items(src)`, `filter_category(items, cat)`):
  rejected — caller has to thread `source_key` through every call.
- **Class with mutable state**: rejected — chained filters would mutate
  shared list, awful for tests.
