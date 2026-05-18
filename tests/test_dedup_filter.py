"""Tests for the _is_worth_showing dedup filter in trendwatch."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "trendwatch") not in sys.path:
    sys.path.insert(0, str(ROOT / "trendwatch"))


def _load_filter():
    # Importing trendwatch.trendwatch pulls in anthropic; skip if missing.
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "trendwatch_orchestrator", ROOT / "trendwatch" / "trendwatch.py"
    )
    try:
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod._is_worth_showing
    except ImportError:
        import pytest
        pytest.skip("anthropic SDK not installed in this env")


def test_new_item_passes():
    f = _load_filter()
    assert f({"is_new": True, "stars": 0}) is True


def test_has_new_skills_passes():
    f = _load_filter()
    assert f({"is_new": False, "has_new_skills": True, "stars": 0}) is True


def test_star_delta_5_passes():
    f = _load_filter()
    assert f({"is_new": False, "delta_stars": 5, "stars": 100}) is True


def test_star_delta_below_5_with_low_stars_filtered():
    f = _load_filter()
    assert f({"is_new": False, "delta_stars": 1, "stars": 50}) is False


def test_high_star_repo_always_passes():
    """100+ stars → always re-evaluated by the LLM, even without delta.
    Otherwise a 7k-star repo that we saw once with zero daily growth
    would silently vanish from analysis forever.
    """
    f = _load_filter()
    assert f({"is_new": False, "delta_stars": 0, "stars": 100}) is True
    assert f({"is_new": False, "delta_stars": 0, "stars": 7833}) is True


def test_below_threshold_stale_repo_filtered():
    f = _load_filter()
    assert f({"is_new": False, "delta_stars": 0, "stars": 99}) is False


def test_missing_fields_treated_as_new():
    f = _load_filter()
    # Default is_new=True when missing — first time we see it
    assert f({}) is True
