"""GitHub source — searches for Claude Code Skills.

Strategy:
  A. Code search for SKILL.md files matching config.GITHUB_CODE_QUERIES.
  B. Repo search by topic (config.GITHUB_TOPICS).
  C. Keyword search in repository description.
All candidates are merged + deduped by (repo_full_name, skill_path) and
optionally verified by hitting the repo's /.claude/skills/ contents endpoint.

GitHub Code Search REQUIRES authentication. The workflow already provides
GITHUB_TOKEN; for local dry-run set it manually (public_repo scope).
"""
import os
import sys
from datetime import datetime, timedelta, timezone

import requests

REPO_SEARCH_URL = "https://api.github.com/search/repositories"
CODE_SEARCH_URL = "https://api.github.com/search/code"
REPO_API_URL = "https://api.github.com/repos"


def _headers() -> dict:
    h = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "trendwatch",
    }
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


RATE_LIMITED = "RATE_LIMITED"


def _safe_get(url: str, params: dict | None = None, timeout: int = 30):
    try:
        resp = requests.get(url, headers=_headers(), params=params, timeout=timeout)
        if resp.status_code == 404:
            return None
        if (
            resp.status_code == 403
            and resp.headers.get("X-RateLimit-Remaining") == "0"
        ):
            return RATE_LIMITED
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        print(f"[trendwatch:github] GET {url} failed: {exc}", file=sys.stderr)
        return None


def _default_branch(full_name: str) -> str:
    data = _safe_get(f"{REPO_API_URL}/{full_name}") or {}
    return data.get("default_branch") or "main"


def _build_skill_url(full_name: str, path: str, branch: str | None = None) -> str:
    """Build a github.com URL pointing at the SKILL.md path or the skill dir."""
    branch = branch or "main"
    # Normalize to point at the SKILL.md file if it's a file path, else the dir.
    return f"https://github.com/{full_name}/blob/{branch}/{path}"


def _build_skill_dir_url(full_name: str, dir_path: str, branch: str | None = None) -> str:
    branch = branch or "main"
    return f"https://github.com/{full_name}/tree/{branch}/{dir_path}"


def _code_search(queries: list[str], since_date: str) -> list[dict]:
    """Return raw candidates from code search across all queries."""
    if not os.environ.get("GITHUB_TOKEN"):
        print(
            "[trendwatch.github] GITHUB_TOKEN missing — code search disabled, "
            "falling back to topic/description search only",
            file=sys.stderr,
        )
        return []
    out: list[dict] = []
    for q in queries or []:
        try:
            data = _safe_get(
                CODE_SEARCH_URL, params={"q": q, "per_page": 20}
            )
            if not data or data == RATE_LIMITED:
                continue
            for it in data.get("items", []) or []:
                repo = it.get("repository") or {}
                full_name = repo.get("full_name")
                path = it.get("path")
                if not full_name or not path:
                    continue
                out.append(
                    {
                        "repo_full_name": full_name,
                        "skill_path": path,
                        "repo_html_url": repo.get("html_url") or f"https://github.com/{full_name}",
                        "description": repo.get("description") or "",
                        "_from": "code_search",
                    }
                )
        except Exception as exc:
            print(f"[trendwatch:github:code_search] {q!r}: {exc}", file=sys.stderr)
            continue
    return out


def _topic_search(topics: list[str], since_date: str) -> list[dict]:
    out: list[dict] = []
    for topic in topics or []:
        try:
            q = f"topic:{topic} pushed:>{since_date}"
            data = _safe_get(
                REPO_SEARCH_URL,
                params={"q": q, "sort": "updated", "order": "desc", "per_page": 20},
            )
            if not data:
                continue
            for repo in data.get("items", []) or []:
                full_name = repo.get("full_name")
                if not full_name:
                    continue
                out.append(
                    {
                        "repo_full_name": full_name,
                        "skill_path": "",  # unknown until verification
                        "repo_html_url": repo.get("html_url") or f"https://github.com/{full_name}",
                        "description": repo.get("description") or "",
                        "stars": repo.get("stargazers_count") or 0,
                        "pushed_at": repo.get("pushed_at") or "",
                        "default_branch": repo.get("default_branch") or "main",
                        "_from": "topic_search",
                    }
                )
        except Exception as exc:
            print(f"[trendwatch:github:topic_search] {topic!r}: {exc}", file=sys.stderr)
            continue
    return out


