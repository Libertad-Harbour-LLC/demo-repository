"""GitHub source for the Open Source radar — repo-level discovery.

Unlike the skills/workflows fetchers (which look for SKILL.md / workflow JSON
*files*), this finds whole **repositories** that are deployable OSS products:
topic search + name/description/readme phrase search, plus the seed repos
injected as candidates. One item per repo. No file-signature verification —
the analyzer decides whether a repo is a ready-to-use product vs a library.
"""
from __future__ import annotations

import sys

from trendwatch.sources._http import (
    CODE_SEARCH_PACING_SECONDS,
    RATE_LIMITED,
    build_github_headers,
    get_json_with_backoff,
)

REPO_SEARCH_URL = "https://api.github.com/search/repositories"
REPO_API_URL = "https://api.github.com/repos"


def _headers() -> dict:
    return build_github_headers("opensource-radar")


def _get(url: str, params: dict | None = None):
    return get_json_with_backoff(
        url, headers=_headers(), params=params, tag="opensource:github"
    )


def _meta_line(stars: int, description: str) -> str:
    desc = (description or "").strip()
    return f"⭐ {stars} • {desc[:120]}" if desc else f"⭐ {stars}"


def _item_from_repo(repo: dict) -> dict | None:
    full = repo.get("full_name")
    if not full:
        return None
    stars = repo.get("stargazers_count") or 0
    return {
        "source": "github",
        "title": full,
        "url": repo.get("html_url") or f"https://github.com/{full}",
        "meta": _meta_line(stars, repo.get("description") or ""),
        "repo_full_name": full,
        "stars": stars,
        "forks": repo.get("forks_count"),
        "pushed_at": repo.get("pushed_at") or "",
        "description": repo.get("description") or "",
        "default_branch": repo.get("default_branch") or "main",
        "topics": repo.get("topics") or [],
    }


def _topic_search(topics: list[str]) -> list[dict]:
    out: list[dict] = []
    for topic in topics or []:
        for sort_mode in ("stars", "updated"):
            data = _get(
                REPO_SEARCH_URL,
                params={
                    "q": f"topic:{topic}",
                    "sort": sort_mode,
                    "order": "desc",
                    "per_page": 40,
                },
            )
            if not data or data == RATE_LIMITED:
                continue
            for repo in data.get("items", []) or []:
                it = _item_from_repo(repo)
                if it:
                    out.append(it)
    return out


def _description_search(queries: list[str]) -> list[dict]:
    out: list[dict] = []
    for q in queries or []:
        data = _get(
            REPO_SEARCH_URL,
            params={"q": q, "sort": "stars", "order": "desc", "per_page": 40},
        )
        if not data or data == RATE_LIMITED:
            continue
        for repo in data.get("items", []) or []:
            it = _item_from_repo(repo)
            if it:
                out.append(it)
    return out


def _seed_candidates(seed_urls: list[str]) -> list[dict]:
    """Fetch repo meta for each seed URL so the analyzer evaluates them."""
    out: list[dict] = []
    for url in seed_urls or []:
        full = _owner_repo(url)
        if not full:
            continue
        data = _get(f"{REPO_API_URL}/{full}")
        if not data or data == RATE_LIMITED:
            # keep the seed as a minimal candidate even if meta failed
            out.append({
                "source": "github",
                "title": full,
                "url": f"https://github.com/{full}",
                "meta": "⭐ ? • seed",
                "repo_full_name": full,
                "stars": 0,
                "pushed_at": "",
                "description": "",
                "default_branch": "main",
                "_seed": True,
            })
            continue
        it = _item_from_repo(data)
        if it:
            it["_seed"] = True
            out.append(it)
    return out


def _owner_repo(url: str) -> str | None:
    import re
    m = re.search(r"github\.com/([^/\s]+)/([^/\s#?]+)", url or "")
    if not m:
        return None
    repo = m.group(2)
    if repo.endswith(".git"):
        repo = repo[:-4]
    return f"{m.group(1)}/{repo}"


def fetch_opensource(
    topics: list[str],
    desc_queries: list[str],
    seed_repos: list[str],
    max_items: int = 80,
) -> list[dict]:
    """Return up to ``max_items`` deployable-OSS repo candidates (seeds first)."""
    try:
        raw: list[dict] = []
        raw.extend(_seed_candidates(seed_repos or []))
        raw.extend(_topic_search(topics or []))
        raw.extend(_description_search(desc_queries or []))

        # Dedupe by repo_full_name; first occurrence wins (seeds come first).
        seen: set[str] = set()
        items: list[dict] = []
        for it in raw:
            full = it.get("repo_full_name") or ""
            if not full or full in seen:
                continue
            seen.add(full)
            items.append(it)

        # Seeds first, then by stars desc.
        items.sort(key=lambda x: (not x.get("_seed", False), -(x.get("stars") or 0)))
        return items[:max_items]
    except Exception as exc:
        print(f"[opensource:github] error: {exc}", file=sys.stderr)
        return []
