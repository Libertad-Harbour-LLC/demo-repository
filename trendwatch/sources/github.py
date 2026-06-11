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
import time
from datetime import datetime, timedelta, timezone

try:
    from ._http import (
        CODE_SEARCH_PACING_SECONDS,
        RATE_LIMITED,
        build_github_headers,
        get_json_with_backoff,
    )
except ImportError:
    from _http import (
        CODE_SEARCH_PACING_SECONDS,
        RATE_LIMITED,
        build_github_headers,
        get_json_with_backoff,
    )

REPO_SEARCH_URL = "https://api.github.com/search/repositories"
CODE_SEARCH_URL = "https://api.github.com/search/code"
REPO_API_URL = "https://api.github.com/repos"


def _headers() -> dict:
    return build_github_headers("trendwatch")


def _safe_get(url: str, params: dict | None = None, timeout: int = 30):
    return get_json_with_backoff(
        url,
        headers=_headers(),
        params=params,
        timeout=timeout,
        tag="trendwatch:github",
    )


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
    """Return raw candidates from code search across all queries.

    Sorted by `indexed` (most recently indexed by GitHub first) so we surface
    NEW SKILL.md files added in the last 24h, not the same top-relevance
    cache day after day. One page of 100 per query — page 2 almost never
    adds fresh items for a 24h window and doubles the request count against
    code search's tight 10-requests/min budget.

    Requests are paced CODE_SEARCH_PACING_SECONDS apart: the 2026-06-11 run
    showed that firing queries back-to-back gets every single one 429'd and
    the channel silently contributes zero candidates.
    """
    if not (os.environ.get("GH_SEARCH_TOKEN") or os.environ.get("GITHUB_TOKEN")):
        print(
            "[trendwatch.github] GITHUB_TOKEN missing — code search disabled, "
            "falling back to topic/description search only",
            file=sys.stderr,
        )
        return []
    out: list[dict] = []
    for i, q in enumerate(queries or []):
        if i:
            time.sleep(CODE_SEARCH_PACING_SECONDS)
        try:
            data = _safe_get(
                CODE_SEARCH_URL,
                params={
                    "q": q,
                    "per_page": 100,
                    "page": 1,
                    "sort": "indexed",
                    "order": "desc",
                },
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
    """Two passes per topic:
    - sort=stars: surfaces popular skill repos (regardless of recent push)
    - sort=updated: surfaces fresh activity (regardless of star count)
    Removed the pushed:> filter — was hiding popular but rarely-updated repos.
    """
    out: list[dict] = []
    for topic in topics or []:
        for sort_mode in ("stars", "updated"):
            try:
                data = _safe_get(
                    REPO_SEARCH_URL,
                    params={
                        "q": f"topic:{topic}",
                        "sort": sort_mode, "order": "desc", "per_page": 50,
                    },
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
                            "_from": f"topic_search:{sort_mode}",
                        }
                    )
            except Exception as exc:
                print(f"[trendwatch:github:topic_search] {topic!r}/{sort_mode}: {exc}", file=sys.stderr)
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


def _skills_meta_line(stars: int, skills: list[dict], description: str) -> str:
    """Format the meta line for a grouped repo item."""
    if skills:
        names = [s.get("name", "") for s in skills if s.get("name")]
        head = ", ".join(names[:3])
        suffix = "…" if len(names) > 3 else ""
        return f"⭐ {stars} • {len(names)} skills: {head}{suffix}"
    return f"⭐ {stars} • {description[:80]}"


