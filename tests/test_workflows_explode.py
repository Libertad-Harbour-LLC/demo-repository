"""Fix 2: per-workflow catalog explosion + full repo enumeration."""
from __future__ import annotations

import sys
import types

from workflows.sources import _github_common as gh


def _load_orchestrator():
    if "anthropic" not in sys.modules:
        m = types.ModuleType("anthropic")
        m.Anthropic = lambda *a, **k: None
        sys.modules["anthropic"] = m
    from workflows import workflows as wf
    return wf


# --- full repo enumeration (git tree) ---------------------------------------

def test_list_repo_workflows_filters_and_caps(monkeypatch):
    tree = {"tree": [
        {"type": "blob", "path": "workflows/a.json"},
        {"type": "blob", "path": "workflows/b.json"},
        {"type": "blob", "path": "package.json"},        # skipped (non-workflow)
        {"type": "blob", "path": "README.md"},           # skipped (not json)
        {"type": "tree", "path": "workflows"},            # skipped (dir)
        {"type": "blob", "path": "deep/c.json"},
    ]}
    monkeypatch.setattr(gh, "_safe_get", lambda url, params=None: tree)
    # every fetched json validates as a workflow
    monkeypatch.setattr(gh, "_fetch_json_capped", lambda url, mb: {"nodes": [], "connections": {}})

    out = gh.list_repo_workflows("o/r", "main", lambda p: True, limit=2)
    assert len(out) == 2  # capped
    assert out[0]["name"] == "a" and out[0]["path"] == "workflows/a.json"
    assert out[0]["json_url"].endswith("/main/workflows/a.json")
    assert "blob/main/workflows/a.json" in out[0]["blob_url"]


def test_list_repo_workflows_drops_invalid(monkeypatch):
    tree = {"tree": [{"type": "blob", "path": "a.json"}, {"type": "blob", "path": "b.json"}]}
    monkeypatch.setattr(gh, "_safe_get", lambda url, params=None: tree)
    monkeypatch.setattr(gh, "_fetch_json_capped", lambda url, mb: {"not": "a workflow"})
    out = gh.list_repo_workflows("o/r", "main", lambda p: "nodes" in p, limit=10)
    assert out == []  # validator rejects all


def test_list_repo_workflows_empty_on_tree_failure(monkeypatch):
    monkeypatch.setattr(gh, "_safe_get", lambda url, params=None: None)
    assert gh.list_repo_workflows("o/r", "main", lambda p: True) == []


# --- owner/repo parsing + explosion -----------------------------------------

def test_owner_repo_from():
    wf = _load_orchestrator()
    assert wf._owner_repo_from({"name": "acme/flows: lead-scraper"}) == "acme/flows"
    assert wf._owner_repo_from({"url": "https://github.com/acme/flows"}) == "acme/flows"
    assert wf._owner_repo_from({"name": "just a title", "url": "x"}) is None


def test_explode_promotions_one_entry_per_workflow(monkeypatch):
    wf = _load_orchestrator()
    monkeypatch.setattr(gh, "_repo_meta", lambda full: {"default_branch": "main"})
    monkeypatch.setattr(gh, "list_repo_workflows", lambda full, branch, val, limit=25: [
        {"name": "lead-scraper", "path": "w/lead.json",
         "json_url": "https://raw/.../lead.json", "blob_url": "https://github.com/acme/flows/blob/main/w/lead.json"},
        {"name": "seo-audit", "path": "w/seo.json",
         "json_url": "https://raw/.../seo.json", "blob_url": "https://github.com/acme/flows/blob/main/w/seo.json"},
    ])
    top_test = [{"name": "acme/flows", "url": "https://github.com/acme/flows",
                 "tool": "n8n", "category": "marketing_workflow", "final_score": 7.0}]
    out = wf._explode_promotions(top_test)
    assert len(out) == 2
    names = {e["name"] for e in out}
    assert names == {"acme/flows: lead-scraper", "acme/flows: seo-audit"}
    for e in out:
        assert e["category"] == "marketing_workflow"   # inherited
        assert e["repo_full_name"] == "acme/flows"
        assert e["url"].startswith("https://github.com/acme/flows/blob/")
        assert e["skills_in_repo"] and len(e["skills_in_repo"]) == 1


def test_explode_falls_back_when_no_workflows(monkeypatch):
    wf = _load_orchestrator()
    monkeypatch.setattr(gh, "_repo_meta", lambda full: {"default_branch": "main"})
    monkeypatch.setattr(gh, "list_repo_workflows", lambda *a, **k: [])
    entry = {"name": "acme/flows", "url": "https://github.com/acme/flows", "tool": "n8n"}
    out = wf._explode_promotions([entry])
    assert out == [entry]  # unchanged single repo entry
