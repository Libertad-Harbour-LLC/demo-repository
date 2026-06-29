"""Shared GitHub fetcher for n8n and Make workflow sources.

Mirrors ``trendwatch.sources.github`` but with three changes:
1. Code search returns *file paths* (one row per JSON file), not just repos —
   the workflow IS the JSON, so we want to track each one.
2. Verification fetches the JSON content (capped at MAX_BYTES) and checks for
   tool-specific signatures via a caller-supplied ``json_validator``.
3. Items are grouped by repo, with all matching JSONs listed in ``workflows``.

The two public modules ``n8n_github`` and ``make_github`` just call
``fetch_workflows`` with their own tool tag, topics, queries, and validator.
"""
from __future__ import annotations

import json as _json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import requests

from trendwatch.sources._http import (
    CODE_SEARCH_PACING_SECONDS,
    RATE_LIMITED,
    build_github_headers,
    get_json_with_backoff,
)

REPO_SEARCH_URL = "https://api.github.com/search/repositories"
CODE_SEARCH_URL = "https://api.github.com/search/code"
REPO_API_URL = "https://api.github.com/repos"
RAW_BASE = "https://raw.githubusercontent.com"


def _headers() -> dict:
    return build_github_headers("workflows-trendwatch")


def _safe_get(url: str, params: dict | None = None, timeout: int = 30):
    return get_json_with_backoff(
        url,
        headers=_headers(),
        params=params,
        timeout=timeout,
        tag="workflows:github",
    )


def _repo_meta(full_name: str) -> dict:
    data = _safe_get(f"{REPO_API_URL}/{full_name}") or {}
    return {
        "stars": data.get("stargazers_count") or 0,
        "default_branch": data.get("default_branch") or "main",
        "pushed_at": data.get("pushed_at") or "",
        "description": data.get("description") or "",
    }


def _raw_url(full_name: str, branch: str, path: str) -> str:
    return f"{RAW_BASE}/{full_name}/{branch}/{path.lstrip('/')}"


def _list_json_files(full_name: str, dir_path: str = "") -> list[str]:
    """List JSON files at the given directory in the repo (default branch).

    Used when a candidate came from topic_search (no code-search JSON-path
    hint). Without this, repos like nusquama/n8nworkflows.xyz (2360★) get
    dropped at the "no hinted_paths + verify=True → skip" branch even
    though their contents/workflows/*.json is exactly what we want.

    Returns up to 20 .json paths (relative to repo root). Empty list on
    any error (rate limit, 404, transient).
    """
    contents_url = f"{REPO_API_URL}/{full_name}/contents"
    if dir_path:
        contents_url += f"/{dir_path.lstrip('/').rstrip('/')}"
    data = _safe_get(contents_url)
    if not data or data == RATE_LIMITED or not isinstance(data, list):
        return []
    found: list[str] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        if entry.get("type") != "file":
            continue
        name = entry.get("name") or ""
        path = entry.get("path") or ""
        if name.lower().endswith(".json") and path:
            found.append(path)
        if len(found) >= 20:
            break
    return found


def _blob_url(full_name: str, branch: str, path: str) -> str:
    return f"https://github.com/{full_name}/blob/{branch}/{path.lstrip('/')}"


# JSON files that are never workflows — skip them during full enumeration.
_NON_WORKFLOW_JSON = {
    "package.json", "package-lock.json", "tsconfig.json", "composer.json",
    "manifest.json", "renovate.json", ".eslintrc.json", "babel.config.json",
    "lerna.json", "nx.json", "components.json", "vercel.json", "now.json",
}


def list_repo_workflows(
    full_name: str,
    branch: str,
    json_validator,
    max_json_bytes: int = 200_000,
    limit: int = 25,
) -> list[dict]:
    """Enumerate ALL verified workflow JSONs in a repo via the recursive git
    tree (used when a repo is PROMOTED, to explode it into per-workflow catalog
    entries). Returns up to ``limit`` ``{name, path, json_url, blob_url}`` dicts;
    empty on any failure. Bounded: at most ``limit`` JSON fetches+validations.
    """
    tree = _safe_get(
        f"{REPO_API_URL}/{full_name}/git/trees/{branch}",
        params={"recursive": "1"},
    )
    if not tree or tree == RATE_LIMITED or not isinstance(tree, dict):
        return []
    paths: list[str] = []
    for node in tree.get("tree") or []:
        if not isinstance(node, dict) or node.get("type") != "blob":
            continue
        path = node.get("path") or ""
        if not path.lower().endswith(".json"):
            continue
        if os.path.basename(path).lower() in _NON_WORKFLOW_JSON:
            continue
        paths.append(path)
    out: list[dict] = []
    for path in paths:
        if len(out) >= limit:
            break
        raw_url = _raw_url(full_name, branch, path)
        parsed = _fetch_json_capped(raw_url, max_json_bytes)
        ok = False
        if isinstance(parsed, (dict, list)):
            try:
                ok = bool(json_validator(parsed))
            except Exception:
                ok = False
        if ok:
            name = os.path.basename(path)
            if name.lower().endswith(".json"):
                name = name[:-5]
            out.append({
                "name": name,
                "path": path,
                "json_url": raw_url,
                "blob_url": _blob_url(full_name, branch, path),
            })
    return out


