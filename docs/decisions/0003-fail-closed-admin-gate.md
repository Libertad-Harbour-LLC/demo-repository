# 0003 — Fail-closed admin gate

**Date:** 2026-05-17. **Status:** Accepted. **Touches:** `api/telegram.py`.

## Context
User asked for the bot to only respond to two Telegram user IDs. The
first version hardcoded the IDs as defaults + an env-var override so
the bot would still work if the env var was missing. The hardcode
leaked the IDs into the public repo. After moving them to env var,
we had to decide: what happens if `BOT_ADMIN_IDS` is unset?

## Decision
**Fail-closed.** `ADMIN_IDS = parse(BOT_ADMIN_IDS_env)`. If the env
var is empty or unset, `ADMIN_IDS` is the empty set and **everyone**
(including the owner) gets the "🔒 Приватный бот" denial. To unlock,
re-add the env var on Vercel.

## Consequences
- ✅ A misconfigured deploy (typo, accidentally deleted env var) can
  NEVER leak data to strangers. Worst case: owner locks themselves out
  for 60 seconds until they fix the env.
- ✅ Healthcheck (`GET /api/telegram`) exposes `"admin_count": N` so
  the misconfiguration is visible from a browser, not just from a "why
  doesn't my bot work" Telegram message.
- ⚠️ Owner must remember to set `BOT_ADMIN_IDS` on every fresh Vercel
  project (covered in `bot-README.md` and `CLAUDE.md`).

## Alternatives Considered
- **Default to one trusted ID**: would still need that ID hardcoded
  somewhere. Same problem in smaller form.
- **Fail-open (any user)**: catastrophic — first deploy with missing
  env makes the bot public.
- **Default to "deny all" with admin-add-via-Telegram**: would need a
  bootstrap mechanism that itself is admin-only. Recursive.
