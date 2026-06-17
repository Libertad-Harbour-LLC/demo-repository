"""Contract tests for the Daily Skill Radar ``## Import payload`` block.

Mirrors docs/skill-radar-import-payload.md. The block is the bot side of the
catalog-import contract — these tests pin the rules the importer relies on:
completeness, stable keys, normalization, numbers-as-numbers, single block,
plain-text descriptions, and GitHub-only repos.
"""
from __future__ import annotations

import json
import re

import pytest

from trendwatch import import_payload as ip
from trendwatch import report


# --- A realistic analyzer output + fetched items (full skill lists) ----------

def _analysis() -> dict:
    return {
        "main_takeaway": "x",
        "rankings": [{"rank": 1, "skill": "PackmindHub/packmind"}],
        "metadata": {
            "date": "2026-06-16",
            "suggested_categories": [
                {
                    "slug": "research_skill",
                    "name": "Research",
                    "count": 2,
                    "rationale": "lit-review, replication-package — научный workflow.",
                }
            ],
        },
        "top_test": [
            {
                "name": "PackmindHub/packmind",
                "category": "vibe_coding_skill",
                "url": "https://github.com/PackmindHub/packmind/tree/main/.claude/skills",
                # Truncated on purpose — the prose list must NOT be the source.
                "skills_in_repo": ["cli-e2e-test-authoring", "create-run-e2e-tests"],
                "description": "**Production** e2e tests 🚀 and feature-flag audits.",
                "final_score": 8.2,
            },
            {
                "name": "hodoshia/richworks-skills",
                "category": "marketing_skill",
                "url": "https://github.com/hodoshia/richworks-skills/tree/main/.claude/skills",
                "skills_in_repo": ["content-flywheel"],
                "final_score": 7.1,
            },
        ],
        "top_watch": [
            {
                "name": "Some Reddit Thread",
                "category": "general_skill",
                "url": "https://www.reddit.com/r/ClaudeAI/comments/abc/post",
                "why_interesting": "buzz",
                "signal_to_wait": "stars",
            }
        ],
    }


def _items() -> list[dict]:
    def skill(repo, name, branch="main"):
        return {
            "name": name,
            "path": f".claude/skills/{name}",
            "url": f"https://github.com/{repo}/tree/{branch}/.claude/skills/{name}",
        }

    return [
        {
            "source": "github",
            "repo_full_name": "PackmindHub/packmind",
            "url": "https://github.com/PackmindHub/packmind/tree/main/.claude/skills",
            "stars": 295,
            "skills": [
                skill("PackmindHub/packmind", n)
                for n in (
                    "cli-e2e-test-authoring",
                    "create-run-e2e-tests",
                    "feature-flags-audit",
                    "typeorm-migrations",
                    "audit-runner",
                )
            ],
        },
        {
            "source": "github",
            "repo_full_name": "hodoshia/richworks-skills",
            "url": "https://github.com/hodoshia/richworks-skills/tree/main/.claude/skills",
            "stars": 0,
            "skills": [
                skill("hodoshia/richworks-skills", n)
                for n in ("content-flywheel", "viral-script-formula", "landing-page-copy")
            ],
        },
    ]


@pytest.fixture
def payload() -> dict:
    return ip.build_payload(_analysis(), _items(), "2026-06-16")


# --- normalization -----------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("vibe_coding_skill", "vibe-coding"),
    ("ai_content_skill", "ai-content"),
    ("marketing_skill", "marketing"),
    ("general_skill", "general"),
    ("Data Skill", "data"),
    ("research_workflow", "research"),
])
def test_normalize_category(raw, expected):
    assert ip.normalize_category(raw) == expected


def test_clean_text_strips_markdown_emoji_and_wrapping_quotes():
    out = ip.clean_text('  "**Hello** 🚀 `world`"  ')
    assert out == "Hello world"
    assert "*" not in out and "`" not in out and "🚀" not in out and '"' not in out


def test_clean_text_collapses_newlines():
    assert ip.clean_text("line one\nline two") == "line one line two"


# --- completeness (the whole point) ------------------------------------------

