"""GitHub source — searches for ready-made Make (Integromat) blueprint JSONs.

A Make blueprint JSON typically contains either ``flow`` (list of modules)
or ``modules`` (older Integromat export), often wrapped in a top-level
``blueprint`` object.
"""
from __future__ import annotations

from ._github_common import fetch_workflows


def _is_make_blueprint(parsed) -> bool:
    if not isinstance(parsed, dict):
        return False
    if "flow" in parsed or "modules" in parsed:
        return True
    bp = parsed.get("blueprint")
    if isinstance(bp, dict) and ("flow" in bp or "modules" in bp):
        return True
    return False


def fetch_make_github(
    topics: list[str],
    code_queries: list[str],
    since_hours: int = 24,
    max_items: int = 15,
    verify: bool = True,
    max_json_bytes: int = 200_000,
) -> list[dict]:
    return fetch_workflows(
        tool="make",
        source_label="github_make",
        topics=topics,
        code_queries=code_queries,
        description_keywords=["make blueprint", "integromat blueprint"],
        json_validator=_is_make_blueprint,
        since_hours=since_hours,
        max_items=max_items,
        verify=verify,
        max_json_bytes=max_json_bytes,
    )


__all__ = ["fetch_make_github"]
