"""Backfill URL parsing — owner/repo + optional branch from /tree/<branch>/.

Loads the orchestrator the same way test_dedup_filter does: importing
trendwatch.trendwatch pulls in anthropic, so we load via spec and skip when
the SDK isn't installed (CI has it).
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "trendwatch") not in sys.path:
    sys.path.insert(0, str(ROOT / "trendwatch"))


def _load():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "trendwatch_orchestrator_bf", ROOT / "trendwatch" / "trendwatch.py"
    )
    try:
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except ImportError:
        pytest.skip("anthropic SDK not installed in this env")


def test_parse_plain_repo_url():
    assert _load()._parse_repo_url("https://github.com/owner/repo") == ("owner/repo", None)


def test_parse_repo_url_with_branch_deeplink():
    owner_repo, branch = _load()._parse_repo_url(
        "https://github.com/appwrite/appwrite/tree/1.9.x/.claude/skills"
    )
    assert owner_repo == "appwrite/appwrite"
    assert branch == "1.9.x"


def test_parse_repo_url_specific_skill_deeplink():
    owner_repo, branch = _load()._parse_repo_url(
        "https://github.com/paperclipai/paperclip/tree/master/.claude/skills/design-guide"
    )
    assert owner_repo == "paperclipai/paperclip"
    assert branch == "master"


def test_parse_strips_dot_git_and_rejects_nongithub():
    mod = _load()
    assert mod._parse_repo_url("https://github.com/a/b.git") == ("a/b", None)
    assert mod._parse_repo_url("https://example.com/x/y") == (None, None)
