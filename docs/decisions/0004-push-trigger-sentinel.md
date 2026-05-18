# 0004 — Push-trigger sentinel for cron pipelines

**Date:** 2026-05-18. **Status:** Accepted. **Touches:** `.github/workflows/{trendwatch,workflows}.yml`, `.github/trigger-*`.

## Context
Operators (incl. coding agents) sometimes need to re-run a cron pipeline
NOW, not at next 09:00 / 12:00 UTC. The Actions UI offers a `Run workflow`
button, but it's ergonomically failure-prone: requires opening the right
URL, picking the right branch, sometimes ticking a checkbox. We accumulated
several "ran but nothing happened" incidents because the checkbox was
missed.

## Decision
Each pipeline yaml watches a sentinel file under `.github/`:
- `trigger-trendwatch` → fires `trendwatch.yml`
- `trigger-workflows` → fires `workflows.yml`

Any push to main that modifies that path triggers the pipeline.
`paths`-scoped so the pipeline's own commit-back (to `digests/**`)
never re-triggers (no loop). Force flag bound to `github.event_name != 'schedule'`
so push **and** workflow_dispatch always force-bypass idempotency;
only the scheduled cron respects `last_sent_date`.

## Consequences
- ✅ Anyone with PR-merge rights can trigger from a git client without
  visiting Actions UI. An agent can trigger via the GitHub MCP `push_files`
  / `create_or_update_file` tool.
- ✅ No checkbox to forget. Manual = always intentional = always force.
- ⚠️ Triple trigger (schedule + workflow_dispatch + push) → more places
  to keep in sync if the run command changes. Mitigated by `if`-on-event-name.

## Alternatives Considered
- **Default `inputs.force=true` on workflow_dispatch**: still requires
  Actions UI access; agent can't trigger from MCP.
- **Push trigger on all of `main` with `paths-ignore: digests/**`**:
  rejected — every code PR merge would fire the pipeline (spam Telegram).
- **External webhook via Vercel**: feasible but adds an HTTP hop and
  another secret to manage.