def test_skills_are_complete_from_items_not_truncated_prose(payload):
    packmind = next(r for r in payload["repos"] if r["slug"] == "packmindhub/packmind")
    # analyzer prose listed only 2; the item has 5 — payload must carry all 5.
    assert len(packmind["skills"]) == 5
    names = {s["slug"] for s in packmind["skills"]}
    assert "feature-flags-audit" in names and "audit-runner" in names


def test_skill_url_is_canonical_deep_link(payload):
    packmind = next(r for r in payload["repos"] if r["slug"] == "packmindhub/packmind")
    for s in packmind["skills"]:
        assert s["url"].startswith(
            "https://github.com/PackmindHub/packmind/tree/main/.claude/skills/"
        )
        assert s["category"] == "vibe-coding"  # inherits repo category


# --- repo-level rules --------------------------------------------------------

def test_repo_slug_lowercase_and_url_canonical(payload):
    slugs = {r["slug"] for r in payload["repos"]}
    assert "packmindhub/packmind" in slugs  # lower-case owner/repo
    pack = next(r for r in payload["repos"] if r["slug"] == "packmindhub/packmind")
    assert pack["url"] == "https://github.com/PackmindHub/packmind"
    assert pack["name"] == "PackmindHub/packmind"  # display keeps original case


def test_decisions_present_and_correct(payload):
    by_slug = {r["slug"]: r for r in payload["repos"]}
    assert by_slug["packmindhub/packmind"]["decision"] == "test_now"
    assert by_slug["hodoshia/richworks-skills"]["decision"] == "test_now"


def test_numbers_are_numbers(payload):
    pack = next(r for r in payload["repos"] if r["slug"] == "packmindhub/packmind")
    assert isinstance(pack["rating"], (int, float))
    assert isinstance(pack["github_stars"], int) and pack["github_stars"] == 295


def test_description_is_plain_text(payload):
    pack = next(r for r in payload["repos"] if r["slug"] == "packmindhub/packmind")
    d = pack["description"]
    assert "*" not in d and "🚀" not in d and "`" not in d and "\n" not in d


def test_non_github_watch_entry_is_skipped(payload):
    # The reddit top_watch entry has no owner/repo — must not appear.
    for r in payload["repos"]:
        assert "reddit.com" not in r["url"]
        assert "/" in r["slug"] and not r["slug"].startswith("http")


# --- categories --------------------------------------------------------------

def test_active_categories_referenced_and_named(payload):
    cats = {c["slug"]: c for c in payload["categories"]}
    assert cats["vibe-coding"]["status"] == "active"
    assert cats["vibe-coding"]["name"] == "Vibe coding"
    assert cats["marketing"]["status"] == "active"


def test_suggested_category_carries_rationale_and_is_not_assigned(payload):
    cats = {c["slug"]: c for c in payload["categories"]}
    assert "research" in cats
    assert cats["research"]["status"] == "suggested"
    assert cats["research"]["rationale"]
    # suggested shelf is never assigned to a repo/skill
    assigned = {r["category"] for r in payload["repos"]}
    assigned |= {s["category"] for r in payload["repos"] for s in r["skills"]}
    assert "research" not in assigned


# --- integration with report.to_markdown ------------------------------------

_BLOCK_RE = re.compile(r"## Import payload\s*\n+```json\n(.*?)\n```", re.DOTALL)


def test_report_embeds_exactly_one_valid_json_block():
    md = report.to_markdown(_analysis(), "2026-06-16", items=_items())
    assert md.count("## Import payload") == 1
    m = _BLOCK_RE.search(md)
    assert m, "no fenced json payload block found"
    parsed = json.loads(m.group(1))  # must be valid JSON
    assert parsed["radar_version"] == "1.0"
    assert parsed["date"] == "2026-06-16"
    assert len(parsed["repos"]) == 2


def test_report_without_items_emits_no_payload():
    md = report.to_markdown(_analysis(), "2026-06-16")  # items=None (e.g. workflows)
    assert "## Import payload" not in md


def test_report_with_no_repos_emits_no_payload():
    empty = {"main_takeaway": "x", "top_test": [], "top_watch": []}
    md = report.to_markdown(empty, "2026-06-16", items=[])
    assert "## Import payload" not in md
