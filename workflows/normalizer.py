"""Cross-source workflow-name aggregation.

Thin wrapper around ``trendwatch.normalizer.normalize`` that swaps the
``KNOWN_TOOLS`` list for one biased toward workflow-automation platforms.
"""
from __future__ import annotations

from trendwatch import normalizer as _base

# Workflows-specific tool vocabulary
KNOWN_TOOLS: list[str] = [
    "n8n",
    "make.com",
    "make",
    "integromat",
    "zapier",
    "node-red",
    "automate.io",
    "airtable automation",
]


def normalize(items_by_source):
    """Run trendwatch's normalizer with the workflows tool vocabulary."""
    saved = list(_base.KNOWN_TOOLS)
    try:
        _base.KNOWN_TOOLS[:] = KNOWN_TOOLS
        return _base.normalize(items_by_source)
    finally:
        _base.KNOWN_TOOLS[:] = saved


def annotate_only(items_by_source):
    _, annotated = normalize(items_by_source)
    return annotated


__all__ = ["KNOWN_TOOLS", "normalize", "annotate_only"]
