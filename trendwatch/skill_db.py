"""Persistent skill database for trendwatch.

Two JSON files in ``digests/`` survive across runs (committed back by CI):

- ``digests/recommended.json`` — skills that have been promoted to ``top_test``
  in any prior run. They are excluded from future digests (one-shot
  recommendation: we never recommend the same repo twice).
- ``digests/watchlist.json`` — skills that landed in ``top_watch`` along with
  the ``signal_to_wait`` the model wanted. On each subsequent run we check
  whether the signal materialised in fresh metrics; if so, the item graduates
  and is fed back to the LLM as a priority candidate for ``top_test``.

Both files are written sorted-keys + indented so the daily commit diff is
review-friendly.
"""
from __future__ import annotations

import json
import os
from datetime import date as _date, datetime, timedelta
from typing import Iterable

DEFAULT_RECOMMENDED_PATH = "digests/recommended.json"
DEFAULT_WATCHLIST_PATH = "digests/watchlist.json"

WATCHLIST_TTL_DAYS = 30
GRADUATE_STAR_DELTA = 5
GRADUATE_SKILLS_DELTA = 1


# ---------------------------------------------------------------------------
# load/save

def _load_json(path: str, empty: dict) -> dict:
    if not os.path.exists(path):
        return dict(empty)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return dict(empty)
    if not isinstance(data, dict):
        return dict(empty)
    return data


