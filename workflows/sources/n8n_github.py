"""GitHub source — searches for ready-made n8n workflow JSONs.

An n8n workflow JSON has top-level (or nested) ``nodes`` and ``connections``
keys. We verify candidates by fetching the JSON (capped at MAX_JSON_BYTES)
and looking for those keys.
"""
from __future__ import annotations

from ._github_common import fetch_workflows


def _is_n8n_workflow(parsed) -> bool:
    if not isinstance(parsed, dict):
        return False
    if "nodes" in parsed and "connections" in parsed:
        return True
    # Some n8n exports wrap workflow under "workflow" key
    inner = parsed.get("workflow")
    if isinstance(inner, dict) and "nodes" in inner and "connections" in inner:
        return True
    return False


def fetch_n8n_github(
    topics: list[str],
    code_queries: list[str],
    since_hours: int = 24,
    max_items: int = 15,
    verify: bool = True,
    max_json_bytes: int = 200_000,
) -> list[dict]:
    return fetch_workflows(
        tool="n8n",
        source_label="github_n8n",
        topics=topics,
        code_queries=code_queries,
        description_keywords=["n8n workflow", "n8n template"],
        json_validator=_is_n8n_workflow,
        since_hours=since_hours,
        max_items=max_items,
        verify=verify,
        max_json_bytes=max_json_bytes,
    )


__all__ = ["fetch_n8n_github"]
