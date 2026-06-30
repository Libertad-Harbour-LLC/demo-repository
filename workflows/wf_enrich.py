"""Populate the four catalog fields on workflows ``recommended.json`` entries.

For each entry we need the actual workflow JSON(s): n8n ``node_count`` is the
length of the ``nodes`` array, integrations come from node types, etc. This
module is the network glue around the pure extractor in ``wf_meta`` — fetch the
repo's workflow JSONs, compute the merged fields, write them onto the entry.

The fetch is injected (``fetch_for_entry``) so the merge/assembly logic stays
unit-testable without touching GitHub. The default fetcher reuses the existing
``_github_common`` git-tree enumeration.
"""
from __future__ import annotations

import re
import sys

from workflows import wf_meta


def owner_repo_from_entry(entry: dict) -> str | None:
    """owner/repo from a recommended entry. ``repo_full_name`` is often polluted
    with a ': <workflow>' analyzer suffix, so strip at the first colon; fall back
    to the github URL."""
    rfn = (entry.get("repo_full_name") or "").split(":", 1)[0].strip()
    if rfn.count("/") == 1 and " " not in rfn:
        return rfn
    m = re.search(r"github\.com/([^/\s]+)/([^/\s#?]+)", entry.get("url") or "")
    if m:
        repo = m.group(2)
        return f"{m.group(1)}/{repo[:-4] if repo.endswith('.git') else repo}"
    return None


def _clean_name(name: str) -> str:
    n = (name or "").strip().lower()
    if n.endswith(".json"):
        n = n[:-5]
    return n


def enrich_db(
    db: dict,
    fetch_for_entry,
    *,
    urls=None,
    only_missing: bool = False,
) -> int:
    """Compute and write ``node_count``/``complexity``/``integrations``/
    ``trigger_type`` onto recommended entries.

    ``urls`` — restrict to these keys (default: all). ``only_missing`` — skip
    entries that already have ``node_count``. Returns the number updated. Never
    raises on a single entry; a fetch failure just leaves that entry untouched.
    """
    skills = (db or {}).get("skills") or {}
    keys = list(urls) if urls is not None else list(skills.keys())
    updated = 0
    for url in keys:
        entry = skills.get(url)
        if not isinstance(entry, dict):
            continue
        if only_missing and entry.get("node_count"):
            continue
        tool = (entry.get("tool") or "").lower()
        try:
            parsed = fetch_for_entry(entry) or []
        except Exception as exc:  # pragma: no cover - defensive
            print(f"[workflows:meta] fetch failed for {url}: {exc}", file=sys.stderr)
            continue
        fields = wf_meta.fields_from_workflows(tool, parsed)
        if fields:
            entry.update(fields)
            updated += 1
    return updated


def _repo_json_paths(gh, owner_repo: str, branch: str) -> list[str]:
    """All non-boilerplate .json paths in a repo via one recursive git-tree
    call (avoids fetching every file just to enumerate)."""
    import os as _os

    tree = gh._safe_get(
        f"https://api.github.com/repos/{owner_repo}/git/trees/{branch}",
        params={"recursive": "1"},
    )
    if not isinstance(tree, dict):
        return []
    out: list[str] = []
    for node in tree.get("tree") or []:
        if not isinstance(node, dict) or node.get("type") != "blob":
            continue
        path = node.get("path") or ""
        if not path.lower().endswith(".json"):
            continue
        if _os.path.basename(path).lower() in gh._NON_WORKFLOW_JSON:
            continue
        out.append(path)
    return out


def make_network_fetcher(max_per_repo: int = 25, max_bytes: int = 200_000):
    """Default ``fetch_for_entry``: returns the parsed workflow JSON object(s)
    for an entry. Per-workflow (exploded) entries fetch just their own JSON;
    repo-level entries enumerate the git tree (1 call) and fetch ONLY the JSONs
    whose basename matches ``skills_in_repo`` — keeping the request count low
    enough to backfill the whole DB in one pass."""
    from workflows.sources import _github_common as gh

    def fetch(entry: dict) -> list:
        owner_repo = owner_repo_from_entry(entry)
        if not owner_repo:
            return []
        names = entry.get("skills_in_repo") or []
        json_url = entry.get("json_url") or ""
        # Exploded single-workflow entry: fetch exactly its JSON.
        if json_url and len(names) == 1:
            p = gh._fetch_json_capped(json_url, max_bytes)
            return [p] if isinstance(p, (dict, list)) else []
        try:
            meta = gh._repo_meta(owner_repo)
            branch = meta.get("default_branch") or "main"
            paths = _repo_json_paths(gh, owner_repo, branch)
        except Exception as exc:
            print(f"[workflows:meta] enumerate failed {owner_repo}: {exc}",
                  file=sys.stderr)
            return []
        targets = {_clean_name(n) for n in names}
        if targets:
            selected = [
                p for p in paths
                if _clean_name(p.rsplit("/", 1)[-1]) in targets
            ]
        else:
            selected = []
        if not selected:
            # No name match (or repo-level entry): take the first few JSONs.
            selected = paths[:max_per_repo]
        out: list = []
        for path in selected[:max_per_repo]:
            p = gh._fetch_json_capped(gh._raw_url(owner_repo, branch, path), max_bytes)
            if isinstance(p, (dict, list)):
                out.append(p)
        return out

    return fetch


__all__ = ["owner_repo_from_entry", "enrich_db", "make_network_fetcher"]
