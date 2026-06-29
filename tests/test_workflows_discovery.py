"""Workflows discovery: broadened JSON validators + recency-aware selection."""
from __future__ import annotations

from workflows.sources._github_common import _select_with_recency
from workflows.sources.make_github import _is_make_blueprint
from workflows.sources.n8n_github import _is_n8n_workflow


# --- validators accept more real-world shapes (Fix 5) -----------------------

def test_n8n_validator_accepts_single_and_wrapped():
    assert _is_n8n_workflow({"nodes": [], "connections": {}})
    assert _is_n8n_workflow({"workflow": {"nodes": [], "connections": {}}})


def test_n8n_validator_accepts_array_and_collection():
    # array export of multiple workflows
    assert _is_n8n_workflow([{"name": "a"}, {"nodes": [], "connections": {}}])
    # collection keyed by id
    assert _is_n8n_workflow({"wf1": {"nodes": [], "connections": {}}})


def test_n8n_validator_rejects_non_workflow():
    assert not _is_n8n_workflow({"name": "package", "dependencies": {}})
    assert not _is_n8n_workflow(["just", "strings"])
    assert not _is_n8n_workflow("nodes connections")


def test_make_validator_accepts_array_and_collection():
    assert _is_make_blueprint({"flow": [], "metadata": {}})
    assert _is_make_blueprint({"blueprint": {"modules": []}})
    assert _is_make_blueprint([{"x": 1}, {"modules": []}])
    assert not _is_make_blueprint({"name": "x"})


# --- recency-aware selection (Fix 1) ----------------------------------------

def _repo(name, stars, pushed):
    return {"repo_full_name": name, "stars": stars, "pushed_at": pushed}


def test_select_returns_all_when_under_cap():
    items = [_repo("a/x", 5, "2026-01-01"), _repo("b/y", 9, "2026-02-01")]
    out = _select_with_recency(items, 10)
    assert len(out) == 2
    assert out[0]["repo_full_name"] == "b/y"  # star-sorted


def test_select_reserves_room_for_fresh_low_star_repos():
    # 5 high-star but old, 5 low-star but fresh; cap 4 with 70% star quota = 2 star + 2 fresh
    old = [_repo(f"old/{i}", 1000 - i, "2020-01-01") for i in range(5)]
    fresh = [_repo(f"fresh/{i}", 1, f"2026-06-2{i}") for i in range(5)]
    out = _select_with_recency(old + fresh, 4)
    names = [it["repo_full_name"] for it in out]
    assert len(out) == 4
    # at least one fresh low-star repo survived (would be impossible with pure star-sort)
    assert any(n.startswith("fresh/") for n in names)
    # and the top star repo is included
    assert any(n.startswith("old/") for n in names)


def test_select_dedupes():
    dup = _repo("a/x", 5, "2026-01-01")
    out = _select_with_recency([dup, dict(dup), _repo("b/y", 1, "2026-09-09")], 2)
    assert [it["repo_full_name"] for it in out].count("a/x") == 1
