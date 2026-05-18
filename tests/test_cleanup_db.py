"""Tests for scripts/cleanup_db.py — eligibility rules and side effects."""
import importlib.util
import json
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "cleanup_db", ROOT / "scripts" / "cleanup_db.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


TODAY = date(2026, 6, 1)


def test_eligible_when_low_score_and_old():
    m = _load_module()
    item = {"final_score": 3.5, "first_recommended": "2026-04-01"}
    ok, _ = m._is_eligible(item, TODAY)
    assert ok is True


def test_protected_when_added_manually():
    m = _load_module()
    item = {"final_score": 1.0, "first_recommended": "2025-01-01",
            "added_manually": True}
    ok, reason = m._is_eligible(item, TODAY)
    assert ok is False
    assert "added_manually" in reason


def test_kept_when_score_above_threshold():
    m = _load_module()
    item = {"final_score": 4.0, "first_recommended": "2025-01-01"}
    ok, reason = m._is_eligible(item, TODAY)
    assert ok is False
    assert "threshold" in reason


def test_kept_when_too_young():
    m = _load_module()
    item = {"final_score": 2.0, "first_recommended": "2026-05-20"}  # 12 days old
    ok, reason = m._is_eligible(item, TODAY)
    assert ok is False
    assert "days old" in reason


def test_kept_when_score_missing():
    m = _load_module()
    item = {"final_score": None, "first_recommended": "2025-01-01"}
    ok, reason = m._is_eligible(item, TODAY)
    assert ok is False
    assert "not numeric" in reason


def test_kept_when_date_unparseable():
    m = _load_module()
    item = {"final_score": 1.0, "first_recommended": "not-a-date"}
    ok, reason = m._is_eligible(item, TODAY)
    assert ok is False
    assert "unparseable" in reason


def test_cleanup_one_full_lifecycle(tmp_path):
    m = _load_module()
    rec = tmp_path / "recommended.json"
    retired = tmp_path / "retired.json"
    rec.write_text(json.dumps({
        "skills": {
            "https://github.com/a/bad":  {"final_score": 2.0, "first_recommended": "2026-01-01",
                                          "repo_full_name": "a/bad"},
            "https://github.com/b/good": {"final_score": 7.0, "first_recommended": "2026-01-01",
                                          "repo_full_name": "b/good"},
            "https://github.com/c/manual": {"final_score": 0.0, "first_recommended": "2026-01-01",
                                            "added_manually": True, "repo_full_name": "c/manual"},
            "https://github.com/d/young": {"final_score": 2.0, "first_recommended": "2026-05-25",
                                           "repo_full_name": "d/young"},
        }
    }), encoding="utf-8")

    counts = m.cleanup_one(rec, retired, TODAY)

    assert counts["checked"] == 4
    assert counts["retired"] == 1
    assert counts["kept_high_score"] == 1
    assert counts["kept_manually"] == 1
    assert counts["kept_young"] == 1

    after = json.loads(rec.read_text(encoding="utf-8"))
    assert "https://github.com/a/bad" not in after["skills"]
    assert "https://github.com/b/good" in after["skills"]
    assert "https://github.com/c/manual" in after["skills"]
    assert "https://github.com/d/young" in after["skills"]

    log = json.loads(retired.read_text(encoding="utf-8"))
    assert len(log["retired"]) == 1
    assert log["retired"][0]["repo_full_name"] == "a/bad"
    assert log["retired"][0]["retired_at"] == "2026-06-01"


def test_cleanup_one_dry_run_does_not_mutate(tmp_path):
    m = _load_module()
    rec = tmp_path / "recommended.json"
    retired = tmp_path / "retired.json"
    payload = {
        "skills": {
            "https://github.com/x/bad": {"final_score": 1.0, "first_recommended": "2026-01-01",
                                         "repo_full_name": "x/bad"}
        }
    }
    rec.write_text(json.dumps(payload), encoding="utf-8")

    counts = m.cleanup_one(rec, retired, TODAY, dry_run=True)

    assert counts["retired"] == 1
    # File should NOT have been mutated
    after = json.loads(rec.read_text(encoding="utf-8"))
    assert "https://github.com/x/bad" in after["skills"]
    assert not retired.exists()


def test_retired_log_appends_across_runs(tmp_path):
    m = _load_module()
    rec = tmp_path / "recommended.json"
    retired = tmp_path / "retired.json"

    # First run retires 1 item
    rec.write_text(json.dumps({
        "skills": {
            "https://github.com/a/old": {"final_score": 2.0, "first_recommended": "2026-01-01",
                                         "repo_full_name": "a/old"}
        }
    }), encoding="utf-8")
    m.cleanup_one(rec, retired, TODAY)

    # Second run with a different item
    rec.write_text(json.dumps({
        "skills": {
            "https://github.com/b/old": {"final_score": 1.0, "first_recommended": "2026-02-01",
                                         "repo_full_name": "b/old"}
        }
    }), encoding="utf-8")
    m.cleanup_one(rec, retired, TODAY)

    log = json.loads(retired.read_text(encoding="utf-8"))
    names = {r["repo_full_name"] for r in log["retired"]}
    assert names == {"a/old", "b/old"}