def _description_search(since_date: str) -> list[dict]:
    out: list[dict] = []
    try:
        q = f'"claude skill" in:description pushed:>{since_date}'
        data = _safe_get(
            REPO_SEARCH_URL,
            params={"q": q, "sort": "updated", "order": "desc", "per_page": 10},
        )
        if not data:
            return out
        for repo in data.get("items", []) or []:
            full_name = repo.get("full_name")
            if not full_name:
                continue
            out.append(
                {
                    "repo_full_name": full_name,
                    "skill_path": "",
                    "repo_html_url": repo.get("html_url") or f"https://github.com/{full_name}",
                    "description": repo.get("description") or "",
                    "stars": repo.get("stargazers_count") or 0,
                    "pushed_at": repo.get("pushed_at") or "",
                    "default_branch": repo.get("default_branch") or "main",
                    "_from": "desc_search",
                }
            )
    except Exception as exc:
        print(f"[trendwatch:github:desc_search] {exc}", file=sys.stderr)
    return out


def _repo_meta(full_name: str) -> dict:
    """Fetch stars/branch/pushed_at/description for a repo. None-safe."""
    data = _safe_get(f"{REPO_API_URL}/{full_name}") or {}
    return {
        "stars": data.get("stargazers_count") or 0,
        "default_branch": data.get("default_branch") or "main",
        "pushed_at": data.get("pushed_at") or "",
        "description": data.get("description") or "",
    }


def _list_skill_dirs(full_name: str):
    """Return list of skill directory names under .claude/skills.

    Returns:
        list[str] — directories found (possibly empty if .claude/skills exists but empty).
        None — repo has no .claude/skills directory (404).
        RATE_LIMITED — verification unknown due to rate-limit; caller should keep
        the candidate as unverified rather than dropping it.
    """
    data = _safe_get(f"{REPO_API_URL}/{full_name}/contents/.claude/skills")
    if data == RATE_LIMITED:
        return RATE_LIMITED
    if data is None:
        return None
    if not isinstance(data, list):
        return []
    return [
        entry.get("name")
        for entry in data
        if isinstance(entry, dict) and entry.get("type") == "dir" and entry.get("name")
    ]


