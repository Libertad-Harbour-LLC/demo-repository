"""Post-LLM guards in trendwatch/analyzer.py: coverage audit and
'also considered' tail injection. No network — pure dict mutation tests.
"""
import importlib.util
import io
import sys
from contextlib import redirect_stderr
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load():
    spec = importlib.util.spec_from_file_location(
        "trendwatch_analyzer", ROOT / "trendwatch" / "analyzer.py"
    )
    try:
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except ImportError:
        pytest.skip("anthropic SDK not installed in this env")


# --- _audit_promotion_coverage --------------------------------------------

def test_audit_warns_when_pool_dropped():
    m = _load()
    parsed = {"top_test": [], "top_watch": [{"name": "a"}]}
    inputs = [{"url": f"u{i}"} for i in range(10)]
    buf = io.StringIO()
    with redirect_stderr(buf):
        m._audit_promotion_coverage(parsed, inputs)
    assert "WARN low promotion coverage" in buf.getvalue()
    assert "inputs=10 promoted=1" in buf.getvalue()


def test_audit_silent_when_healthy_coverage():
    m = _load()
    parsed = {
        "top_test": [{"name": "a"}, {"name": "b"}],
        "top_watch": [{"name": "c"}],
    }
    inputs = [{"url": f"u{i}"} for i in range(5)]
    buf = io.StringIO()
    with redirect_stderr(buf):
        m._audit_promotion_coverage(parsed, inputs)
    assert "WARN" not in buf.getvalue()


def test_audit_silent_when_inputs_themselves_few():
    m = _load()
    parsed = {"top_test": [], "top_watch": []}
    inputs = [{"url": "u1"}, {"url": "u2"}]  # only 2 — too few to fault analyzer
    buf = io.StringIO()
    with redirect_stderr(buf):
        m._audit_promotion_coverage(parsed, inputs)
    assert "WARN" not in buf.getvalue()


# --- _inject_also_considered_tail -----------------------------------------

def test_tail_injected_when_high_star_dropped():
    m = _load()
    parsed = {
        "telegram_summary": "🚀 Daily Skill Radar\n\nГлавное:\nничего\n",
        "top_test": [],
        "top_watch": [],
    }
    inputs = [
        {"repo_full_name": "owner/big", "url": "https://github.com/owner/big",
         "stars": 7833},
        {"repo_full_name": "owner/small", "url": "https://github.com/owner/small",
         "stars": 50},  # below threshold, won't appear
    ]
    m._inject_also_considered_tail(parsed, inputs)
    out = parsed["telegram_summary"]
    assert "🔍 Также рассмотрены" in out
    assert "owner/big" in out
    assert "⭐ 7833" in out
    assert "owner/small" not in out  # below 500 stars


def test_tail_skips_items_already_shown():
    m = _load()
    parsed = {
        "telegram_summary": "🚀 stuff\n",
        "top_test": [{"url": "https://github.com/owner/big"}],
        "top_watch": [],
    }
    inputs = [
        {"repo_full_name": "owner/big", "url": "https://github.com/owner/big",
         "stars": 7833},
    ]
    m._inject_also_considered_tail(parsed, inputs)
    # nothing new — owner/big already in top_test
    assert "Также рассмотрены" not in parsed["telegram_summary"]


def test_tail_no_op_when_model_already_emitted_section():
    m = _load()
    parsed = {
        "telegram_summary": "🚀 stuff\n\n🔍 Также рассмотрены:\n• something\n",
        "top_test": [], "top_watch": [],
    }
    inputs = [
        {"repo_full_name": "owner/big", "url": "https://github.com/owner/big",
         "stars": 7833},
    ]
    before = parsed["telegram_summary"]
    m._inject_also_considered_tail(parsed, inputs)
    assert parsed["telegram_summary"] == before  # untouched


def test_tail_capped_at_limit():
    m = _load()
    parsed = {"telegram_summary": "🚀\n", "top_test": [], "top_watch": []}
    inputs = [
        {"repo_full_name": f"owner/r{i}", "url": f"https://github.com/owner/r{i}",
         "stars": 1000 + i}
        for i in range(20)
    ]
    m._inject_also_considered_tail(parsed, inputs)
    # Should list at most ALSO_CONSIDERED_LIMIT (5) items
    out = parsed["telegram_summary"]
    bullet_count = out.count("• owner/")
    assert bullet_count == m.ALSO_CONSIDERED_LIMIT


def test_tail_sorted_by_stars_desc():
    m = _load()
    parsed = {"telegram_summary": "🚀\n", "top_test": [], "top_watch": []}
    inputs = [
        {"repo_full_name": "owner/medium", "url": "u1", "stars": 1000},
        {"repo_full_name": "owner/huge", "url": "u2", "stars": 9000},
        {"repo_full_name": "owner/big", "url": "u3", "stars": 5000},
    ]
    m._inject_also_considered_tail(parsed, inputs)
    out = parsed["telegram_summary"]
    huge_pos = out.find("owner/huge")
    big_pos = out.find("owner/big")
    medium_pos = out.find("owner/medium")
    assert 0 < huge_pos < big_pos < medium_pos
