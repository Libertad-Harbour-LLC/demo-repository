"""Auto-push the workflows ``recommended.json`` to the automation catalog.

One idempotent POST per run (upsert by workflow url). The site renders the
whole ``recommended.json`` as automation cards — same shape as the n8n library
— so the payload is the recommended DB verbatim. Secret comes from the
``AUTOMATION_INGEST_SECRET`` env var (configured in Actions / the bot); without
it the push is skipped and the digest/Telegram run is unaffected.

Never raises into the orchestrator — returns ``(response_json, error)``.
"""
from __future__ import annotations

import os
from typing import Callable

import requests

INGEST_URL = os.environ.get(
    "AUTOMATION_INGEST_URL",
    "https://iuxlbrjhcbeiovgbldcy.supabase.co/functions/v1/ingest-automation-workflows",
).strip()


def build_payload(recommended_db: dict) -> dict:
    """The catalog ingests the recommended DB as-is (keyed by workflow url)."""
    skills = (recommended_db or {}).get("skills") or {}
    return {"workflows": skills}


def push_recommended(
    recommended_db: dict,
    *,
    url: str = INGEST_URL,
    secret: str | None = None,
    post: Callable = requests.post,
    timeout: int = 30,
) -> tuple[dict | None, str | None]:
    """POST the recommended DB to the automation catalog. Returns ``(json,
    None)`` on success or ``(None, "cause")`` on any failure. Exactly one is
    non-None."""
    if secret is None:
        secret = os.environ.get("AUTOMATION_INGEST_SECRET", "").strip()
    if not secret:
        return None, "AUTOMATION_INGEST_SECRET not set — skipping catalog push"
    payload = build_payload(recommended_db)
    if not payload.get("workflows"):
        return None, "empty recommended.json (no workflows) — nothing to push"

    headers = {"Content-Type": "application/json", "x-automation-secret": secret}
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
    if not isinstance(result, dict):
        return "(no response)"
    parts = []
    for k in ("ok", "workflows", "inserted", "updated", "skipped"):
        if k in result:
            v = result[k]
            if isinstance(v, list):
                v = len(v)
            parts.append(f"{k}={v}")
    return " ".join(parts) or "(empty response)"


__all__ = ["INGEST_URL", "build_payload", "push_recommended", "format_summary"]
