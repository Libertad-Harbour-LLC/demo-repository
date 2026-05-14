"""Build public github.com URLs to the persistent skill-DB indexes.

GitHub Actions automatically sets ``GITHUB_REPOSITORY`` (``owner/repo``); for
local runs we fall back to a hard-coded default that matches the project
where trendwatch lives. This module produces only public URLs — no secrets.
"""
from __future__ import annotations

import os

DEFAULT_REPO = "Libertad-Harbour-LLC/demo-repository"
DEFAULT_BRANCH = "main"

CATEGORIES = (
    "marketing_skill",
    "vibe_coding_skill",
    "ai_content_skill",
    "general_skill",
)


def _resolve_repo(repo_full_name: str | None) -> str:
    if repo_full_name:
        return repo_full_name
    env = os.environ.get("GITHUB_REPOSITORY") or ""
    if env and "/" in env:
        return env
    return DEFAULT_REPO


def build_index_links(
    repo_full_name: str | None = None, branch: str = DEFAULT_BRANCH
) -> dict:
    """Return a dict of public links to the index files."""
    repo = _resolve_repo(repo_full_name)
    base_blob = f"https://github.com/{repo}/blob/{branch}/digests/index"
    base_tree = f"https://github.com/{repo}/tree/{branch}/digests/index"
    return {
        "all": f"{base_blob}/all.md",
        "by_category": {
            cat: f"{base_blob}/by_category/{cat}.md" for cat in CATEGORIES
        },
        "by_month": f"{base_tree}/by_month",
    }


def build_footer(repo_full_name: str | None = None, branch: str = DEFAULT_BRANCH) -> str:
    """Compose a short plain-text footer with index links for Telegram."""
    links = build_index_links(repo_full_name=repo_full_name, branch=branch)
    lines = [
        "",
        "\U0001f5c2 База рекомендованных skills:",
        f"\U0001f517 Все: {links['all']}",
        f"\U0001f4c5 По месяцам: {links['by_month']}",
        "\U0001f3f7 По категориям:",
    ]
    for cat, url in links["by_category"].items():
        lines.append(f"  • {cat}: {url}")
    return "\n".join(lines)


__all__ = ["build_index_links", "build_footer", "DEFAULT_REPO", "DEFAULT_BRANCH"]
