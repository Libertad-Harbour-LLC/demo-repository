# 0001 — Route as typed sum type

**Date:** 2026-05-17. **Status:** Accepted. **Touches:** `api/telegram.py`.

## Context
`handle_callback` parsed `callback_data` strings inline with a flat
`if/elif` chain. CONTEXT.md called this "candidate #5 for future
deepening". Drawback: action names and argument shapes drifted between
the parser and the keyboard builders, with no compile-time check.

## Decision
Introduced a `Route` `@dataclass(frozen=True)` plus a `RouteKind` `Literal`
sum type with one entry per action (`top_menu`, `source_menu`, `list`,
`category`, `month`, `item`, `random`, `share`, `setup`, `similar`,
`explain`). `Route.parse(data)` is the **single** entry point that turns
a Telegram callback string into either a `Route` or `None`. `handle_callback`
is now a pure dispatch on `route.kind`.

## Consequences
- ✅ Wire format byte-stable across releases: inline keyboards baked at
  send time persist in chat history indefinitely. `Route.parse` is the
  only place to add new actions and must remain backward compatible.
- ✅ One unit-test parametrize set (`tests/test_route_parse.py`)
  covers every known shape + 6 invalid shapes.
- ⚠️ Adding a new action = touching both `RouteKind` literal AND
  `Route.parse` AND `handle_callback`. Cost of safety.

## Alternatives Considered
- **Inline parsing**: status quo. Rejected — too easy to drift.
- **Action enum + dict-dispatch**: would require homogenizing signatures
  (`*args` indirection), losing the typed payload per kind.
- **External library (e.g. aiogram routers)**: overkill for ~10 routes;
  would force a framework rewrite.
