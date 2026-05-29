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
    "content_skill",
    "video_skill",
    "photo_skill",
    "design_skill",
    "webdev_skill",
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


WORKFLOWS_CATEGORIES = (
    "marketing_workflow",
    "sales_workflow",
    "content_workflow",
    "video_workflow",
    "photo_workflow",
    "web_workflow",
    "data_workflow",
    "devops_workflow",
    "general_workflow",
)
WORKFLOWS_TOOLS = ("n8n", "make", "other")


def build_index_links(
    repo_full_name: str | None = None, branch: str = DEFAULT_BRANCH
) -> dict:
    """Return a dict of public links to the skills index files."""
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


def build_workflows_index_links(
    repo_full_name: str | None = None, branch: str = DEFAULT_BRANCH
) -> dict:
    """Return a dict of public links to the workflows index files."""
    repo = _resolve_repo(repo_full_name)
    base_blob = f"https://github.com/{repo}/blob/{branch}/digests/workflows/index"
    base_tree = f"https://github.com/{repo}/tree/{branch}/digests/workflows/index"
    return {
        "all": f"{base_blob}/all.md",
        "by_category": {
            cat: f"{base_blob}/by_category/{cat}.md"
            for cat in WORKFLOWS_CATEGORIES
        },
        "by_tool": {
            t: f"{base_blob}/by_tool/{t}.md" for t in WORKFLOWS_TOOLS
        },
        "by_month": f"{base_tree}/by_month",
    }


def build_footer(
    repo_full_name: str | None = None,
    branch: str = DEFAULT_BRANCH,
    category: str = "skills",
) -> str:
    """Compose a short plain-text footer with index links for Telegram.

    ``category`` selects which set of indexes to link: ``"skills"`` (default,
    points at ``digests/index``) or ``"workflows"`` (points at
    ``digests/workflows/index`` and adds a by-tool block).
    """
    if category == "workflows":
        links = build_workflows_index_links(
            repo_full_name=repo_full_name, branch=branch
        )
        lines = [
            "",
            "\U0001f5c2 База рекомендованных workflows:",
            f"\U0001f517 Все: {links['all']}",
            f"\U0001f4c5 По месяцам: {links['by_month']}",
            "⚙️ По инструменту:",
        ]
        for tool, url in links["by_tool"].items():
            lines.append(f"  • {tool}: {url}")
        lines.append("\U0001f3f7 По категориям:")
        for cat, url in links["by_category"].items():
            lines.append(f"  • {cat}: {url}")
        return "\n".join(lines)

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


__all__ = [
    "build_index_links",
    "build_workflows_index_links",
    "build_footer",
    "DEFAULT_REPO",
    "DEFAULT_BRANCH",
    "WORKFLOWS_CATEGORIES",
    "WORKFLOWS_TOOLS",
]