def _save_json(data: dict, path: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")


def load_recommended(path: str = DEFAULT_RECOMMENDED_PATH) -> dict:
    data = _load_json(path, {"skills": {}})
    data.setdefault("skills", {})
    if not isinstance(data["skills"], dict):
        data["skills"] = {}
    return data


def load_watchlist(path: str = DEFAULT_WATCHLIST_PATH) -> dict:
    data = _load_json(path, {"items": {}})
    data.setdefault("items", {})
    if not isinstance(data["items"], dict):
        data["items"] = {}
    return data


def save_recommended(db: dict, path: str = DEFAULT_RECOMMENDED_PATH) -> None:
    _save_json(db, path)


def save_watchlist(db: dict, path: str = DEFAULT_WATCHLIST_PATH) -> None:
    _save_json(db, path)


# ---------------------------------------------------------------------------
# mutation helpers

def is_recommended(db: dict, url: str) -> bool:
    if not url:
        return False
    return url in (db or {}).get("skills", {})


def _repo_full_name(item: dict) -> str:
    return (
        item.get("repo_full_name")
        or item.get("name")
        or item.get("title")
        or ""
    )


def add_to_recommended(
    db: dict,
    items: Iterable[dict],
    date: str,
    promoted_from_watch: bool = False,
) -> list[str]:
    """Persist ``top_test`` items to the recommended DB.

    Skips entries already present (URL is the key). Returns the list of
    newly-added URLs for logging.
    """
    skills = db.setdefault("skills", {})
    added: list[str] = []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        url = it.get("url") or ""
        if not url or url in skills:
            continue
        scores = it.get("scores") if isinstance(it.get("scores"), dict) else {}
        skills[url] = {
            "repo_full_name": _repo_full_name(it),
            "title": it.get("name") or _repo_full_name(it),
            "url": url,
            "category": it.get("category") or "general_skill",
            "skills_in_repo": list(it.get("skills_in_repo") or []),
            "skills_count": len(it.get("skills_in_repo") or []),
            "stars": it.get("stars"),
            "first_recommended": date,
            "final_score": it.get("final_score"),
            "confidence": it.get("confidence"),
            "test_steps": list(it.get("test_steps") or []),
            "metric": it.get("metric") or "",
            "scores": dict(scores),
            "promoted_from_watch": bool(
                promoted_from_watch or it.get("graduated_from_watch")
            ),
        }
        added.append(url)
    return added


def add_to_watchlist(
    db: dict,
    items: Iterable[dict],
    date: str,
    current_metrics_by_url: dict[str, dict] | None = None,
) -> list[str]:
    """Persist ``top_watch`` items to the watchlist DB.

    ``current_metrics_by_url`` maps each item's URL to a baseline metrics
    dict ({stars, skills_count, cross_source_count}). Items already on the
    watchlist are skipped. Returns the URLs newly added.
    """
    items_db = db.setdefault("items", {})
    added: list[str] = []
    today = _parse_iso(date)
    expires = (today + timedelta(days=WATCHLIST_TTL_DAYS)).isoformat()
    metrics_lookup = current_metrics_by_url or {}
    for it in items or []:
        if not isinstance(it, dict):
            continue
        url = it.get("url") or ""
        if not url or url in items_db:
            continue
        baseline = metrics_lookup.get(url) or {}
        items_db[url] = {
            "repo_full_name": _repo_full_name(it),
            "title": it.get("name") or _repo_full_name(it),
            "url": url,
            "category": it.get("category") or "general_skill",
            "added_date": date,
            "signal_to_wait": it.get("signal_to_wait") or "",
            "metric_baseline": {
                "stars": baseline.get("stars"),
                "skills_count": baseline.get("skills_count"),
                "cross_source_count": baseline.get("cross_source_count"),
            },
            "why_interesting": it.get("why_interesting") or "",
            "last_checked": date,
            "expires_at": expires,
        }
        added.append(url)
    return added


def remove_from_watchlist(db: dict, urls: Iterable[str]) -> int:
    items_db = db.setdefault("items", {})
    removed = 0
    for u in urls:
        if u in items_db:
            del items_db[u]
            removed += 1
    return removed


# ---------------------------------------------------------------------------
# graduation + pruning

def _parse_iso(value: str) -> _date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def _trigger_label(
    delta_stars: int | None,
    delta_skills: int | None,
    cross_now: int | None,
    cross_baseline: int | None,
) -> str:
    parts: list[str] = []
    if isinstance(delta_stars, int) and delta_stars >= GRADUATE_STAR_DELTA:
        parts.append(f"stars +{delta_stars}")
    if isinstance(delta_skills, int) and delta_skills >= GRADUATE_SKILLS_DELTA:
        parts.append(f"+{delta_skills} new skills")
    if (
        isinstance(cross_now, int)
        and isinstance(cross_baseline, int)
        and cross_now > cross_baseline
    ):
        parts.append(f"now in {cross_now} sources")
    elif isinstance(cross_now, int) and cross_baseline is None and cross_now > 1:
        parts.append(f"now in {cross_now} sources")
    return ", ".join(parts) or "signal met"


def check_watchlist_graduates(
    db: dict, fresh_items_with_deltas: list[dict]
) -> list[dict]:
    """Find watchlist items whose growth thresholds were met.

    For each watchlist URL we look for a matching entry in
    ``fresh_items_with_deltas`` (matched by URL). If found AND any of these
    is true:

    - ``delta_stars`` >= 5
    - ``delta_skills_count`` >= 1
    - cross_source_count grew vs the stored baseline

    we return the item as a graduate. ``last_checked`` is updated on every
    watchlist entry regardless.

    Each returned dict is the original watchlist entry plus
    ``graduated=True`` and a human-readable ``trigger`` string.
    """
    items_db = db.setdefault("items", {})
    today_iso = datetime.utcnow().strftime("%Y-%m-%d")
    fresh_by_url: dict[str, dict] = {
        it.get("url"): it for it in fresh_items_with_deltas or [] if it.get("url")
    }
    graduates: list[dict] = []
    for url, entry in items_db.items():
        if not isinstance(entry, dict):
            continue
        entry["last_checked"] = today_iso
        fresh = fresh_by_url.get(url)
        if not fresh:
            continue
        delta_stars = fresh.get("delta_stars")
        delta_skills = fresh.get("delta_skills_count")
        cross_now = fresh.get("cross_source_count")
        baseline = entry.get("metric_baseline") or {}
        cross_baseline = baseline.get("cross_source_count")

        promoted = False
        if isinstance(delta_stars, int) and delta_stars >= GRADUATE_STAR_DELTA:
            promoted = True
        if isinstance(delta_skills, int) and delta_skills >= GRADUATE_SKILLS_DELTA:
            promoted = True
        if (
            isinstance(cross_now, int)
            and isinstance(cross_baseline, int)
            and cross_now > cross_baseline
        ):
            promoted = True

        if promoted:
            grad = dict(entry)
            grad["graduated"] = True
            grad["trigger"] = _trigger_label(
                delta_stars, delta_skills, cross_now, cross_baseline
            )
            grad["fresh_item"] = fresh
            graduates.append(grad)
    return graduates


def prune_expired(db: dict, today_iso: str) -> list[str]:
    """Drop watchlist items whose ``expires_at`` is past. Returns dropped URLs."""
    items_db = db.setdefault("items", {})
    try:
        today = _parse_iso(today_iso)
    except ValueError:
        return []
    expired: list[str] = []
    for url, entry in list(items_db.items()):
        exp = (entry or {}).get("expires_at") or ""
        try:
            exp_date = _parse_iso(exp)
        except ValueError:
            continue
        if exp_date < today:
            expired.append(url)
            del items_db[url]
    return expired


__all__ = [
    "DEFAULT_RECOMMENDED_PATH",
    "DEFAULT_WATCHLIST_PATH",
    "WATCHLIST_TTL_DAYS",
    "load_recommended",
    "load_watchlist",
    "save_recommended",
    "save_watchlist",
    "is_recommended",
    "add_to_recommended",
    "add_to_watchlist",
    "remove_from_watchlist",
    "check_watchlist_graduates",
    "prune_expired",
]
