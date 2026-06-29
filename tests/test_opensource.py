"""Tests for the Open Source radar pipeline + its bot integration."""
from __future__ import annotations

import sys
import types

import pytest


def _load_orchestrator():
    """Import opensource.opensource, ensuring `anthropic` is stubbed first.

    The orchestrator pulls trendwatch.analyzer -> `import anthropic`; conftest
    stubs it, but other tests in the suite pop the stub from sys.modules, so we
    (re)install a stub here to stay order-independent.
    """
    if "anthropic" not in sys.modules:
        m = types.ModuleType("anthropic")
        m.Anthropic = lambda *a, **k: None
        sys.modules["anthropic"] = m
    from opensource import opensource as oss
    return oss


# --- config ----------------------------------------------------------------

def test_config_shape():
    from opensource import config
    assert config.DATA_DIR == "digests/opensource"
    assert config.DEFAULT_CATEGORY == "general_oss"
    assert config.DEFAULT_CATEGORY in config.CATEGORIES
    assert len(config.SEED_REPOS) >= 7  # owner examples + curated
    # owner-provided seeds are present
    joined = " ".join(config.SEED_REPOS)
    assert "calesthio/OpenMontage" in joined
    assert "Autom8AI/Open-Higgsfield-AI" in joined
    assert "nesquena/hermes-webui" in joined


# --- github fetcher (mocked) -----------------------------------------------

def test_owner_repo_parse():
    from opensource.sources import github as gh
    assert gh._owner_repo("https://github.com/a/b") == "a/b"
    assert gh._owner_repo("https://github.com/a/b.git") == "a/b"
    assert gh._owner_repo("https://github.com/a/b/tree/main/x") == "a/b"
    assert gh._owner_repo("https://example.com/x") is None


def test_item_shape_from_repo():
    from opensource.sources import github as gh
    it = gh._item_from_repo({
        "full_name": "Acme/open-thing",
        "html_url": "https://github.com/Acme/open-thing",
        "stargazers_count": 123,
        "description": "Open source alternative to PaidThing",
        "default_branch": "main",
        "topics": ["self-hosted", "ai"],
    })
    assert it["repo_full_name"] == "Acme/open-thing"
    assert it["stars"] == 123
    assert it["source"] == "github"
    assert "⭐ 123" in it["meta"]


def test_fetch_injects_seeds_first_and_dedupes(monkeypatch):
    from opensource.sources import github as gh

    def fake_get(url, params=None):
        if url.startswith(gh.REPO_API_URL):  # seed meta
            full = url.split("/repos/", 1)[1]
            return {"full_name": full, "html_url": f"https://github.com/{full}",
                    "stargazers_count": 5, "description": "seed product",
                    "default_branch": "main"}
        # search endpoints: return one popular repo (also a dup of a seed)
        return {"items": [
            {"full_name": "popular/repo", "html_url": "https://github.com/popular/repo",
             "stargazers_count": 9000, "description": "big", "default_branch": "main"},
            {"full_name": "calesthio/OpenMontage", "html_url": "https://github.com/calesthio/OpenMontage",
             "stargazers_count": 800, "description": "dup of a seed", "default_branch": "main"},
        ]}

    monkeypatch.setattr(gh, "_get", fake_get)
    items = gh.fetch_opensource(
        topics=["self-hosted"],
        desc_queries=['"open source alternative" in:readme'],
        seed_repos=["https://github.com/calesthio/OpenMontage",
                    "https://github.com/Autom8AI/Open-Higgsfield-AI"],
        max_items=50,
    )
    fulls = [it["repo_full_name"] for it in items]
    # dedupe: OpenMontage appears once even though it's both a seed and a search hit
    assert fulls.count("calesthio/OpenMontage") == 1
    # seeds come first (before the 9000-star popular repo)
    assert items[0].get("_seed") is True
    assert "popular/repo" in fulls


# --- orchestrator filter ----------------------------------------------------

def test_is_worth_showing():
    oss = _load_orchestrator()
    assert oss._is_worth_showing({"_seed": True, "is_new": False, "stars": 1})
    assert oss._is_worth_showing({"is_new": True})
    assert oss._is_worth_showing({"is_new": False, "delta_stars": 7, "stars": 1})
    assert oss._is_worth_showing({"is_new": False, "stars": 50})
    assert not oss._is_worth_showing({"is_new": False, "delta_stars": 0, "stars": 3})


# --- bot integration --------------------------------------------------------

def test_bot_has_opensource_source():
    from api import telegram as tg
    assert "opensource" in tg.SOURCES
    src = tg.SOURCES["opensource"]
    assert src.tool_filter is None
    assert src.default_category == "general_oss"
    assert "digests/opensource/recommended.json" in src.url
    assert "opensource" in tg.VALID_SOURCES


def test_bot_reply_button_maps_to_opensource():
    from api import telegram as tg
    # the persistent button text must route to the source
    kb = tg._reply_keyboard()
    texts = [b["text"] for row in kb["keyboard"] for b in row]
    assert "📦 Open Source" in texts


def test_bot_category_label_for_oss():
    from api import telegram as tg
    out = tg._safe_cat_label("opensource", "agents_oss")
    assert "Агенты" in out
    assert "agents_oss" not in out  # mapped to human label, no raw slug


def test_route_parse_accepts_opensource():
    from api import telegram as tg
    r = tg.Route.parse("src:opensource:menu")
    assert r is not None and r.source_key == "opensource"
