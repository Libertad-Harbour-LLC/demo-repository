# 0008 — Telegram-visible error reasons in fallback

**Date:** 2026-05-18. **Status:** Accepted. **Touches:** `trendwatch/trendwatch.py`, `workflows/workflows.py`, `api/llm.py`.

## Context
When the analyzer failed (Anthropic 5xx, JSON parse error, auth, …)
the pipeline fell back to a flat-link digest with no clue why. The
real error landed only in Actions / Vercel stderr, which means digging
through logs to diagnose. We hit this loop twice in one session:
1. "LLM-анализ упал" → 30 minutes of guessing → root cause was an
   `\n` in the GitHub Actions secret `ANTHROPIC_API_KEY`.
2. Same again the next day → root cause was a stale revoked key.

## Decision
- **Trendwatch & workflows orchestrators**: extract `_fallback_with_reason`
  helper that, after sending the plain-link digest, sends a SECOND
  Telegram message: `⚠️ LLM-анализ упал, причина: <ExceptionType>: <msg>`.
- **Analyzer**: walk `__cause__` / `__context__` chain on caught
  exceptions and join with `" ← "` so `APIConnectionError: Connection error.`
  becomes `APIConnectionError: Connection error. ← ConnectError: ... ← gaierror: ...`.
- **api/llm.py `_mask_secrets`**: regex-mask `sk-ant-*` and Telegram
  bot tokens in any string that reaches a user-visible fallback. Same
  applied to the chain output before it leaves the analyzer.
- **Trendwatch `_api_key_fingerprint`**: appends `Ключ: len=N ...<last4>`
  (and `(had whitespace)` if the env var was non-stripped) so the
  operator can match against the per-key suffix shown in Anthropic
  console.

## Consequences
- ✅ Diagnosing a broken cron run is now ONE Telegram screenshot,
  not a log-dive.
- ✅ Whitespace-pollution vs revoked-key vs wrong-account-key can be
  told apart by the fingerprint line.
- ⚠️ Telegram message has a few extra lines on failure days. Worth it.

## Alternatives Considered
- **Stderr-only logging**: status quo. Rejected per user pain.
- **External error tracker (Sentry)**: extra service, extra secret,
  extra cost. Overkill for a 2-admin private bot.
- **Mask everything except types in error message**: would lose useful
  detail. The exception message is mostly safe; only API key and bot
  token patterns are masked specifically.
