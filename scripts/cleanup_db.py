"""Periodic garbage-collection for the bot's recommendation databases.

Removes from `digests/recommended.json` and `digests/workflows/recommended.json`
any entry that has:
  - final_score below SCORE_THRESHOLD, AND
  - first_recommended older than AGE_THRESHOLD_DAYS, AND
  - is NOT added_manually=True (manual curations are protected).

Removed entries are appended to `digests/retired.json` (and the
workflows counterpart) so we have an audit trail. Re-adding a retired
URL is allowed — the file is just a log.

Runs via .github/workflows/cleanup.yml weekly, plus workflow_dispatch.
Safe to run locally as well.
"""
from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent

SCORE_THRESHOLD = 4.0       # final_score < this → eligible for retirement
AGE_THRESHOLD_DAYS = 30     # AND older than this many days

REC_PATHS = [
    ("skills", ROOT / "digests" / "recommended.json",
     ROOT / "digests" / "retired.json"),
    ("workflows", ROOT / "digests" / "workflows" / "recommended.json",
     ROOT / "digests" / "workflows" / "retired.json"),
]


def _is_eligible(item: dict, today: date) -> tuple[bool, str]:
    """Return (eligible, reason). Reason is for logging."""
    if item.get("added_manually") is True:
        return False, "added_manually (protected)"
    score = item.get("final_score")
    if not isinstance(score, (int, float)):
        return False, f"final_score is {score!r} (not numeric, can't compare)"
    if score >= SCORE_THRESHOLD:
        return False, f"score {score} >= threshold {SCORE_THRESHOLD}"
    first_str = item.get("first_recommended") or ""
    try:
        first = datetime.strptime(first_str, "%Y-%m-%d").date()
    except ValueError:
        return False, f"first_recommended is {first_str!r} (unparseable)"
    age = (today - first).days
    if age < AGE_THRESHOLD_DAYS:
        return False, f"only {age} days old, need >= {AGE_THRESHOLD_DAYS}"
    return True, f"score {score} < {SCORE_THRESHOLD} and age {age}d >= {AGE_THRESHOLD_DAYS}d"


def _load_retired(retired_path: Path) -> dict:
    if not retired_path.exists():
        return {"retired": []}
    try:
        data = json.loads(retired_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"retired": []}
    if not isinstance(data, dict) or "retired" not in data:
        return {"retired": []}
    return data


def _save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def cleanup_one(rec_path: Path, retired_path: Path, today: date,
                dry_run: bool = False) -> dict:
    """Returns counts: {checked, retired, kept_manually, kept_high_score, kept_young, kept_unparseable}."""
    counts = {
        "checked": 0,
        "retired": 0,
        "kept_manually": 0,
        "kept_high_score": 0,
        "kept_young": 0,
        "kept_unparseable": 0,
    }
    if not rec_path.exists():
        print(f"[cleanup] {rec_path} does not exist, skip", file=sys.stderr)
        return counts

    db = json.loads(rec_path.read_text(encoding="utf-8"))
    skills = db.get("skills") or {}
    retired_db = _load_retired(retired_path)
    today_iso = today.isoformat()

    to_drop: list[str] = []
    for url, item in list(skills.items()):
        counts["checked"] += 1
        eligible, reason = _is_eligible(item, today)
        if not eligible:
            if "added_manually" in reason:
                counts["kept_manually"] += 1
            elif "threshold" in reason:
                counts["kept_high_score"] += 1
            elif "days old" in reason:
                counts["kept_young"] += 1
            else:
                counts["kept_unparseable"] += 1
            continue
        to_drop.append(url)
        # Append to retired log
        retired_db["retired"].append({
            "url": url,
            "repo_full_name": item.get("repo_full_name"),
            "final_score": item.get("final_score"),
            "first_recommended": item.get("first_recommended"),
            "retired_at": today_iso,
            "reason": reason,
        })
        print(f"[cleanup] retire {item.get('repo_full_name', url)} — {reason}",
              file=sys.stderr)

    if not to_drop:
        print(f"[cleanup] {rec_path.name}: nothing to retire (checked {counts['checked']})",
              file=sys.stderr)
        return counts

    counts["retired"] = len(to_drop)
    if dry_run:
        print(f"[cleanup] DRY-RUN: would retire {counts['retired']} item(s)",
              file=sys.stderr)
        return counts

    for url in to_drop:
        del skills[url]
    _save_json(rec_path, db)
    _save_json(retired_path, retired_db)
    print(f"[cleanup] {rec_path.name}: retired {counts['retired']} item(s); "
          f"appended to {retired_path.name}", file=sys.stderr)
    return counts


def main() -> int:
    dry_run = "--dry-run" in sys.argv
    today = date.today()
    overrides_today = [a for a in sys.argv if a.startswith("--today=")]
    if overrides_today:
        today = datetime.strptime(overrides_today[0].split("=", 1)[1], "%Y-%m-%d").date()

    totals = {"checked": 0, "retired": 0,
              "kept_manually": 0, "kept_high_score": 0,
              "kept_young": 0, "kept_unparseable": 0}
    for _name, rec, retired in REC_PATHS:
        c = cleanup_one(rec, retired, today, dry_run=dry_run)
        for k, v in c.items():
            totals[k] += v

    print(f"\n[cleanup] TOTAL — checked={totals['checked']} "
          f"retired={totals['retired']} "
          f"kept_manually={totals['kept_manually']} "
          f"kept_high_score={totals['kept_high_score']} "
          f"kept_young={totals['kept_young']} "
          f"kept_unparseable={totals['kept_unparseable']}",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
