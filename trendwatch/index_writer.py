"""Generate browsable Markdown indexes for the recommended-skill DB.

Reads ``digests/recommended.json`` (already loaded by the caller) and writes:

- ``digests/index/all.md`` — newest first, grouped by month
- ``digests/index/by_category/<category>.md`` — one per category
- ``digests/index/by_month/<YYYY-MM>.md`` — one per month

Indexes are pure derivations of ``recommended.json`` and may be safely
regenerated on every run.
"""
from __future__ import annotations

import os
from collections import defaultdict
from typing import Iterable

CATEGORIES = (
    "marketing_skill",
    "vibe_coding_skill",
    "ai_content_skill",
    "general_skill",
)

_MONTH_NAMES = {
    "01": "January",
    "02": "February",
    "03": "March",
    "04": "April",
    "05": "May",
    "06": "June",
    "07": "July",
    "08": "August",
    "09": "September",
    "10": "October",
    "11": "November",
    "12": "December",
}


def _month_key(date_iso: str) -> str:
    """Return YYYY-MM portion of an ISO date, or 'unknown' if malformed."""
    if not date_iso or len(date_iso) < 7:
        return "unknown"
    return date_iso[:7]


def _month_label(month_key: str) -> str:
    if month_key == "unknown":
        return "Unknown date"
    year, month = month_key.split("-", 1)
    return f"{_MONTH_NAMES.get(month, month)} {year}"


def _safe(value, default: str = "") -> str:
    if value is None:
        return default
    if isinstance(value, str):
        return value
    return str(value)


def _escape_pipe(text: str) -> str:
    return text.replace("|", "\\|")


def _first_test(entry: dict) -> str:
    steps = entry.get("test_steps") or []
    if not steps:
        return ""
    first = steps[0]
    if not isinstance(first, str):
        first = str(first)
    if len(first) > 120:
        first = first[:117] + "..."
    return _escape_pipe(first)


def _repo_link(entry: dict) -> str:
    title = entry.get("title") or entry.get("repo_full_name") or ""
    url = entry.get("url") or ""
    if url and title:
        return f"[{_escape_pipe(_safe(title))}]({url})"
    if title:
        return _escape_pipe(_safe(title))
    return _escape_pipe(_safe(url))


def _table_header() -> list[str]:
    return [
        "| Date | Repo | Skills | Stars | Final Score | Confidence | First Test |",
        "|---|---|---|---|---|---|---|",
    ]


def _table_row(entry: dict) -> str:
    skills_list = entry.get("skills_in_repo") or []
    skills_str = ", ".join(skills_list[:3])
    if len(skills_list) > 3:
        skills_str += f", +{len(skills_list) - 3} more"
    return (
        "| {date} | {repo} | {skills} | {stars} | {score} | {conf} | {test} |".format(
            date=_safe(entry.get("first_recommended")),
            repo=_repo_link(entry),
            skills=_escape_pipe(skills_str),
            stars=_safe(entry.get("stars")),
            score=_safe(entry.get("final_score")),
            conf=_safe(entry.get("confidence")),
            test=_first_test(entry) or "—",
        )
    )


def _sorted_newest_first(entries: Iterable[dict]) -> list[dict]:
    return sorted(
        entries,
        key=lambda e: (e.get("first_recommended") or "", e.get("title") or ""),
        reverse=True,
    )


def _write(path: str, lines: list[str]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines).rstrip() + "\n")


def _write_all(entries: list[dict], path: str) -> None:
    lines = [
        "# Recommended Claude Skills — all time",
        "",
        f"Total: {len(entries)}",
        "",
    ]
    by_month: dict[str, list[dict]] = defaultdict(list)
    for entry in entries:
        by_month[_month_key(entry.get("first_recommended") or "")].append(entry)
    for month_key in sorted(by_month.keys(), reverse=True):
        lines.append(f"## {_month_label(month_key)}")
        lines.append("")
        lines.extend(_table_header())
        for entry in _sorted_newest_first(by_month[month_key]):
            lines.append(_table_row(entry))
        lines.append("")
    _write(path, lines)