def _fetch_json_capped(raw_url: str, max_bytes: int) -> dict | None:
    """Best-effort: download up to ``max_bytes`` and parse JSON.

    Returns the parsed object on success. Returns ``None`` on any failure
    (network, oversize, parse). Uses a Range header to cap bandwidth; if the
    server doesn't honor Range the response is still bounded by ``max_bytes``
    via iter_content.
    """
    try:
        headers = {
            "User-Agent": "workflows-trendwatch",
            "Range": f"bytes=0-{max_bytes - 1}",
            "Accept": "application/json, text/plain, */*",
        }
        resp = requests.get(raw_url, headers=headers, timeout=20, stream=True)
        if resp.status_code not in (200, 206):
            return None
        chunks: list[bytes] = []
        total = 0
        for chunk in resp.iter_content(chunk_size=16_384):
            if not chunk:
                continue
            chunks.append(chunk)
            total += len(chunk)
            if total >= max_bytes:
                break
        body = b"".join(chunks)[:max_bytes]
        try:
            return _json.loads(body.decode("utf-8", errors="replace"))
        except _json.JSONDecodeError:
            return None
    except Exception as exc:
        print(f"[workflows:github] raw fetch failed {raw_url}: {exc}", file=sys.stderr)
        return None


def _code_search(queries: list[str]) -> list[dict]:
    """One page of 100 per query, sorted by freshest-indexed, paced
    CODE_SEARCH_PACING_SECONDS apart — code search allows only ~10
    requests/min and back-to-back queries get every request 429'd
    (observed in the 2026-06-11 production run).
    """
    if not (os.environ.get("GH_SEARCH_TOKEN") or os.environ.get("GITHUB_TOKEN")):
        print(
            "[workflows:github] GITHUB_TOKEN missing — code search disabled",
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
                if not full_name or not path or not path.endswith(".json"):
                    continue
                out.append(
                    {
                        "repo_full_name": full_name,
                        "json_path": path,
                        "repo_html_url": repo.get("html_url")
                        or f"https://github.com/{full_name}",
                        "description": repo.get("description") or "",
                        "_from": "code_search",
                    }
                )
        except Exception as exc:
            print(f"[workflows:github:code] {q!r}: {exc}", file=sys.stderr)
            continue
    return out


def _topic_search(topics: list[str], since_date: str) -> list[dict]:
    """Two passes per topic: sort=stars (high-signal repos regardless of recent
    activity) + sort=updated (fresh activity regardless of stars). Dropped the
    pushed:>since_date filter that was hiding popular but rarely-updated repos.
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
                            "json_path": "",
                            "repo_html_url": repo.get("html_url")
                            or f"https://github.com/{full_name}",
                            "description": repo.get("description") or "",
                            "stars": repo.get("stargazers_count") or 0,
                            "pushed_at": repo.get("pushed_at") or "",
                            "default_branch": repo.get("default_branch") or "main",
                            "_from": f"topic_search:{sort_mode}",
                        }
                    )
            except Exception as exc:
                print(f"[workflows:github:topic] {topic!r}/{sort_mode}: {exc}", file=sys.stderr)
                continue
    return out


def _description_search(keyword: str, since_date: str) -> list[dict]:
    out: list[dict] = []
    try:
        q = f'"{keyword}" in:description pushed:>{since_date}'
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
                    "json_path": "",
                    "repo_html_url": repo.get("html_url")
                    or f"https://github.com/{full_name}",
                    "description": repo.get("description") or "",
                    "stars": repo.get("stargazers_count") or 0,
                    "pushed_at": repo.get("pushed_at") or "",
                    "default_branch": repo.get("default_branch") or "main",
                    "_from": "desc_search",
                }
            )
    except Exception as exc:
        print(f"[workflows:github:desc] {exc}", file=sys.stderr)
    return out


def _meta_line(stars: int, workflows: list[dict], description: str) -> str:
    if workflows:
        names = [w.get("name", "") for w in workflows if w.get("name")]
        head = ", ".join(names[:3])
        suffix = "…" if len(names) > 3 else ""
        return f"⭐ {stars} • {len(names)} wf: {head}{suffix}"
    return f"⭐ {stars} • {description[:80]}"


def fetch_workflows(
    tool: str,
    source_label: str,
    topics: list[str],
    code_queries: list[str],
    description_keywords: list[str],
    json_validator,
    since_hours: int = 24,
    max_items: int = 15,
    verify: bool = True,
    max_json_bytes: int = 200_000,
) -> list[dict]:
    """Fetch workflow candidates from GitHub for a given tool.

    Returned item shape (one per repo):

        {
          "source": <source_label>,    # e.g. "github_n8n"
          "tool":   <tool>,            # "n8n" | "make"
          "title":  "owner/repo: <first-json-basename>" or "owner/repo",
          "url":    repo URL,
          "json_url": raw URL to the FIRST matching JSON (for the digest),
          "docs_url": repo URL (README implicit),
          "meta":   "⭐ N • K wf: name1, name2…",
          "verified": bool,
          "json_path": str,
          "repo_full_name": str,
          "stars": int,
          "pushed_at": iso,
          "workflow_count": int,
          "workflows": [{"name": str, "path": str, "json_url": str,
                         "blob_url": str, "verified": bool}, ...],
        }
    """
    try:
        since_date = (
            datetime.now(timezone.utc) - timedelta(hours=since_hours)
        ).date().isoformat()

        raw: list[dict] = []
        raw.extend(_code_search(code_queries or []))
        raw.extend(_topic_search(topics or [], since_date))
        for kw in description_keywords or []:
            raw.extend(_description_search(kw, since_date))

        # Group all candidates by repo_full_name. Collect JSON path hints per repo.
        repos: dict[str, dict] = {}
        json_paths_per_repo: dict[str, set[str]] = {}
        for cand in raw:
            full = cand.get("repo_full_name") or ""
            if not full:
                continue
            if full not in repos:
                repos[full] = cand
            if cand.get("_from") == "code_search" and cand.get("json_path"):
                json_paths_per_repo.setdefault(full, set()).add(
                    cand["json_path"]
                )

        items: list[dict] = []
        meta_cache: dict[str, dict] = {}

        def _meta_for(full: str) -> dict:
            if full not in meta_cache:
                meta_cache[full] = _repo_meta(full)
            return meta_cache[full]

        for full, cand in repos.items():
            try:
                m = _meta_for(full) if (verify or not cand.get("stars")) else {}
                stars = cand.get("stars") or m.get("stars") or 0
                pushed_at = cand.get("pushed_at") or m.get("pushed_at") or ""
                description = cand.get("description") or m.get("description") or ""
                branch = (
                    cand.get("default_branch") or m.get("default_branch") or "main"
                )
                repo_html = cand.get("repo_html_url") or f"https://github.com/{full}"

                hinted_paths = sorted(json_paths_per_repo.get(full, set()))

                # Fallback discovery: if no code_search hint exists, this repo
                # came from topic_search only (e.g. topic:n8n-workflows on a
                # 2k-star catalog). Probe likely workflow directories so we
                # can actually verify and surface high-signal collections that
                # don't happen to match the rigid code_search query strings.
                if not hinted_paths:
                    for probe_dir in ("workflows", "n8n", "blueprints", ""):
                        discovered = _list_json_files(full, probe_dir)
                        if discovered:
                            hinted_paths = discovered[:_MAX_PATHS_PER_REPO]
                            break

                workflows: list[dict] = []
                any_verified = False

                if hinted_paths and verify:
                    for path in hinted_paths[:_MAX_PATHS_PER_REPO]:  # cap verification per repo
                        raw_url = _raw_url(full, branch, path)
                        parsed = _fetch_json_capped(raw_url, max_json_bytes)
                        is_wf = False
                        if isinstance(parsed, (dict, list)):
                            try:
                                is_wf = bool(json_validator(parsed))
                            except Exception:
                                is_wf = False
                        if is_wf:
                            any_verified = True
                        name = os.path.basename(path)
                        if name.lower().endswith(".json"):
                            name = name[:-5]
                        workflows.append(
                            {
                                "name": name,
                                "path": path,
                                "json_url": raw_url,
                                "blob_url": _blob_url(full, branch, path),
                                "verified": is_wf,
                            }
                        )
                    # Keep only verified, unless verification flat-out failed.
                    verified_only = [w for w in workflows if w.get("verified")]
                    if verified_only:
                        workflows = verified_only
                elif hinted_paths:
                    for path in hinted_paths[:_MAX_PATHS_PER_REPO]:
                        name = os.path.basename(path)
                        if name.lower().endswith(".json"):
                            name = name[:-5]
                        workflows.append(
                            {
                                "name": name,
                                "path": path,
                                "json_url": _raw_url(full, branch, path),
                                "blob_url": _blob_url(full, branch, path),
                                "verified": False,
                            }
                        )

                # If we have no JSON candidates (topic/desc-only repo), drop
                # when verification is on. Otherwise emit the repo as an
                # unverified hint.
                if not workflows:
                    if verify:
                        # nothing to point at — skip
                        continue
                    items.append(
                        {
                            "source": source_label,
                            "tool": tool,
                            "title": full,
                            "url": repo_html,
                            "json_url": "",
                            "docs_url": repo_html,
                            "meta": _meta_line(stars, [], description),
                            "verified": False,
                            "json_path": "",
                            "repo_full_name": full,
                            "stars": stars,
                            "pushed_at": pushed_at,
                            "workflow_count": 0,
                            "workflows": [],
                            "skills_count": 0,
                        }
                    )
                    continue

                first = workflows[0]
                title = f"{full}: {first['name']}" if first.get("name") else full
                items.append(
                    {
                        "source": source_label,
                        "tool": tool,
                        "title": title,
                        "url": repo_html,
                        "json_url": first.get("json_url", ""),
                        "docs_url": repo_html,
                        "meta": _meta_line(stars, workflows, description),
                        "verified": any_verified,
                        "json_path": first.get("path", ""),
                        "repo_full_name": full,
                        "stars": stars,
                        "pushed_at": pushed_at,
                        "workflow_count": len(workflows),
                        "workflows": workflows,
                        # Alias for state.py / skill_db.py reuse (they read
                        # ``skills_count`` for the delta logic).
                        "skills_count": len(workflows),
                    }
                )
            except Exception as exc:
                print(f"[workflows:github:item] {full!r}: {exc}", file=sys.stderr)
                continue

        # Hard filter: drop items that didn't pass JSON-structure verification.
        # Unverified candidates are GitHub code-search false-positives —
        # random JSONs (UI configs, SDK changelogs, dictionaries) that happen
        # to contain words like "nodes" or "blueprint" but are NOT importable
        # n8n / Make workflows. Letting them through wastes LLM tokens on
        # mass-excluded'ing them in the analyzer. Keep RATE_LIMITED-derived
        # items (verified=False because we *couldn't check*, not because we
        # checked and it failed) — those get a separate marker.
        before = len(items)
        items = [it for it in items if it.get("verified") is True]
        dropped = before - len(items)
        if dropped:
            print(
                f"[workflows:github] dropped {dropped} unverified candidate(s) "
                f"(failed JSON-structure check)", file=sys.stderr
            )

        return _select_with_recency(items, max_items)
    except Exception as exc:
        print(f"[workflows:github] error: {exc}", file=sys.stderr)
        return []


# Fraction of the cap reserved for highest-star repos; the rest is filled by
# most-recently-pushed repos so NEW low-star workflows aren't truncated out by
# the star sort (the root cause of the pipeline only ever seeing the same
# top-N popular repos).
_STAR_QUOTA_FRACTION = 0.7
_MAX_PATHS_PER_REPO = 8


def _select_with_recency(items: list[dict], max_items: int) -> list[dict]:
    """Pick up to ``max_items``: a star-ranked head + a recency-ranked tail.

    Pure star-sort truncation makes the pipeline re-chew the same popular repos
    every run; interleaving the freshest-pushed repos rotates new candidates in.
    """
    if len(items) <= max_items:
        return sorted(items, key=lambda x: -(x.get("stars") or 0))
    by_stars = sorted(items, key=lambda x: -(x.get("stars") or 0))
    by_recency = sorted(items, key=lambda x: x.get("pushed_at") or "", reverse=True)
    star_quota = int(max_items * _STAR_QUOTA_FRACTION)
    selected: list[dict] = []
    seen: set[str] = set()
    for it in by_stars[:star_quota]:
        full = it.get("repo_full_name") or ""
        if full and full not in seen:
            seen.add(full)
            selected.append(it)
    for it in by_recency:
        if len(selected) >= max_items:
            break
        full = it.get("repo_full_name") or ""
        if full and full not in seen:
            seen.add(full)
            selected.append(it)
    return selected


__all__ = ["fetch_workflows", "list_repo_workflows", "_repo_meta", "RATE_LIMITED"]