def fetch_github(
    topics: list[str],
    queries: list[str],
    since_hours: int = 24,
    max_items: int = 15,
    verify: bool = True,
) -> list[dict]:
    """Fetch Claude Skill candidates from GitHub.

    Grouped by ``repo_full_name`` — ONE item per repo, with all skill folders
    listed inside ``skills``. Returns up to ``max_items`` items.

    Each item has shape::

        {"source": "github",
         "title": "<owner/repo>",
         "url": "<link to .claude/skills folder if verified, else repo root>",
         "meta": "⭐ N • K skills: name1, name2, name3…" or "⭐ N • <desc>",
         "verified": bool,
         "skill_path": ".claude/skills",
         "repo_full_name": str,
         "stars": int,
         "pushed_at": iso,
         "skills": [{"name": str, "path": str, "url": str}, ...],
         "skills_count": int}
    """
    try:
        since_date = (
            datetime.now(timezone.utc) - timedelta(hours=since_hours)
        ).date().isoformat()

        raw: list[dict] = []
        raw.extend(_code_search(queries or [], since_date))
        raw.extend(_topic_search(topics or [], since_date))
        raw.extend(_description_search(since_date))

        # Group all candidates by repo_full_name; keep first candidate per repo
        # but remember whether any code_search candidate carried a path hint.
        repos: dict[str, dict] = {}
        code_search_paths: dict[str, str] = {}
        for cand in raw:
            full = cand.get("repo_full_name") or ""
            if not full:
                continue
            if full not in repos:
                repos[full] = cand
            if cand.get("_from") == "code_search" and cand.get("skill_path"):
                code_search_paths.setdefault(full, cand.get("skill_path"))

        items: list[dict] = []
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

        for full, cand in repos.items():
            try:
                meta = _meta_for(full) if (verify or not cand.get("stars")) else {}
                stars = cand.get("stars") or meta.get("stars") or 0
                pushed_at = cand.get("pushed_at") or meta.get("pushed_at") or ""
                description = cand.get("description") or meta.get("description") or ""
                branch = cand.get("default_branch") or meta.get("default_branch") or "main"
                repo_html = cand.get("repo_html_url") or f"https://github.com/{full}"
                skills_dir_url = _build_skill_dir_url(full, ".claude/skills", branch)

                if verify:
                    dirs = _dirs_for(full)
                    if dirs == RATE_LIMITED:
                        # Verification unknown — keep as unverified single repo item.
                        items.append(
                            {
                                "source": "github",
                                "title": full,
                                "url": repo_html,
                                "meta": _skills_meta_line(stars, [], description),
                                "verified": False,
                                "skill_path": ".claude/skills",
                                "repo_full_name": full,
                                "stars": stars,
                                "pushed_at": pushed_at,
                                "skills": [],
                                "skills_count": 0,
                            }
                        )
                        continue
                    if dirs is None:
                        # No .claude/skills directory found.
                        cs_path = code_search_paths.get(full)
                        if cs_path:
                            # Code-search saw a SKILL.md at a non-standard path;
                            # emit single unverified repo item pointing at it.
                            items.append(
                                {
                                    "source": "github",
                                    "title": full,
                                    "url": _build_skill_url(full, cs_path, branch),
                                    "meta": _skills_meta_line(stars, [], description),
                                    "verified": False,
                                    "skill_path": cs_path,
                                    "repo_full_name": full,
                                    "stars": stars,
                                    "pushed_at": pushed_at,
                                    "skills": [],
                                    "skills_count": 0,
                                }
                            )
                        # else: topic/desc-search candidate without skills dir — drop
                        continue

                    # 200 OK: build ONE repo item listing all skill dirs.
                    if not dirs:
                        # .claude/skills exists but empty — skip
                        continue
                    skills_list = [
                        {
                            "name": name,
                            "path": f".claude/skills/{name}",
                            "url": _build_skill_dir_url(full, f".claude/skills/{name}", branch),
                        }
                        for name in dirs
                    ]
                    items.append(
                        {
                            "source": "github",
                            "title": full,
                            "url": skills_dir_url,
                            "meta": _skills_meta_line(stars, skills_list, description),
                            "verified": True,
                            "skill_path": ".claude/skills",
                            "repo_full_name": full,
                            "stars": stars,
                            "pushed_at": pushed_at,
                            "skills": skills_list,
                            "skills_count": len(skills_list),
                        }
                    )
                else:
                    # No verification — emit a single unverified repo item.
                    cs_path = code_search_paths.get(full)
                    url = _build_skill_url(full, cs_path, branch) if cs_path else repo_html
                    items.append(
                        {
                            "source": "github",
                            "title": full,
                            "url": url,
                            "meta": _skills_meta_line(stars, [], description),
                            "verified": False,
                            "skill_path": cs_path or ".claude/skills",
                            "repo_full_name": full,
                            "stars": stars,
                            "pushed_at": pushed_at,
                            "skills": [],
                            "skills_count": 0,
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
