"""GitHub source — searches for ready-made n8n workflow JSONs.

An n8n workflow JSON has top-level (or nested) ``nodes`` and ``connections``
keys. We verify candidates by fetching the JSON (capped at MAX_JSON_BYTES)
and looking for those keys.
"""
from __future__ import annotations

from ._github_common import fetch_workflows


def _is_n8n_node_set(d) -> bool:
    return isinstance(d, dict) and "nodes" in d and "connections" in d


def _is_n8n_workflow(parsed) -> bool:
    # single workflow: {nodes, connections}
    if _is_n8n_node_set(parsed):
        return True
    if isinstance(parsed, dict):
        # wrapped under "workflow"
        if _is_n8n_node_set(parsed.get("workflow")):
            return True
        # collection keyed by id/name: {"<id>": {nodes, connections}, ...}
        for v in parsed.values():
            if _is_n8n_node_set(v) or _is_n8n_node_set(
                v.get("workflow") if isinstance(v, dict) else None
            ):
                return True
    # array of workflows: [{nodes, connections}, ...]
    if isinstance(parsed, list):
        for x in parsed:
            if _is_n8n_node_set(x) or _is_n8n_node_set(
                x.get("workflow") if isinstance(x, dict) else None
            ):
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
