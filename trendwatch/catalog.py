"""Auto-push the Import payload to the web catalog ingest endpoint.

One idempotent POST (upsert by repo slug / skill url) per run. Secret comes
from the ``SKILL_RADAR_INGEST_SECRET`` env var (already in Actions secrets).
Never raises into the orchestrator — returns ``(response_json, error)``.
"""
from __future__ import annotations

import os
import sys
from typing import Callable

import requests

INGEST_URL = os.environ.get(
    "SKILL_RADAR_INGEST_URL",
    "https://iuxlbrjhcbeiovgbldcy.supabase.co/functions/v1/ingest-skill-radar",
).strip()


def push_payload(
    payload: dict,
    *,
    url: str = INGEST_URL,
    secret: str | None = None,
    post: Callable = requests.post,
    timeout: int = 30,
) -> tuple[dict | None, str | None]:
    """POST ``payload`` to the catalog. Returns ``(json, None)`` on success or
    ``(None, "human-readable cause")`` on any failure. Exactly one is non-None.
    """
    if secret is None:
        secret = os.environ.get("SKILL_RADAR_INGEST_SECRET", "").strip()
    if not secret:
        return None, "SKILL_RADAR_INGEST_SECRET not set — skipping catalog push"
    if not payload.get("repos"):
        return None, "empty payload (no repos) — nothing to push"

    headers = {"Content-Type": "application/json", "x-radar-secret": secret}
    try:
        resp = post(url, json=payload, headers=headers, timeout=timeout)
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"

    status = getattr(resp, "status_code", None)
    if status != 200:
        body = ""
        try:
            body = resp.text[:300]
        except Exception:
            pass
        return None, f"HTTP {status}: {body}"
    try:
        return resp.json(), None
    except Exception:
        return None, "non-JSON response from ingest endpoint"


def format_summary(result: dict | None) -> str:
    """Compact one-line log of the ingest response counts."""
    if not isinstance(result, dict):
        return "(no response)"
    keys = ("ok", "repos", "skills", "skipped", "suggested")
    parts = []
    for k in keys:
        if k in result:
            v = result[k]
            if isinstance(v, list):
                v = len(v)
            parts.append(f"{k}={v}")
    return " ".join(parts) or "(empty response)"


def suggested_categories(result: dict | None) -> list[dict]:
    """Pull the ``suggested`` list out of the ingest response (best-effort)."""
    if not isinstance(result, dict):
        return []
    raw = result.get("suggested")
    if isinstance(raw, list):
        return [s for s in raw if isinstance(s, dict)]
    return []


__all__ = ["INGEST_URL", "push_payload", "format_summary", "suggested_categories"]
