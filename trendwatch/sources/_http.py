"""Shared GitHub-API GET helper with secondary-rate-limit awareness.

GitHub's search endpoints (especially /search/code) enforce both a primary
quota (X-RateLimit-*) and a *secondary* abuse limit that answers ``429 Too
Many Requests`` (or ``403`` with a ``Retry-After`` header). The original
fetchers only recognised the 403+remaining=0 shape, so in GitHub Actions —
where runner IPs are shared and code-search budgets are tight — every
code-search query died with an unhandled 429 and the whole channel silently
contributed zero candidates (observed in the 2026-06-11 production run).

This helper is used by both pipelines (``trendwatch/sources/github.py`` and
``workflows/sources/_github_common.py``):

- honours ``Retry-After`` (capped) and retries before giving up;
- returns the shared ``RATE_LIMITED`` sentinel so callers can keep their
  existing ``data == RATE_LIMITED`` checks;
- prefers a ``GH_SEARCH_TOKEN`` env var over ``GITHUB_TOKEN`` when building
  auth headers — a user PAT has its own search quota, which dodges the
  shared budget of the Actions installation token if 429s persist.
"""
from __future__ import annotations

import os
import sys
import time

import requests

RATE_LIMITED = "RATE_LIMITED"

# Cap a single Retry-After sleep; daily-cron runs can afford waiting but a
# hostile/huge header value must not stall the job for an hour.
MAX_RETRY_AFTER_SECONDS = 120
# Fallback waits when no Retry-After header is present (attempt 1, 2, ...).
DEFAULT_BACKOFF_SECONDS = (30, 60)

# Pause between consecutive /search/code requests. The authenticated limit
# is 10 requests/min; 7.5s spacing keeps us at 8/min with headroom.
CODE_SEARCH_PACING_SECONDS = 7.5


def build_github_headers(user_agent: str) -> dict:
    """Standard GitHub REST headers. GH_SEARCH_TOKEN (optional PAT secret)
    wins over the Actions-provided GITHUB_TOKEN."""
    h = {
        "Accept": "application/vnd.github+json",
        "User-Agent": user_agent,
    }
    token = (
        os.environ.get("GH_SEARCH_TOKEN", "").strip()
        or os.environ.get("GITHUB_TOKEN", "").strip()
    )
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _is_rate_limited(resp: requests.Response) -> bool:
    if resp.status_code == 429:
        return True
    if resp.status_code == 403:
        # Primary quota exhausted or secondary abuse limit.
        if resp.headers.get("X-RateLimit-Remaining") == "0":
            return True
        if resp.headers.get("Retry-After"):
            return True
    return False


def _retry_wait(resp: requests.Response, attempt: int) -> int:
    try:
        ra = int(resp.headers.get("Retry-After") or 0)
    except ValueError:
        ra = 0
    if ra > 0:
        return min(ra, MAX_RETRY_AFTER_SECONDS)
    idx = min(attempt, len(DEFAULT_BACKOFF_SECONDS) - 1)
    return DEFAULT_BACKOFF_SECONDS[idx]


def get_json_with_backoff(
    url: str,
    *,
    headers: dict,
    params: dict | None = None,
    timeout: int = 30,
    max_retries: int = 2,
    tag: str = "github",
    sleep=time.sleep,
):
    """GET ``url`` returning parsed JSON, ``None`` (404 / hard error), or
    ``RATE_LIMITED`` (rate limit persisted through all retries).

    On 429 / rate-limit 403 the call sleeps per ``Retry-After`` (capped at
    MAX_RETRY_AFTER_SECONDS, defaults if absent) and retries up to
    ``max_retries`` times. Network errors are not retried — the daily-cron
    callers already degrade gracefully on ``None``.
    """
    for attempt in range(max_retries + 1):
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=timeout)
        except Exception as exc:
            print(f"[{tag}] GET {url} failed: {exc}", file=sys.stderr)
            return None
        if resp.status_code == 404:
            return None
        if _is_rate_limited(resp):
            if attempt < max_retries:
                wait = _retry_wait(resp, attempt)
                print(
                    f"[{tag}] {resp.status_code} rate-limited on {url} — "
                    f"sleeping {wait}s (attempt {attempt + 1}/{max_retries})",
                    file=sys.stderr,
                )
                sleep(wait)
                continue
            print(
                f"[{tag}] {resp.status_code} rate-limited on {url} — "
                f"giving up after {max_retries} retries",
                file=sys.stderr,
            )
            return RATE_LIMITED
        try:
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            print(f"[{tag}] GET {url} failed: {exc}", file=sys.stderr)
            return None
    return None


__all__ = [
    "RATE_LIMITED",
    "CODE_SEARCH_PACING_SECONDS",
    "build_github_headers",
    "get_json_with_backoff",
]
