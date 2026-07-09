"""skills.sh source — searches the Vercel skills registry.

skills.sh is the hosted index behind ``npx skills find`` (vercel-labs/skills).
Its killer signal is **install counts** — real usage telemetry aggregated from
CLI installs — which is a far stronger traction indicator for niche skills
than GitHub stars. One GET per domain query:

    GET https://skills.sh/api/search?q=<query>&limit=N
    -> {"skills": [{"id", "name", "installs", "source"}, ...]}

``source`` is ``owner/repo`` — the same key our GitHub source groups by, so
the orchestrator can merge the installs signal onto GitHub-discovered items
and keep only registry-exclusive repos as standalone entries.

No auth required. The API is unofficial: any failure returns [] and the run
continues on the other sources (standard per-source resilience rule).
"""
from __future__ import annotations

import os
import sys
import time
from typing import Callable

import requests

SEARCH_URL = os.environ.get("SKILLS_SH_API_URL", "https://skills.sh/api/search").strip()
REQUEST_PACING_SECONDS = 0.5  # be polite; no documented rate limit
PER_QUERY_LIMIT = 20


def _default_http_get(url: str, params: dict, timeout: int = 20):
    r = requests.get(
        url, params=params, timeout=timeout,
        headers={"User-Agent": "trendwatch-skill-radar"},
    )
    if r.status_code != 200:
        return None
    try:
        return r.json()
    except ValueError:
        return None


def _installs_meta(installs: int, skills: list[str]) -> str:
    head = ", ".join(skills[:3])
    suffix = "…" if len(skills) > 3 else ""
    return f"⬇ {installs} installs • {len(skills)} skills: {head}{suffix}"


def fetch_skills_sh(
    queries: list[str],
    max_items: int = 30,
    http_get: Callable = _default_http_get,
    per_query_limit: int = PER_QUERY_LIMIT,
) -> list[dict]:
    """Fetch skill repos from the skills.sh registry, grouped by owner/repo.

    Item shape mirrors the github source (one item per repo) plus the extra
    ``installs`` field::

        {"source": "skills_sh", "title": "owner/repo",
         "url": "https://github.com/owner/repo",
         "meta": "⬇ N installs • K skills: a, b, c…",
         "verified": False, "skill_path": "", "repo_full_name": "owner/repo",
         "stars": 0, "pushed_at": "", "skills": [{"name":...}],
         "skills_count": K, "installs": N}
    """
    repos: dict[str, dict] = {}
    try:
        for i, q in enumerate(queries or []):
            if i:
                time.sleep(REQUEST_PACING_SECONDS)
            try:
                data = http_get(SEARCH_URL, {"q": q, "limit": str(per_query_limit)})
            except Exception as exc:
                print(f"[trendwatch:skills_sh] {q!r}: {exc}", file=sys.stderr)
                continue
            if not isinstance(data, dict):
                continue
            for sk in data.get("skills") or []:
                if not isinstance(sk, dict):
                    continue
                full = (sk.get("source") or "").strip().strip("/")
                if full.count("/") != 1:  # need owner/repo
                    continue
                name = (sk.get("name") or sk.get("id") or "").strip()
                try:
                    installs = int(sk.get("installs") or 0)
                except (TypeError, ValueError):
                    installs = 0
                agg = repos.setdefault(
                    full, {"skills": {}, "installs": 0}
                )
                # Same skill can surface under several queries — count once.
                if name and name not in agg["skills"]:
                    agg["skills"][name] = installs
                    agg["installs"] += installs

        items: list[dict] = []
        for full, agg in repos.items():
            skill_names = sorted(
                agg["skills"], key=lambda n: -agg["skills"][n]
            )
            items.append(
                {
                    "source": "skills_sh",
                    "title": full,
                    "url": f"https://github.com/{full}",
                    "meta": _installs_meta(agg["installs"], skill_names),
                    "verified": False,
                    "skill_path": "",
                    "repo_full_name": full,
                    "stars": 0,
                    "pushed_at": "",
                    "skills": [{"name": n, "path": "", "url": ""} for n in skill_names],
                    "skills_count": len(skill_names),
                    "installs": agg["installs"],
                }
            )
        items.sort(key=lambda x: -(x.get("installs") or 0))
        return items[:max_items]
    except Exception as exc:
        print(f"[trendwatch:skills_sh] error: {exc}", file=sys.stderr)
        return []


def merge_installs(items_by_source: dict[str, list[dict]]) -> None:
    """Fold the skills.sh installs signal into GitHub-discovered items.

    For every skills_sh repo that the GitHub source ALSO found (matched by
    ``repo_full_name``), copy ``installs`` onto the GitHub item, append the
    signal to its meta line, and drop the standalone skills_sh entry — so one
    repo never appears as two digest items. Registry-exclusive repos stay in
    the skills_sh list. Mutates ``items_by_source`` in place.
    """
    sh_items = items_by_source.get("skills_sh") or []
    if not sh_items:
        return
    gh_by_repo = {
        it.get("repo_full_name"): it
        for it in items_by_source.get("github") or []
        if it.get("repo_full_name")
    }
    remaining: list[dict] = []
    merged = 0
    for it in sh_items:
        twin = gh_by_repo.get(it.get("repo_full_name"))
        if twin is None:
            remaining.append(it)
            continue
        installs = it.get("installs") or 0
        twin["installs"] = installs
        if installs and "installs" not in (twin.get("meta") or ""):
            twin["meta"] = f"{twin.get('meta') or ''} • ⬇ {installs} installs".strip(" •")
        merged += 1
    items_by_source["skills_sh"] = remaining
    if merged:
        print(
            f"[trendwatch:skills_sh] merged installs into {merged} github item(s); "
            f"{len(remaining)} registry-only repo(s) kept",
            file=sys.stderr,
        )


__all__ = ["fetch_skills_sh", "merge_installs", "SEARCH_URL"]