def _write_category(category: str, entries: list[dict], path: str) -> None:
    lines = [
        f"# Recommended Claude Skills — {category}",
        "",
        f"Total: {len(entries)}",
        "",
    ]
    if entries:
        lines.extend(_table_header())
        for entry in _sorted_newest_first(entries):
            lines.append(_table_row(entry))
    else:
        lines.append("_No skills in this category yet._")
    _write(path, lines)


def _write_month(month_key: str, entries: list[dict], path: str) -> None:
    lines = [
        f"# Recommended Claude Skills — {_month_label(month_key)}",
        "",
        f"Total: {len(entries)}",
        "",
    ]
    lines.extend(_table_header())
    for entry in _sorted_newest_first(entries):
        lines.append(_table_row(entry))
    _write(path, lines)


def _write_tool(tool: str, entries: list[dict], path: str) -> None:
    lines = [
        f"# Recommended — tool: {tool}",
        "",
        f"Total: {len(entries)}",
        "",
    ]
    if entries:
        lines.extend(_table_header())
        for entry in _sorted_newest_first(entries):
            lines.append(_table_row(entry))
    else:
        lines.append("_No entries for this tool yet._")
    _write(path, lines)


def write_indexes(
    recommended_db: dict,
    base_dir: str = "digests/index",
    categories: tuple[str, ...] | None = None,
    tools: tuple[str, ...] | None = None,
    default_category: str = "general_skill",
) -> dict:
    """Write all index Markdown files. Returns paths summary for logging.

    ``categories`` overrides the canonical CATEGORIES list (used by the
    workflows pipeline which has its own category set).

    ``tools`` enables a ``by_tool/`` directory — one file per tool (e.g.
    ``n8n``, ``make``, ``other``). Entries are grouped by their ``tool``
    field. When ``None`` (default), the by_tool dir is not written —
    backwards compatible with the original skill-pipeline call sites.
    """
    cats: tuple[str, ...] = tuple(categories) if categories else CATEGORIES
    skills_map = (recommended_db or {}).get("skills", {}) or {}
    entries = [v for v in skills_map.values() if isinstance(v, dict)]

    all_path = os.path.join(base_dir, "all.md")
    _write_all(entries, all_path)

    by_cat_dir = os.path.join(base_dir, "by_category")
    by_cat_paths: list[str] = []
    by_category: dict[str, list[dict]] = defaultdict(list)
    for entry in entries:
        cat = entry.get("category") or default_category
        by_category[cat].append(entry)
    # Always write the canonical categories so the links are stable
    for cat in cats:
        cat_path = os.path.join(by_cat_dir, f"{cat}.md")
        _write_category(cat, by_category.get(cat, []), cat_path)
        by_cat_paths.append(cat_path)
    # Plus any extra categories that showed up
    for cat, items in by_category.items():
        if cat in cats:
            continue
        cat_path = os.path.join(by_cat_dir, f"{cat}.md")
        _write_category(cat, items, cat_path)
        by_cat_paths.append(cat_path)

    by_month: dict[str, list[dict]] = defaultdict(list)
    for entry in entries:
        by_month[_month_key(entry.get("first_recommended") or "")].append(entry)
    by_month_dir = os.path.join(base_dir, "by_month")
    by_month_paths: list[str] = []
    for month_key, month_entries in by_month.items():
        if month_key == "unknown":
            continue
        month_path = os.path.join(by_month_dir, f"{month_key}.md")
        _write_month(month_key, month_entries, month_path)
        by_month_paths.append(month_path)

    by_tool_paths: list[str] = []
    if tools:
        by_tool_dir = os.path.join(base_dir, "by_tool")
        by_tool: dict[str, list[dict]] = defaultdict(list)
        for entry in entries:
            t = (entry.get("tool") or "other").lower()
            by_tool[t].append(entry)
        for t in tools:
            tool_path = os.path.join(by_tool_dir, f"{t}.md")
            _write_tool(t, by_tool.get(t, []), tool_path)
            by_tool_paths.append(tool_path)
        for t, items in by_tool.items():
            if t in tools:
                continue
            tool_path = os.path.join(by_tool_dir, f"{t}.md")
            _write_tool(t, items, tool_path)
            by_tool_paths.append(tool_path)

    result = {
        "all": all_path,
        "by_category": by_cat_paths,
        "by_month": by_month_paths,
    }
    if tools:
        result["by_tool"] = by_tool_paths
    return result


__all__ = ["write_indexes", "CATEGORIES"]