def fetch_github(
    topics: list[str],
    queries: list[str],
    since_hours: int = 24,
    max_items: int = 15,
    verify: bool = True,
) -> list[dict]:
    """Fetch Claude Skill candidates from GitHub.

    Deduped by (repo_full_name, skill_path). Returns up to ``max_items`` items.
    Each item has shape::

        {"source": "github",
         "title": "<owner/repo>: <skill_name>",
         "url": "...",
         "meta": "⭐ N • <repo description first 80 chars>",
         "verified": bool,
         "skill_path": str,
         "repo_full_name": str,
         "stars": int,
         "pushed_at": iso}
    """
    try:
        since_date = (
            datetime.now(timezone.utc) - timedelta(hours=since_hours)
        ).date().isoformat()

        raw: list[dict] = []
        raw.extend(_code_search(queries or [], since_date))
        raw.extend(_topic_search(topics or [], since_date))
        raw.extend(_description_search(since_date))

        # Dedupe by (repo_full_name, skill_path)
        seen: dict[tuple[str, str], dict] = {}
        for cand in raw:
            full = cand.get("repo_full_name") or ""
            path = cand.get("skill_path") or ""
            key = (full, path)
            if not full:
                continue
            if key not in seen:
                seen[key] = cand

        # Verification pass: for each unique repo, optionally inspect
        # /.claude/skills/ to enumerate skill folders.
        items: list[dict] = []
        # Cache per-repo metadata + dir listings so we hit the API once per repo.
        repo_meta_cache: dict[str, dict] = {}
        repo_dirs_cache: dict = {}

        def _meta_for(full: str) -> dict:
            if full not in repo_meta_cache:
                repo_meta_cache[full] = _repo_meta(full)
            return repo_meta_cache[full]

        def _dirs_for(full: str):
            if full not in repo_dirs_cache:
                repo_dirs_cache[full] = _list_skill_dirs(full)
            return repo_dirs_cache[full]

        produced_repos: set[str] = set()

        for (full, path), cand in seen.items():
            try:
                meta = _meta_for(full) if (verify or not cand.get("stars")) else {}
                stars = cand.get("stars") or meta.get("stars") or 0
                pushed_at = cand.get("pushed_at") or meta.get("pushed_at") or ""
                description = cand.get("description") or meta.get("description") or ""
                branch = cand.get("default_branch") or meta.get("default_branch") or "main"

                if verify:
                    dirs = _dirs_for(full)
                    if dirs == RATE_LIMITED:
                        # Verification unknown — keep as unverified candidate.
                        items.append(
                            {
                                "source": "github",
                                "title": f"{full}: {path or '(repo)'}",
                                "url": _build_skill_url(full, path, branch) if path else (cand.get("repo_html_url") or f"https://github.com/{full}"),
                                "meta": f"⭐ {stars} • {description[:80]}",
                                "verified": False,
                                "skill_path": path,
                                "repo_full_name": full,
                                "stars": stars,
                                "pushed_at": pushed_at,
                            }
                        )
                        continue
                    if dirs is None:
                        # No .claude/skills directory in the repo.
                        if cand.get("_from") == "code_search" and path:
                            # Code search matched a different layout (e.g. skills/foo/SKILL.md)
                            items.append(
                                {
                                    "source": "github",
                                    "title": f"{full}: {path}",
                                    "url": _build_skill_url(full, path, branch),
                                    "meta": f"⭐ {stars} • {description[:80]}",
                                    "verified": False,
                                    "skill_path": path,
                                    "repo_full_name": full,
                                    "stars": stars,
                                    "pushed_at": pushed_at,
                                }
                            )
                        # else: topic/desc-search candidate without .claude/skills — drop
                        continue

                    # 200 OK: enumerate one item per skill directory, once per repo.
                    if full in produced_repos:
                        continue
                    produced_repos.add(full)
                    if not dirs:
                        # .claude/skills exists but empty — skip
                        continue
                    skill_count = len(dirs)
                    for skill_name in dirs:
                        dir_path = f".claude/skills/{skill_name}"
                        items.append(
                            {
                                "source": "github",
                                "title": f"{full}: {skill_name}",
                                "url": _build_skill_dir_url(full, dir_path, branch),
                                "meta": f"⭐ {stars} • {skill_count} skills",
                                "verified": True,
                                "skill_path": dir_path,
                                "repo_full_name": full,
                                "stars": stars,
                                "pushed_at": pushed_at,
                            }
                        )
                else:
                    # No verification — emit raw candidate.
                    title_tail = path or "(repo)"
                    items.append(
                        {
                            "source": "github",
                            "title": f"{full}: {title_tail}",
                            "url": _build_skill_url(full, path, branch) if path else (cand.get("repo_html_url") or f"https://github.com/{full}"),
                            "meta": f"⭐ {stars} • {description[:80]}",
                            "verified": False,
                            "skill_path": path,
                            "repo_full_name": full,
                            "stars": stars,
                            "pushed_at": pushed_at,
                        }
                    )
            except Exception as exc:
                print(f"[trendwatch:github:item] {full!r}: {exc}", file=sys.stderr)
                continue

        # Sort: verified first, then stars desc.
        items.sort(key=lambda x: (not x.get("verified", False), -(x.get("stars") or 0)))
        return items[:max_items]
    except Exception as exc:
        print(f"[trendwatch:github] error: {exc}", file=sys.stderr)
        return []
