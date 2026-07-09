"""Tests for the vercel-labs/skills borrowings:

1. skills.sh registry source (fetch + installs merge into github items)
2. git-tree skill discovery (case-insensitive SKILL.md anywhere in the repo)
3. SKILL.md frontmatter parsing in enrich (pre-LLM hint + fallback description)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from trendwatch import enrich  # noqa: E402
from trendwatch.sources import github as gh_source  # noqa: E402
from trendwatch.sources.skills_sh import fetch_skills_sh, merge_installs  # noqa: E402


# ── 1. skills.sh fetcher ────────────────────────────────────────────────
def _fake_http(responses):
    """http_get stub: returns responses[query] for the q param."""
    def get(url, params):
        return responses.get(params.get("q"))
    return get


def test_fetch_skills_sh_groups_by_repo_and_sums_installs():
    responses = {
        "marketing": {"skills": [
            {"id": "seo-writer", "name": "seo-writer", "installs": 1200,
             "source": "acme/marketing-skills"},
            {"id": "ad-copy", "name": "ad-copy", "installs": 300,
             "source": "acme/marketing-skills"},
            {"id": "react-best", "name": "react-best", "installs": 90000,
             "source": "vercel-labs/agent-skills"},
        ]},
        "video": {"skills": [
            # same skill surfaces again under another query — counted once
            {"id": "seo-writer", "name": "seo-writer", "installs": 1200,
             "source": "acme/marketing-skills"},
        ]},
    }
    items = fetch_skills_sh(["marketing", "video"], max_items=10,
                            http_get=_fake_http(responses))
    by_repo = {i["repo_full_name"]: i for i in items}
    acme = by_repo["acme/marketing-skills"]
    assert acme["installs"] == 1500          # 1200 + 300, no double count
    assert acme["skills_count"] == 2
    assert acme["source"] == "skills_sh"
    assert acme["url"] == "https://github.com/acme/marketing-skills"
    assert "⬇ 1500 installs" in acme["meta"]
    # sorted by installs desc
    assert items[0]["repo_full_name"] == "vercel-labs/agent-skills"


def test_fetch_skills_sh_survives_api_failure():
    def boom(url, params):
        raise RuntimeError("registry down")
    assert fetch_skills_sh(["a", "b"], http_get=boom) == []
    # malformed rows are skipped, not fatal
    bad = {"a": {"skills": [{"source": "not-a-repo"}, "garbage",
                            {"source": "x/y", "name": "ok", "installs": "7"}]}}
    items = fetch_skills_sh(["a"], http_get=_fake_http(bad))
    assert len(items) == 1 and items[0]["installs"] == 7


def test_merge_installs_folds_into_github_twin():
    items = {
        "github": [
            {"repo_full_name": "acme/marketing-skills", "meta": "⭐ 12 • 2 skills",
             "url": "https://github.com/acme/marketing-skills/tree/main/.claude/skills"},
        ],
        "skills_sh": [
            {"repo_full_name": "acme/marketing-skills", "installs": 1500,
             "meta": "⬇ 1500 installs"},
            {"repo_full_name": "solo/registry-only", "installs": 40,
             "meta": "⬇ 40 installs"},
        ],
    }
    merge_installs(items)
    gh = items["github"][0]
    assert gh["installs"] == 1500
    assert "1500 installs" in gh["meta"]
    # twin dropped from skills_sh; registry-only stays
    assert [i["repo_full_name"] for i in items["skills_sh"]] == ["solo/registry-only"]


def test_merge_installs_noop_without_source():
    items = {"github": [{"repo_full_name": "a/b", "meta": "x"}]}
    merge_installs(items)  # must not raise
    assert "installs" not in items["github"][0]


# ── 2. git-tree skill discovery ─────────────────────────────────────────
def _tree(paths):
    return {"tree": [{"type": "blob", "path": p} for p in paths]}


def test_tree_discovery_finds_skills_beyond_claude_dir(monkeypatch):
    tree = _tree([
        ".claude/skills/writer/SKILL.md",
        "skills/marketing/seo/SKILL.md",       # depth-2 catalog layout
        ".codex/skills/helper/skill.md",       # cross-agent dir, lowercase file
        "SKILL.md",                            # root-level skill
        "node_modules/pkg/SKILL.md",           # skipped dir
        "docs/NOTSKILL.md",                    # not a SKILL.md basename
    ])
    monkeypatch.setattr(gh_source, "_safe_get", lambda url, params=None, timeout=30: tree)
    folders = gh_source._skill_folders_from_tree("o/r", "main")
    assert folders == [
        ".claude/skills/writer",
        "skills/marketing/seo",
        ".codex/skills/helper",
        "",
    ]


def test_tree_discovery_none_and_rate_limited(monkeypatch):
    monkeypatch.setattr(gh_source, "_safe_get", lambda *a, **k: _tree(["README.md"]))
    assert gh_source._skill_folders_from_tree("o/r", "main") is None
    monkeypatch.setattr(gh_source, "_safe_get", lambda *a, **k: gh_source.RATE_LIMITED)
    assert gh_source._skill_folders_from_tree("o/r", "main") == gh_source.RATE_LIMITED
    monkeypatch.setattr(gh_source, "_safe_get", lambda *a, **k: None)
    assert gh_source._skill_folders_from_tree("o/r", "main") is None


def test_tree_discovery_caps_per_repo(monkeypatch):
    tree = _tree([f"skills/s{i}/SKILL.md" for i in range(120)])
    monkeypatch.setattr(gh_source, "_safe_get", lambda *a, **k: tree)
    folders = gh_source._skill_folders_from_tree("o/r", "main")
    assert len(folders) == gh_source._MAX_SKILLS_PER_REPO


def test_new_agent_dir_queries_present():
    from trendwatch import config
    joined = " ".join(config.GITHUB_CODE_QUERIES)
    for d in (".agents/skills", ".codex/skills", ".opencode/skills",
              ".github/skills", ".windsurf/skills"):
        assert d in joined
    assert config.SOURCES.get("skills_sh") is True
    assert len(config.SKILLS_SH_QUERIES) >= 10


# ── 3. frontmatter parsing ──────────────────────────────────────────────
def test_parse_frontmatter_scalars_and_quotes():
    md = '---\nname: seo-writer\ndescription: "Writes SEO articles for blogs"\nlicense: MIT\n---\n# Body\n'
    fm = enrich.parse_frontmatter(md)
    assert fm == {"name": "seo-writer", "description": "Writes SEO articles for blogs"}


def test_parse_frontmatter_folded_multiline():
    md = (
        "---\n"
        "name: video-cutter\n"
        "description: >-\n"
        "  Cuts long videos into shorts\n"
        "  for TikTok and Reels\n"
        "---\nbody"
    )
    fm = enrich.parse_frontmatter(md)
    assert fm["description"] == "Cuts long videos into shorts for TikTok and Reels"


def test_parse_frontmatter_absent_or_garbage():
    assert enrich.parse_frontmatter("# no frontmatter") == {}
    assert enrich.parse_frontmatter(None) == {}
    assert enrich.parse_frontmatter("---\n:::\n---\n") == {}


def test_raw_skill_md_url_accepts_blob_urls():
    assert enrich.raw_skill_md_url(
        "https://github.com/o/r/blob/main/SKILL.md"
    ) == "https://raw.githubusercontent.com/o/r/main/SKILL.md"
    assert enrich.raw_skill_md_url(
        "https://github.com/o/r/blob/dev/pkg/sub/SKILL.md"
    ) == "https://raw.githubusercontent.com/o/r/dev/pkg/sub/SKILL.md"
    # tree URLs still work as before
    assert enrich.raw_skill_md_url(
        "https://github.com/o/r/tree/main/.claude/skills/x"
    ) == "https://raw.githubusercontent.com/o/r/main/.claude/skills/x/SKILL.md"


def test_frontmatter_fallback_description_survives_llm_failure():
    payload = {"repos": [{
        "decision": "test_now", "category": "marketing", "name": "o/r",
        "skills": [{"slug": "seo-writer",
                    "url": "https://github.com/o/r/tree/main/.claude/skills/seo-writer"}],
    }]}

    def fake_fetch(url):
        return "---\nname: seo-writer\ndescription: Writes SEO articles\n---\n# T"

    def broken_llm(system, user):
        raise RuntimeError("credit balance too low")

    enrich.enrich_payload(payload, md_fetch=fake_fetch, claude_complete=broken_llm)
    skill = payload["repos"][0]["skills"][0]
    assert skill["description"] == "Writes SEO articles"


def test_frontmatter_hint_reaches_llm_prompt():
    captured = {}
    payload = {"repos": [{
        "decision": "test_now", "category": "marketing", "name": "o/r",
        "skills": [{"slug": "s",
                    "url": "https://github.com/o/r/tree/main/.claude/skills/s"}],
    }]}

    def fake_fetch(url):
        return "---\ndescription: Builds landing pages\n---\nbody"

    def fake_llm(system, user):
        captured["user"] = user
        return '{"results": [{"id": 0, "description": "Собирает лендинги", "category": "marketing", "tags": ["landing","web","copy"]}]}'

    enrich.enrich_payload(payload, md_fetch=fake_fetch, claude_complete=fake_llm)
    assert "frontmatter_description: Builds landing pages" in captured["user"]
    assert payload["repos"][0]["skills"][0]["description"] == "Собирает лендинги"
