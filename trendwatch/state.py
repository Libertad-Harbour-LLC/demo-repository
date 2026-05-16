"""Persisted day-to-day state for trendwatch.

Stores a snapshot of items seen on the last run in ``digests/state.json`` so we
can compute deltas (new items, stargazer growth, score growth) on the next run.
The file is committed back by CI so memory survives across runs.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

DEFAULT_PATH = "digests/state.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_state(path: str = DEFAULT_PATH) -> dict:
    """Load previous-run state, or return an empty skeleton if missing."""
    if not os.path.exists(path):
        return {"items": {}}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {"items": {}}
    if not isinstance(data, dict):
        return {"items": {}}
    data.setdefault("items", {})
    if not isinstance(data["items"], dict):
        data["items"] = {}
    return data


def _key(item: dict) -> str:
    return item.get("url") or item.get("id") or item.get("title", "")


def _extract_stars(item: dict) -> int | None:
    """Best-effort pull of stargazer count from the meta string."""
    stars = item.get("stars")
    if isinstance(stars, int):
        return stars
    meta = item.get("meta", "")
    if not isinstance(meta, str):
        return None
    # GitHub items use "⭐ 1234 • ..." — parse the first int after the star.
    star_marker = "⭐"
    if star_marker in meta:
        rest = meta.split(star_marker, 1)[1].strip()
        token = rest.split(" ", 1)[0].replace(",", "")
        try:
            return int(token)
        except ValueError:
            return None
    return None


def _extract_score(item: dict) -> int | None:
    score = item.get("score")
    if isinstance(score, int):
        return score
    meta = item.get("meta", "")
    if not isinstance(meta, str):
        return None
    # Reddit items use "↑<score>" inside meta.
    marker = "↑"
    if marker in meta:
        rest = meta.split(marker, 1)[1].strip()
        token = rest.split(" ", 1)[0].split("•", 1)[0].strip()
        try:
            return int(token)
        except ValueError:
            return None
    return None


def _extract_skills_count(item: dict) -> int | None:
    """Pull skills_count from a github-grouped item (None for other sources)."""
    sc = item.get("skills_count")
    if isinstance(sc, int):
        return sc
    return None


def compute_deltas(
    new_items_by_source: dict[str, list[dict]], prev_state: dict
) -> list[dict]:
    """Annotate each new item with is_new + delta vs the previous snapshot.

    Returns a flat list across sources. Each entry keeps the original item
    fields plus: ``is_new``, ``delta_stars``, ``delta_score``,
    ``delta_skills_count``, ``has_new_skills``, ``first_seen``.
    """
    prev_items: dict[str, dict] = (prev_state or {}).get("items", {}) or {}
    now = _now_iso()
    out: list[dict] = []
    for source, items in (new_items_by_source or {}).items():
        for it in items or []:
            key = _key(it)
            if not key:
                continue
            prev = prev_items.get(key)
            stars = _extract_stars(it)
            score = _extract_score(it)
            skills_count = _extract_skills_count(it)
            if prev is None:
                first_seen = now
                is_new = True
                delta_stars = None
                delta_score = None
                delta_skills_count = None
            else:
                first_seen = prev.get("first_seen", now)
                is_new = False
                prev_stars = prev.get("stars")
                prev_score = prev.get("score")
                prev_skills_count = prev.get("skills_count")
                delta_stars = (
                    stars - prev_stars
                    if isinstance(stars, int) and isinstance(prev_stars, int)
                    else None
                )
                delta_score = (
                    score - prev_score
                    if isinstance(score, int) and isinstance(prev_score, int)
                    else None
                )
                # Backwards-compat: old state may lack skills_count.
                delta_skills_count = (
                    skills_count - prev_skills_count
                    if isinstance(skills_count, int) and isinstance(prev_skills_count, int)
                    else None
                )
            has_new_skills = (
                isinstance(delta_skills_count, int) and delta_skills_count > 0
            )
            enriched = dict(it)
            enriched["source"] = source
            enriched["is_new"] = is_new
            enriched["delta_stars"] = delta_stars
            enriched["delta_score"] = delta_score
            enriched["delta_skills_count"] = delta_skills_count
            enriched["has_new_skills"] = has_new_skills
            enriched["first_seen"] = first_seen
            out.append(enriched)
    return out


def save_state(
    items_by_source: dict[str, list[dict]], path: str = DEFAULT_PATH
) -> None:
    """Persist a fresh snapshot, preserving ``first_seen`` for known items.

    Other top-level keys in the existing state file (e.g. ``last_sent_date``)
    are preserved as-is so idempotency markers survive a state-save.
    """
    prev = load_state(path)
    prev_items = prev.get("items", {}) or {}
    now = _now_iso()
    new_items: dict[str, dict] = {}
    for source, items in (items_by_source or {}).items():
        for it in items or []:
            key = _key(it)
            if not key:
                continue
            stars = _extract_stars(it)
            score = _extract_score(it)
            skills_count = _extract_skills_count(it)
            first_seen = (prev_items.get(key) or {}).get("first_seen", now)
            new_items[key] = {
                "source": source,
                "title": it.get("title", ""),
                "stars": stars,
                "score": score,
                "skills_count": skills_count,
                "first_seen": first_seen,
            }
    snapshot: dict[str, Any] = dict(prev)
    snapshot["last_run"] = now
    snapshot["items"] = new_items
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2, sort_keys=True)


def _today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def was_sent_today(path: str = DEFAULT_PATH) -> bool:
    """Return True if the pipeline already sent a Telegram digest today.

    Used as an idempotency guard: protects the Anthropic API budget when the
    workflow is re-triggered manually (workflow_dispatch retries, CI reruns).
    """
    data = load_state(path)
    return data.get("last_sent_date") == _today_utc()


def mark_sent_today(path: str = DEFAULT_PATH) -> None:
    """Record today's date as the last successful Telegram send."""
    data = load_state(path)
    data["last_sent_date"] = _today_utc()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
